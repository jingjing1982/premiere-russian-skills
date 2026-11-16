import unittest
from layout_titles import choose

class TitleTests(unittest.TestCase):
    def test_title_remains_whole_when_safe_two_rows_fit(self):
        s='Мы изучаем «Алмазная сутра» сегодня.';title='«Алмазная сутра»';a=s.index(title)
        rows,kind,exception=choose(s,25,len,[{'start':a,'end':a+len(title),'text':title,'kind':'scripture'}])
        self.assertTrue(rows);self.assertTrue(any(title in r for r in rows));self.assertEqual(' '.join(rows),s);self.assertFalse(exception)
    def test_scripture_exception_is_not_general_book_exception(self):
        s='«Сутра большого глубокого понимания природы сознания»';title={'start':0,'end':len(s),'text':s,'kind':'scripture'}
        rows,kind,exceptions=choose(s,32,len,[title]);self.assertEqual(kind,'long_scripture_wrap');self.assertEqual(len(rows),2);self.assertEqual(' '.join(rows),s)
        title['kind']='book';self.assertIsNone(choose(s,32,len,[title])[0])
    def test_short_text_stays_one_line_and_special_spaces_remain(self):
        s='Это\u00a0слово  здесь.';rows,_,_=choose(s,30,len,[]);self.assertEqual(rows,[s])
    def test_stale_title_text_rejected(self):
        with self.assertRaises(ValueError):choose('Привет мир',5,len,[{'start':0,'end':3,'text':'BAD','kind':'book'}])
    def test_no_three_line_fallback(self):
        self.assertIsNone(choose('ОдинОченьДлинныйТерминДругой ещё слова',8,len,[])[0])
    def test_no_equal_width_fallback_without_titles(self):
        rows,_,_=choose('аа аа аа аа',5,len,[]);self.assertIsNone(rows)
if __name__=='__main__':unittest.main()
