import unittest

from app.schemas.models import ConversationMessage
from app.services.retrieval.conversation_context import (
    resolve_conversation_retrieval,
)


class DeterministicFollowupQueryTest(unittest.TestCase):

    def test_company_followup_reuses_entity(self):
        history = [
            ConversationMessage(
                role="user",
                content="OpenAI가 뭐 하는 회사야?",
            ),
            ConversationMessage(
                role="assistant",
                content="이전 답변",
            ),
        ]

        result = resolve_conversation_retrieval(
            "그 회사 최신 뉴스 검색해줘",
            history,
        )

        self.assertEqual(
            result.query,
            "OpenAI 최신 뉴스 검색해줘",
        )
        self.assertTrue(result.used_history)

    def test_about_subject_followup_reuses_subject(self):
        history = [
            ConversationMessage(
                role="user",
                content="BTS에 대해 조사하고 있어",
            ),
            ConversationMessage(
                role="assistant",
                content="이전 답변",
            ),
        ]

        result = resolve_conversation_retrieval(
            "그 그룹 최근 뉴스 찾아봐",
            history,
        )

        self.assertEqual(
            result.query,
            "BTS 최근 뉴스 찾아봐",
        )
        self.assertTrue(result.used_history)

    def test_verification_keeps_previous_query(self):
        history = [
            ConversationMessage(
                role="user",
                content="침착맨이 누구야?",
            ),
            ConversationMessage(
                role="assistant",
                content="이전 답변",
            ),
        ]

        result = resolve_conversation_retrieval(
            "확실해?",
            history,
        )

        self.assertEqual(
            result.query,
            "침착맨이 누구야?",
        )
        self.assertTrue(result.used_history)

    def test_standalone_query_does_not_use_history(self):
        history = [
            ConversationMessage(
                role="user",
                content="OpenAI가 뭐 하는 회사야?",
            ),
            ConversationMessage(
                role="assistant",
                content="이전 답변",
            ),
        ]

        result = resolve_conversation_retrieval(
            "현재 환율 알려줘",
            history,
        )

        self.assertEqual(
            result.query,
            "현재 환율 알려줘",
        )
        self.assertFalse(result.used_history)


if __name__ == "__main__":
    unittest.main()
