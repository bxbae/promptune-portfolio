import unittest

from app.services.retrieval.evidence_selector import (
    select_web_evidence,
)


class ProfileEvidenceGroundingTest(unittest.TestCase):

    def test_profile_rejects_other_people(self):
        results = [
            {
                "title": "홍명보 - 나무위키",
                "url": "https://example.com/hong",
                "content": "대한민국의 축구 감독 홍명보",
                "score": 1.0,
            },
            {
                "title": "김연경 - 나무위키",
                "url": "https://example.com/kim",
                "content": "배구 선수 김연경 경력",
                "score": 0.95,
            },
            {
                "title": "손흥민 - 프로필",
                "url": "https://example.com/son",
                "content": "손흥민의 축구 선수 경력과 소속 정보",
                "score": 0.40,
            },
        ]

        selected = select_web_evidence(
            results,
            query="손흥민 이력서 알려줘",
            intent="PROFILE",
            entity="손흥민",
            limit=3,
        )

        self.assertEqual(len(selected), 1)
        self.assertIn("손흥민", selected[0]["title"])


    def test_profile_returns_empty_when_entity_is_absent(self):
        results = [
            {
                "title": "홍명보",
                "url": "https://example.com/hong",
                "content": "홍명보의 축구 경력",
                "score": 1.0,
            },
            {
                "title": "정몽규",
                "url": "https://example.com/chung",
                "content": "정몽규의 경력",
                "score": 0.9,
            },
        ]

        selected = select_web_evidence(
            results,
            query="손흥민 이력서 알려줘",
            intent="PROFILE",
            entity="손흥민",
            limit=3,
        )

        self.assertEqual(selected, [])


    def test_general_query_does_not_hard_filter_entity(self):
        results = [
            {
                "title": "한국 축구 산업 보고서",
                "url": "https://example.com/report",
                "content": "대한민국 축구 산업 전반을 분석한다.",
                "score": 0.8,
            },
        ]

        selected = select_web_evidence(
            results,
            query="손흥민이 한국 축구 산업에 미친 영향",
            intent="GENERAL",
            entity="손흥민",
            limit=3,
        )

        self.assertEqual(len(selected), 1)


if __name__ == "__main__":
    unittest.main()
