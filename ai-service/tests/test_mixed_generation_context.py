import unittest

from app.schemas.models import (
    Document,
    GenerateRequest,
)
from app.services.generate_hcx import (
    _build_generation_user_prompt,
)


def _request():
    document = Document.model_construct(
        document_id=7,
        chunk_id=101,
        chunk_index=0,
        title="사내 연차 규정",
        document_type="POLICY",
        description="연차 운영 규정",
        content="사내 연차 규정의 실제 본문입니다.",
        score=0.9,
    )

    return GenerateRequest.model_construct(
        prompt="이 규정이 현재 노동법과 맞는지 비교해줘",
        task_type="research",
        documents=[document],
        web_results=[],
        user_context={},
        preference={},
        history=[],
    )


class MixedGenerationContextTest(unittest.TestCase):

    def test_document_and_web_are_both_present(self):
        text = _build_generation_user_prompt(
            _request(),
            web_results=[
                {
                    "title": "현행 노동법 자료",
                    "url": "https://example.com/law",
                    "content": "현재 법률의 실제 외부 근거입니다.",
                    "score": 0.91,
                }
            ],
        )

        self.assertIn(
            "사내 연차 규정의 실제 본문입니다.",
            text,
        )
        self.assertIn(
            "[외부 웹 근거 - 현재/공식 사실 비교용]",
            text,
        )
        self.assertIn(
            "현재 법률의 실제 외부 근거입니다.",
            text,
        )
        self.assertIn(
            "현재 문서의 내용과 외부 사실을 구분해서 비교한다.",
            text,
        )
        self.assertNotIn(
            "- 현재 문서만 답변 근거로 사용한다.",
            text,
        )

    def test_internal_only_keeps_document_only_rule(self):
        text = _build_generation_user_prompt(
            _request(),
            web_results=[],
        )

        self.assertIn(
            "- 현재 문서만 답변 근거로 사용한다.",
            text,
        )
        self.assertNotIn(
            "[외부 웹 근거 - 현재/공식 사실 비교용]",
            text,
        )


if __name__ == "__main__":
    unittest.main()
