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
    # 2026-09-02: CONTEXT 추천문구가 덧붙어 다문장이 되면 entity 정규식 추출이
    # 실패하지만("^...$" 앵커 때문에), 질의에 "선수" 같은 인물 마커가 있으면
    # entity=None이어도 intent는 여전히 PROFILE로 분류돼야 한다 - 그래야
    # tavily_search.py가 위키백과/나무위키/올림픽/그래미 도메인으로 검색한다.
    (
        "이강인 선수에대해 알려줘. 이강인 선수는 뛰어난 드리블 능력과 패스 "
        "능력으로 주목받고 있는 젊은 축구 선수입니다. 소속 클럽과 약력을 "
        "안내해줘.",
        "PROFILE",
        None,
        "NONE",
    ),
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
