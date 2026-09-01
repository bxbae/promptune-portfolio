import unittest
from unittest.mock import patch

from app.schemas.models import SuggestRequest
from app.services.suggest_hcx import (
    _filter_context_grounded_candidates,
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


def state(**overrides):
    value = {
        element: 0
        for element in ELEMENTS
    }
    value.update(overrides)
    return value


class SuggestionGroundingTest(unittest.TestCase):

    @patch(
        "app.services.suggest_hcx.calculate_similarities",
        return_value=[0.95, 0.84, 0.80],
    )
    def test_grounding_uses_relative_cutoff_and_preserves_order(
        self,
        mock_similarities,
    ):
        candidates = [
            "후보 A.",
            "후보 B.",
            "후보 C.",
        ]

        result = _filter_context_grounded_candidates(
            context="임원 보고와 의사결정 참고",
            candidates=candidates,
        )

        # best=0.95 -> cutoff=max(0.70, 0.95-0.12)=0.83
        self.assertEqual(
            result,
            [
                "후보 A.",
                "후보 B.",
            ],
        )

        mock_similarities.assert_called_once_with(
            reference="임원 보고와 의사결정 참고",
            candidates=candidates,
        )

    @patch(
        "app.services.suggest_hcx.calculate_similarities",
        return_value=[0.74, 0.72, 0.69],
    )
    def test_grounding_uses_minimum_cutoff(
        self,
        mock_similarities,
    ):
        candidates = [
            "후보 A.",
            "후보 B.",
            "후보 C.",
        ]

        result = _filter_context_grounded_candidates(
            context="팀 내부 공유",
            candidates=candidates,
        )

        # best=0.74 -> best-0.12=0.62 이므로 최소 기준 0.70 적용
        self.assertEqual(
            result,
            [
                "후보 A.",
                "후보 B.",
            ],
        )

        mock_similarities.assert_called_once()

    @patch(
        "app.services.suggest_hcx.calculate_similarities",
        return_value=[0.90],
    )
    def test_grounding_rejects_score_count_mismatch(
        self,
        mock_similarities,
    ):
        with self.assertRaises(RuntimeError):
            _filter_context_grounded_candidates(
                context="임원 보고",
                candidates=[
                    "후보 A.",
                    "후보 B.",
                ],
            )

        mock_similarities.assert_called_once()

    @patch(
        "app.services.suggest_hcx.calculate_similarities",
    )
    def test_grounding_skips_embedding_when_context_is_blank(
        self,
        mock_similarities,
    ):
        candidates = [
            "후보 A.",
            "후보 B.",
        ]

        result = _filter_context_grounded_candidates(
            context="   ",
            candidates=candidates,
        )

        self.assertEqual(
            result,
            candidates,
        )
        mock_similarities.assert_not_called()

    @patch(
        "app.services.suggest_hcx._filter_context_grounded_candidates",
        side_effect=RuntimeError("BGE failed"),
    )
    @patch(
        "app.services.suggest_hcx._generate_candidates",
        return_value=[
            "임원에게 보고하는 용도로 사용합니다.",
        ],
    )
    def test_context_suggest_does_not_bypass_grounding_failure(
        self,
        mock_generate,
        mock_grounding,
    ):
        req = SuggestRequest(
            text="회의 내용을 정리해줘",
            context="임원 보고와 의사결정 참고",
            target_elements=["CONTEXT"],
        )

        with patch(
            "app.services.suggest_hcx.predict_missing_with_rules",
            return_value=state(CONTEXT=1),
        ):
            result = suggest(req)

        self.assertEqual(
            result.suggestions,
            [],
        )

        mock_generate.assert_called_once()
        mock_grounding.assert_called_once()

    @patch(
        "app.services.suggest_hcx._filter_context_grounded_candidates",
    )
    @patch(
        "app.services.suggest_hcx._generate_candidates",
        return_value=[
            "표 형식으로 정리해줘.",
        ],
    )
    def test_non_context_element_does_not_use_context_grounding(
        self,
        mock_generate,
        mock_grounding,
    ):
        req = SuggestRequest(
            text="회의 내용을 정리해줘",
            context="임원 보고와 의사결정 참고",
            target_elements=["FORMAT"],
        )

        with patch(
            "app.services.suggest_hcx.predict_missing_with_rules",
            side_effect=[
                state(FORMAT=1),
                state(FORMAT=0),
            ],
        ):
            result = suggest(req)

        self.assertEqual(
            len(result.suggestions),
            1,
        )
        self.assertEqual(
            result.suggestions[0].primary,
            "표 형식으로 정리해줘.",
        )

        mock_generate.assert_called_once()
        mock_grounding.assert_not_called()

    @patch(
        "app.services.suggest_hcx._filter_context_grounded_candidates",
    )
    @patch(
        "app.services.suggest_hcx._generate_candidates",
        return_value=[
            (
                "프로젝트 개발 일정이 3일 지연되었습니다. "
                "새로운 완료 예정일은 2023년 10월 28일입니다."
            ),
        ],
    )
    def test_context_suggest_uses_explicit_context_when_all_generated_candidates_add_new_numbers(
        self,
        mock_generate,
        mock_grounding,
    ):
        context = (
            "프로젝트 개발 일정이 3일 지연되었습니다. "
            "지연 원인은 AI 모델 검증 작업이 추가되었기 때문이며, "
            "새로운 완료 예정일은 8월 28일입니다."
        )

        req = SuggestRequest(
            text="팀장님께 프로젝트 일정이 늦어질 것 같다고 메일 써줘.",
            context=context,
            target_elements=["CONTEXT"],
        )

        mock_grounding.return_value = [context]

        with patch(
            "app.services.suggest_hcx.predict_missing_with_rules",
            side_effect=[
                state(CONTEXT=1),
                state(CONTEXT=0),
            ],
        ):
            result = suggest(req)

        self.assertEqual(
            len(result.suggestions),
            1,
        )
        self.assertEqual(
            result.suggestions[0].primary,
            context,
        )

        mock_generate.assert_called_once()

        mock_grounding.assert_called_once_with(
            context=context,
            candidates=[context],
        )

    @patch(
        "app.services.suggest_hcx._filter_context_grounded_candidates",
    )
    @patch(
        "app.services.suggest_hcx._generate_candidates",
    )
    def test_context_suggest_uses_explicit_context_when_generated_candidates_fail_diagnosis_guard(
        self,
        mock_generate,
        mock_grounding,
    ):
        context = (
            "프로젝트 개발 일정이 3일 지연되었습니다. "
            "지연 원인은 AI 모델 검증 작업이 추가되었기 때문이며, "
            "새로운 완료 예정일은 8월 28일입니다."
        )

        generated_candidate = (
            "프로젝트 일정이 3일 지연되었으며 "
            "완료 예정일은 8월 28일입니다."
        )

        req = SuggestRequest(
            text="팀장님께 프로젝트 일정이 늦어질 것 같다고 메일 써줘.",
            context=context,
            target_elements=["CONTEXT"],
        )

        mock_generate.return_value = [generated_candidate]

        mock_grounding.side_effect = [
            [generated_candidate],
            [context],
        ]

        with patch(
            "app.services.suggest_hcx.predict_missing_with_rules",
            side_effect=[
                state(CONTEXT=1),
                state(CONTEXT=1),
                state(CONTEXT=0),
            ],
        ):
            result = suggest(req)

        self.assertEqual(len(result.suggestions), 1)
        self.assertEqual(
            result.suggestions[0].element,
            "CONTEXT",
        )
        self.assertEqual(
            result.suggestions[0].primary,
            context,
        )

        self.assertEqual(
            mock_grounding.call_count,
            2,
        )

        mock_grounding.assert_any_call(
            context=context,
            candidates=[generated_candidate],
        )
        mock_grounding.assert_any_call(
            context=context,
            candidates=[context],
        )


if __name__ == "__main__":
    unittest.main()
