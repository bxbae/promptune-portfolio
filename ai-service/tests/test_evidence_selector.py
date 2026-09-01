import unittest

from app.services.retrieval.evidence_selector import (
    select_web_evidence,
)


class EvidenceSelectorTest(unittest.TestCase):

    def test_entity_match_beats_mismatch(self):
        results = [
            {
                "title": "다른 아이돌 해외 활동",
                "url": "https://news.example/a",
                "content": "다른 그룹의 활동",
                "score": 0.90,
            },
            {
                "title": "BTS 경제적 영향",
                "url": "https://news.example/b",
                "content": "BTS의 국가 경제 기여",
                "score": 0.82,
            },
        ]

        selected = select_web_evidence(
            results,
            query="BTS가 국가에 기여한 점",
            intent="RESEARCH",
            entity="BTS",
            limit=1,
        )

        self.assertEqual(
            selected[0]["title"],
            "BTS 경제적 영향",
        )

    def test_research_authority_bonus(self):
        results = [
            {
                "title": "BTS 경제 효과 블로그",
                "url": "https://blog.example/a",
                "content": "BTS 경제 효과",
                "score": 0.85,
            },
            {
                "title": "BTS 문화경제 연구",
                "url": "https://example.go.kr/report",
                "content": "BTS 문화 경제 기여 연구",
                "score": 0.75,
            },
        ]

        selected = select_web_evidence(
            results,
            query="BTS 국가 기여",
            intent="RESEARCH",
            entity="BTS",
            limit=1,
        )

        self.assertIn(
            "go.kr",
            selected[0]["url"],
        )

    def test_duplicate_removed(self):
        results = [
            {
                "title": "같은 기사",
                "url": "https://example.com/a",
                "content": "첫 결과",
                "score": 0.9,
            },
            {
                "title": "같은 기사",
                "url": "https://example.com/b",
                "content": "중복 결과",
                "score": 0.8,
            },
        ]

        selected = select_web_evidence(
            results,
            query="테스트",
            intent="GENERAL",
            entity=None,
            limit=3,
        )

        self.assertEqual(
            len(selected),
            1,
        )

    def test_limit(self):
        results = [
            {
                "title": f"result-{i}",
                "url": f"https://example.com/{i}",
                "content": "내용",
                "score": 1 - i * 0.1,
            }
            for i in range(5)
        ]

        selected = select_web_evidence(
            results,
            query="테스트",
            intent="GENERAL",
            entity=None,
            limit=3,
        )

        self.assertEqual(
            len(selected),
            3,
        )


if __name__ == "__main__":
    unittest.main()
