import json
from pathlib import Path
import tempfile
import unittest
import numpy as np

from drive_order.audio import assign_sources, runs, splice_overlap, prepare_clips
from drive_order.nemotron35 import transcription_prompt, turns_from_response
from drive_order.orders import HybridInterpreter, OrderBook, RuleBasedInterpreter, validate_menu
from drive_order.trip import validate_trip

MENU = {'store_id': 'one', 'items': [{'id': 'curry', 'name': '카레'}, {'id': 'cola', 'name': '콜라'}]}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_without_separator_overlap_stays_unresolved(self):
        import soundfile as sf
        folder = Path(self.temp.name)
        wave = folder/'mix.wav'
        sf.write(wave, np.sin(np.arange(32000)*.1).astype('float32')*.1, 16000)
        probabilities = np.zeros((200, 8), dtype='float32')
        probabilities[:150, 0] = 1
        probabilities[50:, 1] = 1
        clips = prepare_clips(wave, probabilities, folder, folder/'no-models', device='cpu', separator_kind='none')
        self.assertEqual(len(clips), 2)
        self.assertTrue(all(c['overlap'] and c['needs_review'] and c['method'] == 'unresolved_overlap' for c in clips))

    def turn(self, i, speaker='speaker_0', **extra):
        return dict(id=str(i), speaker=speaker, start=float(i), end=i+.5, text='카레 콜라 주문', **extra)

    def decision(self, items):
        return {'action': 'update', 'operations': items, 'reason': '발화 근거'}

    def test_empty_recording_has_downloadable_event_stream(self):
        book = OrderBook(MENU, lambda p: None, self.temp.name)
        book.save()
        self.assertEqual(Path(self.temp.name, 'order_events.jsonl').read_text(), '')
        self.assertEqual(json.loads(Path(self.temp.name, 'orders.json').read_text())['speakers'], {})

    def item(self, id, n=1):
        return {'op': 'set', 'menu_id': id, 'quantity': n, 'options': []}

    def test_replace_cancel_and_speaker_isolation(self):
        responses = iter([self.decision([self.item('curry')]), self.decision([self.item('cola')]),
                          self.decision([{'op': 'remove', 'menu_id': 'curry'}, self.item('cola', 2)]),
                          self.decision([{'op': 'clear'}])])
        book = OrderBook(MENU, lambda p: next(responses), self.temp.name)
        book.consume(self.turn(1))
        book.consume(self.turn(2, 'speaker_1'))
        book.consume(self.turn(3))
        self.assertEqual(book.orders['speaker_0'], [{'menu_id': 'cola', 'quantity': 2, 'options': []}])
        self.assertEqual(book.orders['speaker_1'], [{'menu_id': 'cola', 'quantity': 1, 'options': []}])
        cancel = self.turn(4)
        cancel['text'] = '전부 취소요'
        book.consume(cancel)
        self.assertEqual(book.orders['speaker_0'], [])
        self.assertEqual(len(Path(self.temp.name, 'order_events.jsonl').read_text().splitlines()), 4)

    def test_unknown_menu_and_bad_quantity_do_not_mutate(self):
        for quantity, id in [(1, 'steak'), (True, 'cola'), (-1, 'cola'), (1.2, 'cola')]:
            book = OrderBook(MENU, lambda p: self.decision([self.item(id, quantity)]), self.temp.name)
            event = book.consume(self.turn(1))
            self.assertEqual(event['decision']['action'], 'clarify')
            self.assertEqual(book.orders, {})

    def test_uncertain_audio_cannot_change_state_or_context(self):
        def forbidden(payload):
            self.fail('LLM must not receive uncertain audio')
        book = OrderBook(MENU, forbidden, self.temp.name)
        book.consume(self.turn(1, needs_review=True))
        self.assertEqual(book.orders, {})
        self.assertEqual(book.recent, [])

    def test_duplicates_and_ordering(self):
        book = OrderBook(MENU, lambda p: self.decision([{'op': 'clear'}]), self.temp.name)
        book.consume(self.turn(2))
        self.assertIsNone(book.consume(self.turn(2)))
        with self.assertRaises(ValueError):
            book.consume(self.turn(1))

    def test_long_conversation_keeps_bounded_context_and_all_events(self):
        def interpret(payload):
            self.assertLessEqual(len(payload['recent']), 8)
            return {'action': 'noop', 'reason': '질문', 'items': []}
        book = OrderBook(MENU, interpret, self.temp.name)
        for i in range(200):
            book.consume(self.turn(i))
        self.assertEqual(len(book.recent), 8)
        self.assertEqual(len(Path(self.temp.name, 'order_events.jsonl').read_text().splitlines()), 200)

    def test_invalid_patch_rolls_back_all_operations(self):
        responses = iter([self.decision([self.item('curry')]), self.decision([
            {'op': 'remove', 'menu_id': 'curry'}, self.item('unknown')])])
        book = OrderBook(MENU, lambda p: next(responses), self.temp.name)
        book.consume(self.turn(1))
        before = json.loads(json.dumps(book.orders))
        self.assertEqual(book.consume(self.turn(2))['decision']['action'], 'clarify')
        self.assertEqual(book.orders, before)

    def test_other_speaker_history_is_not_in_order_prompt(self):
        payloads = []
        def record(p):
            payloads.append(p)
            return {'action': 'noop', 'reason': '질문', 'operations': []}
        book = OrderBook(MENU, record, self.temp.name)
        book.consume(self.turn(1, 'speaker_0'))
        book.consume(self.turn(2, 'speaker_1'))
        self.assertEqual(payloads[-1]['recent'], [])

    def test_new_menu_requires_utterance_evidence(self):
        book = OrderBook(MENU, lambda p: self.decision([self.item('curry')]), self.temp.name)
        turn = self.turn(1)
        turn['text'] = '스테이크 주세요'
        self.assertEqual(book.consume(turn)['decision']['action'], 'clarify')

    def test_recognized_overlap_is_still_a_confirmation_candidate(self):
        book = OrderBook(MENU, lambda p: self.decision([self.item('curry')]), self.temp.name)
        event = book.consume(self.turn(1, overlap=True))
        self.assertTrue(event['requires_confirmation'])
        saved = json.loads(Path(self.temp.name, 'orders.json').read_text())
        self.assertEqual(saved['status'], 'needs_confirmation')
        self.assertEqual(saved['overlap_confirmation_count'], 1)

    def test_rule_parser_recovers_unique_typo_and_multiple_quantities(self):
        menu = {'store_id': 'restaurant', 'items': [
            {'id': 'maze', 'name': '마제소바', 'aliases': ['마제 소바']},
            {'id': 'katsu', 'name': '가츠동', 'aliases': ['카츠동', '가쓰동']},
        ]}
        book = OrderBook(menu, RuleBasedInterpreter(), self.temp.name)
        turn = self.turn(1, overlap=True)
        turn['text'] = '마제소보 한 개랑 가츠동 두 개 주세요'
        event = book.consume(turn)
        self.assertEqual(book.orders['speaker_0'], [
            {'menu_id': 'maze', 'quantity': 1, 'options': []},
            {'menu_id': 'katsu', 'quantity': 2, 'options': []},
        ])
        self.assertTrue(event['requires_confirmation'])
        self.assertTrue(event['decision']['needs_confirmation'])

    def test_rule_parser_does_not_invent_severely_corrupted_menu(self):
        menu = {'store_id': 'restaurant', 'items': [
            {'id': 'maze', 'name': '마제소바'}, {'id': 'katsu', 'name': '가츠동'}]}
        book = OrderBook(menu, RuleBasedInterpreter(), self.temp.name)
        turn = self.turn(1)
        turn['text'] = '마제소바 한 개랑 같은 돈 두 개예요'
        book.consume(turn)
        self.assertEqual(book.orders['speaker_0'], [
            {'menu_id': 'maze', 'quantity': 1, 'options': []}])

    def test_rule_parser_handles_exact_orders_and_ignores_questions(self):
        menu = {'store_id': 'burger', 'items': [
            {'id': 'shrimp', 'name': '슈슈버거 세트', 'aliases': ['슈슈 버거 세트']},
            {'id': 'bigmac', 'name': '빅맥 세트'},
        ]}
        book = OrderBook(menu, RuleBasedInterpreter(), self.temp.name)
        exact = self.turn(1)
        exact['text'] = '슈슈버거 세트 하나랑 빅맥 세트 두 개 주세요'
        book.consume(exact)
        self.assertEqual(book.orders['speaker_0'], [
            {'menu_id': 'shrimp', 'quantity': 1, 'options': []},
            {'menu_id': 'bigmac', 'quantity': 2, 'options': []},
        ])
        question = self.turn(2, speaker='speaker_1')
        question['text'] = '빅맥 세트 얼마예요?'
        event = book.consume(question)
        self.assertEqual(event['decision']['action'], 'noop')
        self.assertNotIn('speaker_1', book.orders)

    def test_hybrid_uses_rules_then_llm_for_implicit_correction(self):
        menu = {'store_id': 'burger', 'items': [
            {'id': 'bigmac', 'name': '빅맥 세트'},
            {'id': 'shrimp', 'name': '슈슈버거 세트'},
        ]}
        llm_payloads = []
        def llm(payload):
            llm_payloads.append(payload)
            return self.decision([
                {'op': 'remove', 'menu_id': 'bigmac'},
                self.item('shrimp'),
            ])
        hybrid = HybridInterpreter(lambda: llm)
        book = OrderBook(menu, hybrid, self.temp.name)
        first = self.turn(1)
        first['text'] = '빅맥 세트 하나랑요.'
        book.consume(first)
        self.assertEqual(book.orders['speaker_0'], [
            {'menu_id': 'bigmac', 'quantity': 1, 'options': []}])
        self.assertEqual(hybrid.rule_calls, 1)
        self.assertEqual(hybrid.llm_calls, 0)

        correction = self.turn(2)
        correction['text'] = '아니다 그냥 슈비버거 세트로 주세요.'
        event = book.consume(correction)
        self.assertEqual(book.orders['speaker_0'], [
            {'menu_id': 'shrimp', 'quantity': 1, 'options': []}])
        self.assertEqual(hybrid.llm_calls, 1)
        self.assertEqual(llm_payloads[0]['previous_items'][0]['menu_id'], 'bigmac')
        self.assertEqual(llm_payloads[0]['grounded_menu_mentions'][0]['menu_id'], 'shrimp')
        self.assertTrue(event['requires_confirmation'])  # fuzzy ASR/menu match

    def test_validator_infers_single_previous_item_replacement(self):
        menu = {'store_id': 'burger', 'items': [
            {'id': 'bigmac', 'name': '빅맥 세트'},
            {'id': 'shrimp', 'name': '슈슈버거 세트'},
        ]}
        responses = iter([self.decision([self.item('bigmac')]),
                          self.decision([self.item('shrimp')])])
        book = OrderBook(menu, lambda payload: next(responses), self.temp.name)
        first = self.turn(1)
        first['text'] = '빅맥 세트 하나 주세요'
        book.consume(first)
        correction = self.turn(2)
        correction['text'] = '아니다 그냥 슈슈버거 세트로 주세요'
        book.consume(correction)
        self.assertEqual(book.orders['speaker_0'], [
            {'menu_id': 'shrimp', 'quantity': 1, 'options': []}])

    def test_validator_discards_menu_abandoned_within_same_utterance(self):
        menu = {'store_id': 'burger', 'items': [
            {'id': 'bigmac', 'name': '빅맥 세트'},
            {'id': 'shrimp', 'name': '슈슈버거 세트'},
        ]}
        raw = self.decision([self.item('bigmac'), self.item('shrimp')])
        book = OrderBook(menu, lambda payload: raw, self.temp.name)
        turn = self.turn(1)
        turn['text'] = '빅맥 세트 하나요. 아니다 그냥 슈슈버거 세트로 주세요'
        event = book.consume(turn)
        self.assertEqual(book.orders['speaker_0'], [
            {'menu_id': 'shrimp', 'quantity': 1, 'options': []}])
        self.assertEqual([op['menu_id'] for op in event['raw_decision']['operations']],
                         ['bigmac', 'shrimp'])
        self.assertEqual([op['menu_id'] for op in event['decision']['operations']], ['shrimp'])

    def test_validator_rejects_ambiguous_implicit_replacement(self):
        menu = {'store_id': 'burger', 'items': [
            {'id': 'bigmac', 'name': '빅맥 세트'},
            {'id': 'shrimp', 'name': '슈슈버거 세트'},
            {'id': 'bulgogi', 'name': '불고기 버거 세트'},
        ]}
        responses = iter([self.decision([self.item('bigmac'), self.item('shrimp')]),
                          self.decision([self.item('bulgogi')])])
        book = OrderBook(menu, lambda payload: next(responses), self.temp.name)
        first = self.turn(1)
        first['text'] = '빅맥 세트 하나랑 슈슈버거 세트 하나 주세요'
        book.consume(first)
        before = json.loads(json.dumps(book.orders))
        correction = self.turn(2)
        correction['text'] = '아니다 그냥 불고기 버거 세트로 주세요'
        event = book.consume(correction)
        self.assertEqual(event['decision']['action'], 'clarify')
        self.assertEqual(book.orders, before)

    def test_validator_keeps_grounded_items_when_one_llm_item_is_unsupported(self):
        menu = {'store_id': 'restaurant', 'items': [
            {'id': 'maze', 'name': '마제소바'}, {'id': 'pork', 'name': '돈카츠'}]}
        decision = self.decision([self.item('maze'), self.item('pork', 2)])
        book = OrderBook(menu, lambda payload: decision, self.temp.name)
        turn = self.turn(1)
        turn['text'] = '마제소바 한 개랑 같은 돈 두 개예요'
        event = book.consume(turn)
        self.assertEqual(book.orders['speaker_0'], [
            {'menu_id': 'maze', 'quantity': 1, 'options': []}])
        self.assertTrue(event['requires_confirmation'])
        self.assertEqual(event['decision']['rejected_operations'][0]['operation']['menu_id'], 'pork')

    def test_add_and_remove_preserve_other_items(self):
        responses = iter([self.decision([self.item('curry'), self.item('cola')]),
            self.decision([dict(self.item('cola', 2), op='add')]),
            self.decision([{'op': 'remove', 'menu_id': 'cola'}])])
        book = OrderBook(MENU, lambda p: next(responses), self.temp.name)
        book.consume(self.turn(1))
        book.consume(self.turn(2))
        self.assertEqual(book.orders['speaker_0'][1]['quantity'], 3)
        book.consume(self.turn(3))
        self.assertEqual(book.orders['speaker_0'], [{'menu_id': 'curry', 'quantity': 1, 'options': []}])

    def test_source_permutation_uses_anchors(self):
        active = np.zeros((100, 2), dtype=bool)
        active[:70, 0] = True
        active[30:, 1] = True
        sources = np.repeat(active.T.astype(float), 80, axis=1)
        self.assertEqual(assign_sources(sources, active), [0, 1])
        self.assertEqual(assign_sources(sources[::-1], active), [1, 0])
        self.assertIsNone(assign_sources(sources, np.ones((100, 2), dtype=bool)))

    def test_conflicting_anchors_are_rejected(self):
        active = np.zeros((100, 2), dtype=bool)
        active[:40, 0] = True
        active[60:, 1] = True
        sources = np.stack([np.ones(8000), np.zeros(8000)])
        self.assertIsNone(assign_sources(sources, active))

    def test_runs_keep_boundaries(self):
        self.assertEqual(runs(np.array([1, 1, 0, 1, 1], bool), gap=1), [(0, 5)])
        self.assertEqual(runs(np.zeros(10, bool)), [])

    def test_splicing_preserves_nonoverlap_original(self):
        mix = np.random.default_rng(4).normal(0, .1, 16000).astype('float32')
        source = np.random.default_rng(5).normal(0, .1, 8000).astype('float32')
        active = np.ones((100, 2), dtype=bool)
        active[:30, 1] = False
        active[70:, 1] = False
        result = splice_overlap(mix, source, active, 0)
        np.testing.assert_array_equal(result[:4000], mix[:4000])
        np.testing.assert_array_equal(result[-4000:], mix[-4000:])

    def test_nemotron35_words_become_speaker_turns(self):
        response = {
            'choices': [{'finish_reason': 'stop', 'message': {'content':
                '<spk:0> 아메리카노 하나 <spk:1> 라떼 두 잔'}}],
            'ctc_timestamps': {
                'error': None,
                'words': [
                    {'word': '아메리카노', 'start': .2, 'end': .8, 'speaker': '0'},
                    {'word': '하나', 'start': .9, 'end': 1.2, 'speaker': '0'},
                    {'word': '라떼', 'start': .7, 'end': 1.1, 'speaker': '1'},
                    {'word': '두 잔', 'start': 1.2, 'end': 1.7, 'speaker': '1'},
                ],
                'diarization': [
                    {'speaker': 0, 'start': .1, 'end': 1.3},
                    {'speaker': 1, 'start': .6, 'end': 1.8},
                ],
                'speaker_tag_to_diarization_speaker': {'0': 0, '1': 1},
            },
        }
        turns, diarization = turns_from_response(response)
        self.assertEqual([turn['speaker'] for turn in turns], ['speaker_0', 'speaker_1'])
        self.assertEqual(turns[0]['text'], '아메리카노 하나')
        self.assertEqual(turns[1]['text'], '라떼 두 잔')
        self.assertTrue(all(turn['overlap'] for turn in turns))
        self.assertEqual(len(diarization), 2)

    def test_nemotron35_requires_successful_alignment(self):
        with self.assertRaises(RuntimeError):
            turns_from_response({'choices': [{'message': {'content': '말'}}],
                                 'ctc_timestamps': {'error': 'alignment_failed'}})

    def test_nemotron35_prompt_includes_menu_without_claiming_it_was_spoken(self):
        prompt = transcription_prompt(MENU, max_speakers=2)
        self.assertIn('<spk:0> <spk:1>', prompt)
        self.assertIn('카레, 콜라', prompt)
        self.assertIn('use only when spoken', prompt)

    def test_trip_rejects_wrong_branch_and_invalid_coordinates(self):
        t = {'session_id': 's', 'destination': {'store_id': 'wrong', 'name': '식당', 'latitude': 37, 'longitude': 127}}
        with self.assertRaises(ValueError):
            validate_trip(t, MENU)
        t['destination']['store_id'] = 'one'
        self.assertEqual(validate_trip(t, MENU)['status'], 'pending_android_adapter')
        t['destination']['latitude'] = float('nan')
        with self.assertRaises(ValueError):
            validate_trip(t, MENU)


if __name__ == '__main__':
    unittest.main()
