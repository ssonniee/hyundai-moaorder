"""Bounded-context order interpretation and deterministic state validation."""
import copy
import json
import math
import re
from pathlib import Path


def dump(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def validate_menu(menu):
    if not isinstance(menu.get('store_id'), str) or not menu['store_id']:
        raise ValueError('menu.store_id is required')
    ids = set()
    for item in menu['items']:
        if not isinstance(item['id'], str) or item['id'] in ids:
            raise ValueError('menu IDs must be unique strings')
        if not isinstance(item['name'], str) or not item['name'].strip():
            raise ValueError('menu name is required')
        ids.add(item['id'])
    if not ids:
        raise ValueError('menu must contain items')


class InvalidLLMOutput(ValueError):
    def __init__(self, raw, cause):
        super().__init__(str(cause))
        self.raw = raw


class OrderBook:
    def __init__(self, menu, interpreter, output):
        validate_menu(menu)
        self.menu, self.interpreter = menu, interpreter
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.orders, self.recent, self.seen = {}, [], set()
        self.review_count = 0
        self.overlap_confirmation_count = 0
        self.last_start = -1

    def _apply(self, decision, before, text):
        if not isinstance(decision, dict) or decision.get('action') not in {'update', 'noop', 'clarify'}:
            raise ValueError('Invalid LLM action')
        if not isinstance(decision.get('reason'), str):
            raise ValueError('Missing reason')
        if decision['action'] != 'update':
            return before
        operations = decision.get('operations')
        if not isinstance(operations, list) or not operations or len(operations) > 50:
            raise ValueError('Invalid operations')
        menu = {m['id']: m for m in self.menu['items']}
        result = copy.deepcopy(before)
        normalized = re.sub(r'\s+', '', text)
        reference = any(v in normalized for v in ('그거', '그걸', '같은걸', '아까거', '아까것'))
        for item in operations:
            op = item.get('op')
            if op == 'clear':
                result = []
                continue
            if item.get('menu_id') not in menu:
                raise ValueError('Unknown menu ID')
            id = item['menu_id']
            existing = [i for i in result if i['menu_id'] == id]
            entry = menu[id]
            mentioned = any(re.sub(r'\s+', '', s) in normalized for s in [entry['name']] + entry.get('aliases', []))
            if not mentioned and not (reference and existing):
                raise ValueError('Menu has no evidence in current utterance')
            if op == 'remove':
                if not existing:
                    raise ValueError('Cannot cancel a menu absent from current order')
                result = [i for i in result if i['menu_id'] != id]
                continue
            if op not in {'set', 'add'}:
                raise ValueError('Invalid operation')
            if type(item.get('quantity')) is not int or not 1 <= item['quantity'] <= 99:
                raise ValueError('Invalid quantity')
            opts = item.get('options')
            if not isinstance(opts, list) or len(opts) > 20 or any(not isinstance(v, str) or len(v) > 100 for v in opts):
                raise ValueError('Invalid options')
            if op == 'set':
                result = [i for i in result if i['menu_id'] != id]
            matching = next((i for i in result if i['menu_id'] == id and sorted(i['options']) == sorted(opts)), None)
            if matching:
                matching['quantity'] += item['quantity']
                if matching['quantity'] > 99:
                    raise ValueError('Quantity exceeds limit')
            else:
                result.append({k: copy.deepcopy(item[k]) for k in ('menu_id', 'quantity', 'options')})
        return result

    def consume(self, turn):
        if turn['id'] in self.seen:
            return None
        start, end = turn['start'], turn['end']
        if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in (start, end)) or start < 0 or end <= start:
            raise ValueError('Invalid timestamps')
        if start < self.last_start:
            raise ValueError('Turns must be chronological')
        self.last_start = start
        speaker = turn.get('speaker')
        before = copy.deepcopy(self.orders.get(speaker, []))
        after = before
        raw = None
        try:
            if not speaker or turn.get('needs_review', False):
                decision = {'action': 'clarify', 'operations': [], 'reason': '음성/화자 대응 확인 필요'}
            elif not turn['text'].strip():
                decision = {'action': 'noop', 'operations': [], 'reason': '인식된 발화 없음'}
            else:
                own_recent = [r for r in self.recent if r['speaker'] == speaker][-8:]
                payload = {'menu': self.menu, 'previous_items': before,
                    'recent': own_recent, 'current': {k: turn[k] for k in ('id', 'speaker', 'text', 'start', 'end')}}
                if getattr(self.interpreter, 'contextual', False):
                    payload.update(conversation_recent=copy.deepcopy(self.recent), all_orders=copy.deepcopy(self.orders))
                raw = self.interpreter(payload)
                decision = copy.deepcopy(raw)
                after = self._apply(decision, before, turn['text'])
        except (ValueError, TypeError, KeyError) as exc:
            if isinstance(exc, InvalidLLMOutput):
                raw = exc.raw
            decision = {'action': 'clarify', 'operations': [], 'reason': 'Order output rejected: ' + str(exc)}
        if decision['action'] == 'update':
            self.orders[speaker] = copy.deepcopy(after)
        if decision['action'] == 'clarify' or decision.get('needs_confirmation', False):
            self.review_count += 1
        if turn.get('overlap', False):
            self.overlap_confirmation_count += 1
        event = {'utterance_id': turn['id'], 'speaker': speaker, 'start': start, 'end': end,
                 'text': turn['text'], 'before': before, 'decision': decision, 'raw_decision': raw,
                 'requires_confirmation': (turn.get('overlap', False) or decision['action'] == 'clarify'
                                           or decision.get('needs_confirmation', False)),
                 'after': copy.deepcopy(self.orders.get(speaker, []))}
        with (self.output / 'order_events.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')
        self.seen.add(turn['id'])
        # Uncertain transcripts are retained on disk but cannot contaminate later LLM context.
        if speaker and not turn.get('needs_review', False):
            limit = 64 if getattr(self.interpreter, 'contextual', False) else 8
            self.recent = (self.recent + [{k: turn[k] for k in ('id', 'speaker', 'text', 'start', 'end')}])[-limit:]
        self.save()
        return event

    def save(self):
        # Silence is a valid recording: expose an empty event stream as well.
        (self.output / 'order_events.jsonl').touch(exist_ok=True)
        names = {m['id']: m['name'] for m in self.menu['items']}
        dump(self.output / 'orders.json', {'store_id': self.menu['store_id'],
            'status': 'needs_confirmation' if self.review_count or self.overlap_confirmation_count else 'draft',
            'review_count': self.review_count,
            'overlap_confirmation_count': self.overlap_confirmation_count,
            'speakers': {s: [dict(i, name=names[i['menu_id']]) for i in items]
                         for s, items in self.orders.items()}})
