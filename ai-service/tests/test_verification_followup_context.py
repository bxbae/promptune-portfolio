import unittest

from app.schemas.models import ConversationMessage
from app.services.conversation_memory import (
    classify_conversation_context,
)
from app.services.retrieval.conversation_context import (
    resolve_conversation_retrieval,
)


class VerificationFollowupContextTest(unittest.TestCase):

    def test_verification_is_immediate_followup(self):
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

        self.assertEqual(
            classify_conversation_context(
                "확실해?",
                history,
            ),
            "immediate_followup",
        )

    def test_verification_reuses_previous_user_query(self):
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
        self.assertIsNone(
            result.route_override
        )
        self.assertTrue(
            result.used_history
        )

    def test_repeated_verification_skips_old_verification_message(self):
        history = [
            ConversationMessage(
                role="user",
                content="OpenAI가 뭐 하는 회사야?",
            ),
            ConversationMessage(
                role="assistant",
                content="첫 답변",
            ),
            ConversationMessage(
                role="user",
                content="확실해?",
            ),
            ConversationMessage(
                role="assistant",
                content="재확인 답변",
            ),
        ]

        result = resolve_conversation_retrieval(
            "진짜야?",
            history,
        )

        self.assertEqual(
            result.query,
            "OpenAI가 뭐 하는 회사야?",
        )


if __name__ == "__main__":
    unittest.main()
