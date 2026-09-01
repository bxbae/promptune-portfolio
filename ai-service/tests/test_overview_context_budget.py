import unittest

from app.schemas.models import (
    Document,
    GenerateRequest,
)
from app.services.generate_hcx import (
    _build_generation_user_prompt,
)


class OverviewContextBudgetTest(unittest.TestCase):

    def test_overview_does_not_duplicate_document(self):
        documents = [
            Document.model_construct(
                document_id=7,
                chunk_id=index + 1,
                chunk_index=index,
                title="테스트 보고서",
                document_type="REPORT",
                description="테스트",
                content=(
                    f"UNIQUE_CHUNK_{index} "
                    + ("내용 " * 300)
                ),
                score=0.9,
            )
            for index in range(4)
        ]

        req = GenerateRequest.model_construct(
            prompt="이 문서 전체 요약해줘",
            task_type="summary",
            documents=documents,
            web_results=[],
            user_context={},
            preference={},
            history=[],
        )

        result = _build_generation_user_prompt(
            req,
            web_results=[],
        )

        self.assertNotIn(
            "[대표 근거 - 문서 각 부분에서 그대로 발췌]",
            result,
        )

        for index in range(4):
            self.assertEqual(
                result.count(
                    f"UNIQUE_CHUNK_{index}"
                ),
                1,
            )

        self.assertLess(
            len(result),
            7000,
        )


if __name__ == "__main__":
    unittest.main()
