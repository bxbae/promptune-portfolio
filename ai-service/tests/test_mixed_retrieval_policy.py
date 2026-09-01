import unittest

from app.services.retrieval.retrieval_orchestrator import (
    _should_auto_use_web_with_internal,
)


class MixedRetrievalPolicyTest(unittest.TestCase):

    def check(self, query, expected):
        actual = _should_auto_use_web_with_internal(
            query,
            [7],
        )
        self.assertEqual(actual, expected)

    def test_plain_document_question(self):
        self.check(
            "이 문서에서 프로젝트 내용을 알려줘",
            False,
        )

    def test_document_overview(self):
        self.check(
            "이 문서 요약해줘",
            False,
        )

    def test_current_market_comparison(self):
        self.check(
            "이 보고서의 시장 규모가 현재도 맞는지 확인해줘",
            True,
        )

    def test_current_law_comparison(self):
        self.check(
            "이 규정이 현행 노동법과 맞는지 검토해줘",
            True,
        )

    def test_current_price_comparison(self):
        self.check(
            "첨부 가격이 현재 시세와 맞는지 확인해줘",
            True,
        )

    def test_no_document_never_auto_web(self):
        actual = _should_auto_use_web_with_internal(
            "현재 시세와 맞는지 확인해줘",
            [],
        )
        self.assertFalse(actual)


if __name__ == "__main__":
    unittest.main()
