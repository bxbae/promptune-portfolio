import unittest

from app.services.action.action_resolver import resolve_action


class ActionResolverTest(unittest.TestCase):

    def test_chat_without_retrieval(self):
        plan = resolve_action("안녕하세요 오늘도 잘 부탁해")
        self.assertEqual(plan.action.value, "CHAT")
        self.assertEqual(plan.retrieval_route, "no_retrieval")
        self.assertFalse(plan.retrieval_required)

    def test_memory_write(self):
        plan = resolve_action("앞으로 나를 사장님이라고 불러줘")
        self.assertEqual(plan.action.value, "MEMORY_WRITE")
        self.assertEqual(plan.retrieval_route, "no_retrieval")

    def test_memory_read(self):
        plan = resolve_action("내 프로젝트 이름 뭐라고 했지?")
        self.assertEqual(plan.action.value, "MEMORY_READ")
        self.assertEqual(plan.retrieval_route, "no_retrieval")

    def test_web_fact(self):
        plan = resolve_action("리센느라는 그룹에 대해 알려줘")
        self.assertEqual(plan.action.value, "WEB_FACT")
        self.assertEqual(
            plan.retrieval_route,
            "external_or_realtime",
        )

    def test_realtime_fact(self):
        plan = resolve_action("오늘 원달러 환율 얼마야?")
        self.assertEqual(plan.action.value, "WEB_FACT")

    def test_internal_document(self):
        plan = resolve_action("첨부한 계약서 핵심 내용 알려줘")
        self.assertEqual(plan.action.value, "INTERNAL_DOC")

    def test_transform(self):
        plan = resolve_action("이 문장을 좀 더 자연스럽게 수정해줘")
        self.assertEqual(plan.action.value, "TEXT_TRANSFORM")
        self.assertEqual(plan.retrieval_route, "no_retrieval")

    def test_greeting_word_is_not_always_chat(self):
        plan = resolve_action("안녕이라는 표현의 유래를 조사해줘")
        self.assertEqual(plan.action.value, "WEB_FACT")


if __name__ == "__main__":
    unittest.main()


class StrongRetrievalSignalTest(unittest.TestCase):

    def test_realtime_weather_is_strong_web_signal(self):
        from app.services.retrieval.ml_router import (
            resolve_strong_retrieval_route,
        )

        self.assertEqual(
            resolve_strong_retrieval_route("오늘 날씨 어때?"),
            "external_or_realtime",
        )

    def test_third_party_profile_is_strong_web_signal(self):
        from app.services.retrieval.ml_router import (
            resolve_strong_retrieval_route,
        )

        self.assertEqual(
            resolve_strong_retrieval_route(
                "lg 트윈스 단장님의 이름과 약력을 안내해줘"
            ),
            "external_or_realtime",
        )

    def test_greeting_has_no_strong_retrieval_signal(self):
        from app.services.retrieval.ml_router import (
            resolve_strong_retrieval_route,
        )

        self.assertIsNone(
            resolve_strong_retrieval_route("안녕")
        )


class ExecutionContextActionResolverTest(unittest.TestCase):

    def test_current_user_name_is_normalized_to_self_context(self):
        plan = resolve_action(
            "차승연 이력서 알려줘",
            {
                "name": "차승연",
                "displayName": "차승연",
            },
        )

        self.assertEqual(
            plan.routing_query,
            "내 이력서 알려줘",
        )
        self.assertEqual(
            plan.action.value,
            "USER_CONTEXT",
        )
        self.assertEqual(
            plan.retrieval_route,
            "user_context",
        )

    def test_current_user_possessive_name_is_self_context(self):
        plan = resolve_action(
            "차승연의 경력 정리해줘",
            {"name": "차승연"},
        )

        self.assertEqual(
            plan.routing_query,
            "내 경력 정리해줘",
        )
        self.assertEqual(
            plan.action.value,
            "USER_CONTEXT",
        )

    def test_other_person_is_not_normalized_to_self(self):
        plan = resolve_action(
            "손흥민 이력서 알려줘",
            {"name": "차승연"},
        )

        self.assertEqual(
            plan.routing_query,
            "손흥민 이력서 알려줘",
        )
        self.assertEqual(
            plan.action.value,
            "WEB_FACT",
        )

    def test_current_user_web_news_remains_web(self):
        plan = resolve_action(
            "차승연 최근 뉴스 찾아줘",
            {"name": "차승연"},
        )

        self.assertNotEqual(
            plan.action.value,
            "USER_CONTEXT",
        )
