import unittest

from app.services.retrieval.search_plan import build_search_plan


CASES = [
    ("침착맨이 누구야?", "PROFILE", "침착맨", "NONE"),
    ("OpenAI가 뭐 하는 회사야?", "PROFILE", "OpenAI", "NONE"),
    ("BTS가 국가에 기여한 점 알려줘", "RESEARCH", "BTS", "NONE"),
    ("BTS 최근 뉴스 알려줘", "NEWS", "BTS", "WEEK"),
    ("현재 커피 시세 알려줘", "FINANCE", "커피", "DAY"),
    ("오늘 원달러 환율 알려줘", "FINANCE", "원달러", "DAY"),
    ("오늘 서울 날씨 알려줘", "CURRENT_FACT", "서울", "DAY"),
    ("어제 LG 트윈스 경기 결과 알려줘", "CURRENT_FACT", "LG 트윈스", "NONE"),
    ("양자컴퓨팅 원리를 설명해줘", "GENERAL", None, "NONE"),
]


class SearchPlanTest(unittest.TestCase):

    def test_cases(self):
        for query, intent, entity, freshness in CASES:
            with self.subTest(query=query):
                plan = build_search_plan(query)

                self.assertEqual(plan.intent, intent)
                self.assertEqual(plan.entity, entity)
                self.assertEqual(plan.freshness, freshness)


if __name__ == "__main__":
    unittest.main()
