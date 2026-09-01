import unittest
from unittest.mock import patch

from app.schemas.models import SuggestRequest
from app.services.suggest_hcx import (
    _normalize_target_elements,
    _parse_generated_candidates,
    suggest,
)


ELEMENTS = [
    "TASK",
    "AUDIENCE",
    "CONTEXT",
    "FORMAT",
    "TONE",
    "LENGTH",
    "CONSTRAINT",
    "EXAMPLE",
]


def _predict_missing_with_valid_candidates(original_text: str):
    def fake_predict_missing(text: str) -> dict[str, int]:
        if text == original_text:
            return {
                element: 1
                for element in ELEMENTS
            }

        return {
            element: 0
            for element in ELEMENTS
        }

    return fake_predict_missing


class DynamicHcxSuggestionTest(unittest.TestCase):

    def test_target_elements_are_normalized_and_deduplicated(self):
        result = _normalize_target_elements(
            ["format", "FORMAT", "tone"]
        )

        self.assertEqual(
            result,
            ["FORMAT", "TONE"],
        )

    def test_parse_generated_candidates_from_json(self):
        raw = """
        {
          "candidates": [
            "내부 공유를 위한 자료로 사용할 예정이야.",
            "후속 업무를 진행할 때 참고할 자료로 사용할 예정이야.",
            "회의 결과를 팀에서 공유하기 위한 자료로 사용할 예정이야."
          ]
        }
        """

        result = _parse_generated_candidates(raw)

        self.assertEqual(len(result), 3)
        self.assertEqual(
            result[0],
            "내부 공유를 위한 자료로 사용할 예정이야.",
        )

    def test_parse_generated_candidates_removes_duplicates(self):
        raw = """
        {
          "candidates": [
            "표 형식으로 정리해줘.",
            "표 형식으로 정리해줘.",
            "불릿 목록으로 정리해줘."
          ]
        }
        """

        result = _parse_generated_candidates(raw)

        self.assertEqual(
            result,
            [
                "표 형식으로 정리해줘.",
                "불릿 목록으로 정리해줘.",
            ],
        )

    @patch(
        "app.services.suggest_hcx._generate_candidates",
        return_value=[
            "표 형식으로 정리해줘.",
            "불릿 목록으로 정리해줘.",
            "마크다운 형식으로 정리해줘.",
            "체크리스트 형식으로 정리해줘.",
            "번호 목록으로 정리해줘.",
        ],
    )
    def test_suggest_builds_primary_and_alternatives_from_generated_candidates(
        self,
        mock_generate,
    ):
        req = SuggestRequest(
            text="회의 결과 정리해줘",
            target_elements=["FORMAT"],
            context="팀원들이 결정사항을 빠르게 확인해야 한다.",
        )

        with patch(
            "app.services.suggest_hcx.predict_missing_with_rules",
            side_effect=_predict_missing_with_valid_candidates(
                req.text
            ),
        ):
            result = suggest(req)

        self.assertEqual(
            len(result.suggestions),
            1,
        )

        suggestion = result.suggestions[0]

        self.assertEqual(
            suggestion.element,
            "FORMAT",
        )

        self.assertEqual(
            suggestion.primary,
            "표 형식으로 정리해줘.",
        )

        self.assertEqual(
            suggestion.alternatives,
            [
                "불릿 목록으로 정리해줘.",
                "마크다운 형식으로 정리해줘.",
            ],
        )

        mock_generate.assert_called_once_with(
            text=req.text,
            context=req.context,
            element="FORMAT",
        )

    @patch(
        "app.services.suggest_hcx._generate_candidates",
    )
    def test_suggest_generates_for_each_target_element(
        self,
        mock_generate,
    ):
        def generate_candidates(**kwargs):
            if kwargs["element"] == "AUDIENCE":
                return [
                    "팀장님께 전달하는 메일로 작성해줘.",
                    "프로젝트 담당자에게 전달하는 메일로 작성해줘.",
                    "수신자를 관련 부서 담당자로 설정해줘.",
                ]

            return [
                "첫 번째 후보.",
                "두 번째 후보.",
                "세 번째 후보.",
            ]

        mock_generate.side_effect = generate_candidates

        req = SuggestRequest(
            text="경쟁사 정보를 정리해줘",
            target_elements=[
                "TASK",
                "AUDIENCE",
                "FORMAT",
            ],
            context=None,
        )

        with patch(
            "app.services.suggest_hcx.predict_missing_with_rules",
            side_effect=_predict_missing_with_valid_candidates(
                req.text
            ),
        ):
            result = suggest(req)

        self.assertEqual(
            len(result.suggestions),
            3,
        )

        self.assertEqual(
            [
                item.element
                for item in result.suggestions
            ],
            [
                "TASK",
                "AUDIENCE",
                "FORMAT",
            ],
        )

        self.assertEqual(
            mock_generate.call_count,
            3,
        )

    @patch(
        "app.services.suggest_hcx._generate_candidates",
        side_effect=RuntimeError("HCX generation failed"),
    )
    def test_suggest_does_not_use_fixed_fallback_when_generation_fails(
        self,
        mock_generate,
    ):
        req = SuggestRequest(
            text="회의 내용을 정리해줘",
            target_elements=["FORMAT"],
            context=None,
        )

        with patch(
            "app.services.suggest_hcx.predict_missing_with_rules",
            return_value={
                **{
                    element: 0
                    for element in ELEMENTS
                },
                "FORMAT": 1,
            },
        ):
            result = suggest(req)

        self.assertEqual(
            result.suggestions,
            [],
        )

        mock_generate.assert_called_once()

    @patch(
        "app.services.suggest_hcx._generate_candidates",
    )
    def test_suggest_skips_context_generation_without_explicit_context(
        self,
        mock_generate,
    ):
        req = SuggestRequest(
            text="임원에게 보고할 회의 내용을 정리해줘",
            target_elements=["CONTEXT"],
            context=None,
        )

        with patch(
            "app.services.suggest_hcx.predict_missing_with_rules",
            return_value={
                **{
                    element: 0
                    for element in ELEMENTS
                },
                "CONTEXT": 1,
            },
        ):
            result = suggest(req)

        self.assertEqual(
            result.suggestions,
            [],
        )
        mock_generate.assert_not_called()

    def test_parse_generated_candidates_supports_five_candidates(self):
        raw = """
        {
        "candidates": [
            "첫 번째 후보.",
            "두 번째 후보.",
            "세 번째 후보.",
            "네 번째 후보.",
            "다섯 번째 후보."
        ]
        }
        """

        result = _parse_generated_candidates(raw)

        self.assertEqual(len(result), 5)
        self.assertEqual(
            result,
            [
                "첫 번째 후보.",
                "두 번째 후보.",
                "세 번째 후보.",
                "네 번째 후보.",
                "다섯 번째 후보.",
            ],
        )

    def test_constraint_prompt_contains_constraint_specific_rules(self):
        from app.services.suggest_hcx import _build_generation_prompt

        prompt = _build_generation_prompt(
            text="회의 결과를 정리해줘",
            context=None,
            element="CONSTRAINT",
        )

        self.assertIn("CONSTRAINT 전용 규칙", prompt)
        self.assertIn("제외 조건", prompt)


    def test_example_prompt_contains_example_specific_rules(self):
        from app.services.suggest_hcx import _build_generation_prompt

        prompt = _build_generation_prompt(
            text="회의 결과를 정리해줘",
            context=None,
            element="EXAMPLE",
        )

        self.assertIn("EXAMPLE 전용 규칙", prompt)
        self.assertIn("형태나 구조", prompt)    


if __name__ == "__main__":
    unittest.main()