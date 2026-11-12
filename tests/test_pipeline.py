import json
from pathlib import Path
import tempfile
import unittest
import numpy as np

from drive_order.audio import assign_sources, runs, splice_overlap, prepare_clips
from drive_order.orders import OrderBook, validate_menu
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
        book.consume(self.turn(4))
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
