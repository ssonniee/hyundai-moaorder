import json
import tempfile
import unittest
from pathlib import Path
from drive_order.context_orders import ContextOrderBook, parse_decision
from drive_order.orders import InvalidLLMOutput

class ContextTests(unittest.TestCase):
    def test_cross_speaker_context_and_original_evidence(self):
        payloads=[]
        class Interpreter:
            contextual=True
            def __call__(self,payload):
                payloads.append(payload)
                return {'action':'update','reason':'명시 주문 및 참조','operations':[{'op':'set','menu_id':'coffee','quantity':1,'options':[]}],'needs_confirmation':False,'evidence_turn_ids':[payload['current']['id']]}
        menu={'store_id':'test','items':[{'id':'coffee','name':'아이스 아메리카노'}]}
        with tempfile.TemporaryDirectory() as tmp:
            book=ContextOrderBook(menu,Interpreter(),tmp)
            for i,(speaker,text) in enumerate([('A','아아 하나 주세요'),('B','저도 같은 걸로요')]):
                book.consume({'id':str(i),'speaker':speaker,'text':text,'start':i*2,'end':i*2+1})
            self.assertIn('A',payloads[1]['all_orders'])
            self.assertEqual(payloads[1]['conversation_recent'][0]['text'],'아아 하나 주세요')
            self.assertEqual(book.orders['A'],book.orders['B'])
            record=json.loads((Path(tmp)/'menu_postprocessing.jsonl').read_text().splitlines()[0])
            self.assertEqual(record['original_text'],'아아 하나 주세요')
            self.assertEqual(record['menu_hints'][0]['menu_ids'],['coffee'])
    def test_updates_require_current_evidence(self):
        with self.assertRaises(InvalidLLMOutput):
            parse_decision(json.dumps({'action':'update','evidence_turn_ids':['old']}),{'current':{'id':'new'},'conversation_recent':[{'id':'old'}]})
