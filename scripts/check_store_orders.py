"""Test user-provided store menus with real Qwen inference on synthetic text."""
import json
from pathlib import Path
import tempfile

from drive_order.orders import LocalLLM, OrderBook

ROOT = Path(__file__).resolve().parents[1]
stores = json.loads((ROOT/'demo/stores.json').read_text())
llm = LocalLLM(ROOT/'models/Qwen3-4B-Instruct-2507')
cases = [
    (['토피넛라떼 한 잔 주세요.', '저는 딸기 라떼 한 잔 주세요.',
      '토피넛라떼 말고 차이티 라떼 한 잔으로 바꿀게요.'], 'menu_005', 'menu_006'),
    (['빅맥 세트 한 개 주세요.', '저는 슈슈 세트 한 개 주세요.',
      '빅맥 세트 말고 상하이 세트 한 개로 바꿀게요.'], 'menu_001', 'menu_004'),
    (['마제소바 하나 주세요.', '저는 어묵우동 하나 주세요.',
      '마제소바 말고 치즈카츠 하나로 바꿀게요.'], 'menu_001', 'menu_003')
]
for store, (texts, first, second) in zip(stores, cases):
    menu = {'store_id': store['id'], 'items': [dict(m, id=f'menu_{i:03d}') for i,m in enumerate(store['items'])]}
    with tempfile.TemporaryDirectory() as output:
        book = OrderBook(menu, llm, output)
        for i, (speaker, text) in enumerate(zip(['speaker_0', 'speaker_1', 'speaker_0'], texts)):
            event = book.consume({'id': str(i), 'speaker': speaker, 'start': i*2., 'end': i*2.+1., 'text': text})
            print(store['name'], text, event['decision'], flush=True)
        assert [i['menu_id'] for i in book.orders['speaker_0']] == [first], book.orders
        assert [i['menu_id'] for i in book.orders['speaker_1']] == [second], book.orders
        assert book.review_count == 0
        print('PASS:', store['name'], 'speaker isolation, aliases and menu replacement', flush=True)
