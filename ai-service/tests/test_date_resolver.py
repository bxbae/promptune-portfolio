import unittest
from datetime import datetime, timedelta, timezone

from app.services.retrieval.date_resolver import resolve_relative_dates

KST = timezone(timedelta(hours=9))
FIXED_NOW = datetime(2026, 8, 26, 15, 0, tzinfo=KST)  # 수요일이라고 가정


class ResolveRelativeDatesTest(unittest.TestCase):

    def test_yesterday_is_resolved(self):
        result = resolve_relative_dates(
            "어제 잠실의 날씨를 안내해주고 lg 트윈스의 승리여부를 안내해줘.",
            now=FIXED_NOW,
        )
        self.assertIn("어제(2026-08-25)", result)
        # 원문 단어/문장은 보존돼야 함 (검색어에 자연어 맥락도 같이 남기기 위함)
        self.assertIn("lg 트윈스의 승리여부", result)

    def test_today_is_resolved(self):
        result = resolve_relative_dates("오늘 환율 알려줘", now=FIXED_NOW)
        self.assertIn("오늘(2026-08-26)", result)

    def test_tomorrow_is_resolved(self):
        result = resolve_relative_dates("내일 날씨 어때", now=FIXED_NOW)
        self.assertIn("내일(2026-08-27)", result)

    def test_no_relative_date_word_is_left_unchanged(self):
        query = "회의 내용 정리해줘"
        self.assertEqual(resolve_relative_dates(query, now=FIXED_NOW), query)

    def test_empty_query_is_left_unchanged(self):
        self.assertEqual(resolve_relative_dates("", now=FIXED_NOW), "")

    def test_multiple_relative_date_words_are_all_resolved(self):
        result = resolve_relative_dates(
            "어제랑 오늘 날씨 둘 다 알려줘", now=FIXED_NOW
        )
        self.assertIn("어제(2026-08-25)", result)
        self.assertIn("오늘(2026-08-26)", result)


if __name__ == "__main__":
    unittest.main()
