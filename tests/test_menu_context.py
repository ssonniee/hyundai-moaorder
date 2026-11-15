import unittest
from drive_order.menu_context import prepare_menu, menu_hints

class MenuContextTests(unittest.TestCase):
    def menu(self, *names):
        return {'store_id':'test','items':[{'id':str(i),'name':n} for i,n in enumerate(names)]}
    def test_store_scoped_aliases(self):
        menu=self.menu('아이스 아메리카노','아이스티 샷 추가','감자튀김')
        for text,mid in [('아아 두 잔 주세요','0'),('아샷추 하나 주세요','1'),('감튀 주세요','2')]:
            self.assertEqual(menu_hints(text,menu)[0]['menu_ids'],[mid])
        self.assertNotIn('aliases',menu['items'][0])
    def test_unavailable_products_not_created(self):
        self.assertEqual(menu_hints('아아 아샷추 감튀',self.menu('뜨거운 아메리카노','아이스티','감자튀김 세트')),[])
    def test_typo_candidates(self):
        h=menu_hints('아이스아메리카노오 두 잔 취소요',self.menu('아이스아메리카노'))
        self.assertEqual(h[0]['kind'],'possible_asr_typo')
        self.assertEqual(h[0]['menu_ids'],['0'])
    def test_ambiguous_alias(self):
        menu=self.menu('아이스아메리카노','디카페인아메리카노')
        for item in menu['items']:item['aliases']=['아아']
        self.assertTrue(menu_hints('아아 주세요',menu)[0]['ambiguous'])
    def test_no_substring_alias(self):
        self.assertEqual(menu_hints('아아아아',self.menu('아이스아메리카노')),[])
