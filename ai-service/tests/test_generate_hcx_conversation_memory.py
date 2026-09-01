import unittest

from app.schemas.models import ConversationMessage, GenerateRequest
from app.services.generate_hcx import (
    _build_recent_user_evidence,
    _build_generation_user_prompt,
)


class ConversationMemoryTest(unittest.TestCase):

    def build_request(self):
        return GenerateRequest(
            prompt="내 프로젝트 명이 뭐라고?",
            task_type="support",
            documents=[],
            web_results=[],
            user_context={},
            preference={},
            history=[
                ConversationMessage(
                    role="user",
                    content="내 이름은 차승연이고 프로젝트는 nested 플랫폼이야 기억해둬",
                ),
                ConversationMessage(
                    role="assistant",
                    content="내 프로젝트 이름은 My Projects입니다.",
                ),
            ],
        )

    def test_recent_user_fact_is_preserved(self):
        req = self.build_request()

        evidence = _build_recent_user_evidence(req)

        self.assertIn("nested 플랫폼", evidence)
        self.assertNotIn("My Projects", evidence)

    def test_recent_user_fact_is_anchored_in_final_prompt(self):
        req = self.build_request()

        prompt = _build_generation_user_prompt(req)

        self.assertIn("nested 플랫폼", prompt)
        self.assertIn("내 프로젝트 명이 뭐라고?", prompt)
        self.assertNotIn("My Projects", prompt)


if __name__ == "__main__":
    unittest.main()
