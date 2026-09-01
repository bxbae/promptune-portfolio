import unittest

from app.schemas.models import ConversationMessage
from app.services.context_budget import (
    budget_history,
    truncate_context_text,
)


class ContextBudgetTest(unittest.TestCase):

    def test_short_text_unchanged(self):
        self.assertEqual(
            truncate_context_text(
                "짧은 내용",
                100,
            ),
            "짧은 내용",
        )

    def test_long_text_is_bounded(self):
        result = truncate_context_text(
            "A" * 3000,
            1000,
        )

        self.assertLessEqual(
            len(result),
            1000,
        )
        self.assertIn(
            "중간 생략",
            result,
        )

    def test_history_total_is_bounded(self):
        history = [
            ConversationMessage(
                role="user",
                content="A" * 2000,
            ),
            ConversationMessage(
                role="assistant",
                content="B" * 2000,
            ),
            ConversationMessage(
                role="user",
                content="C" * 2000,
            ),
            ConversationMessage(
                role="assistant",
                content="D" * 2000,
            ),
        ]

        selected = budget_history(
            history
        )

        total = sum(
            len(message.content)
            for message in selected
        )

        self.assertLessEqual(
            total,
            3000,
        )

        self.assertEqual(
            selected[-1].role,
            "assistant",
        )


if __name__ == "__main__":
    unittest.main()
