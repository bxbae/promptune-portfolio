import unittest

from app.schemas.models import ConversationMessage
from app.services.retrieval.conversation_context import resolve_conversation_retrieval


class ConversationContextPolicyTest(unittest.TestCase):

    def test_memory_set_does_not_search(self):
        q = "\ub0b4 \ud504\ub85c\uc81d\ud2b8\ub294 nested \ud50c\ub7ab\ud3fc\uc774\uc57c \uae30\uc5b5\ud574\ub46c"
        result = resolve_conversation_retrieval(query=q, history=[])
        self.assertEqual(result.route_override, "no_retrieval")
        self.assertFalse(result.used_history)

    def test_memory_recall_does_not_search(self):
        history = [
            ConversationMessage(
                role="user",
                content="\ub0b4 \ud504\ub85c\uc81d\ud2b8\ub294 nested \ud50c\ub7ab\ud3fc\uc774\uc57c \uae30\uc5b5\ud574\ub46c",
            ),
        ]
        q = "\ub0b4 \ud504\ub85c\uc81d\ud2b8 \uba85\uc774 \ubb50\ub77c\uace0?"
        result = resolve_conversation_retrieval(query=q, history=history)
        self.assertEqual(result.route_override, "no_retrieval")
        self.assertTrue(result.used_history)

    def test_standalone_does_not_use_history(self):
        history = [
            ConversationMessage(
                role="user",
                content="\ub0b4 \ud504\ub85c\uc81d\ud2b8\ub294 nested \ud50c\ub7ab\ud3fc\uc774\uc57c \uae30\uc5b5\ud574\ub46c",
            ),
            ConversationMessage(
                role="assistant",
                content="\uae30\uc5b5\ud588\uc2b5\ub2c8\ub2e4.",
            ),
        ]
        q = "\uce68\ucc29\ub9e8 \ub204\uad6c\uc57c?"
        result = resolve_conversation_retrieval(query=q, history=history)
        self.assertEqual(result.query, q)
        self.assertIsNone(result.route_override)
        self.assertFalse(result.used_history)


if __name__ == "__main__":
    unittest.main()
