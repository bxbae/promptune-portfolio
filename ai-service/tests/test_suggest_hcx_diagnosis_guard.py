import unittest
from unittest.mock import patch

from app.services.suggest_hcx import (
    _candidate_is_audience_safe,
    _candidate_is_diagnosis_safe,
    _context_candidate_has_only_allowed_numbers,
    _merge_prompt_with_candidate,
    _validate_generated_candidates,
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
    result = {element: 0 for element in ELEMENTS}
    result.update(overrides)
    return result


class SuggestionDiagnosisGuardTest(unittest.TestCase):
    def test_accepts_candidate_when_target_is_fixed_without_regression(self):
        baseline = state(CONTEXT=1)
        after = state(CONTEXT=0)

        self.assertTrue(
            _candidate_is_diagnosis_safe(
                element="CONTEXT",
                baseline=baseline,
                after=after,
            )
        )

    def test_rejects_candidate_when_target_is_still_missing(self):
        baseline = state(CONTEXT=1)
        after = state(CONTEXT=1)

        self.assertFalse(
            _candidate_is_diagnosis_safe(
                element="CONTEXT",
                baseline=baseline,
                after=after,
            )
        )

    def test_rejects_candidate_when_other_sufficient_element_regresses(self):
        baseline = state(CONTEXT=1, TASK=0)
        after = state(CONTEXT=0, TASK=1)

        self.assertFalse(
            _candidate_is_diagnosis_safe(
                element="CONTEXT",
                baseline=baseline,
                after=after,
            )
        )

    def test_context_candidate_is_merged_as_background_information(self):
        result = _merge_prompt_with_candidate(
            "팀장님께 프로젝트 일정이 늦어질 것 같다고 메일 써줘.",
            "프로젝트 개발 일정이 3일 지연되었습니다.",
            element="CONTEXT",
        )

        self.assertEqual(
            result,
            (
                "팀장님께 프로젝트 일정이 늦어질 것 같다고 메일 써줘.\n"
                "추가 배경 정보: 프로젝트 개발 일정이 3일 지연되었습니다."
            ),
        )

    def test_non_context_candidate_keeps_existing_merge_format(self):
        result = _merge_prompt_with_candidate(
            "보고서 작성해줘",
            "표 형식으로 작성해줘.",
            element="FORMAT",
        )

        self.assertEqual(
            result,
            "보고서 작성해줘. 표 형식으로 작성해줘.",
        )

    def test_context_candidate_accepts_numbers_from_context(self):
        self.assertTrue(
            _context_candidate_has_only_allowed_numbers(
                context=(
                    "프로젝트 개발 일정이 3일 지연되었습니다. "
                    "새로운 완료 예정일은 8월 28일입니다."
                ),
                candidate=(
                    "프로젝트 일정이 3일 지연되었으며 "
                    "완료 예정일은 8월 28일입니다."
                ),
            )
        )

    def test_context_candidate_rejects_new_numbers(self):
        self.assertFalse(
            _context_candidate_has_only_allowed_numbers(
                context=(
                    "프로젝트 개발 일정이 3일 지연되었습니다. "
                    "새로운 완료 예정일은 8월 28일입니다."
                ),
                candidate=(
                    "프로젝트 일정이 3일 지연되었으며 "
                    "완료 예정일은 2023년 10월 28일입니다."
                ),
            )
        )

    def test_context_candidate_without_numbers_is_allowed_when_context_has_none(self):
        self.assertTrue(
            _context_candidate_has_only_allowed_numbers(
                context="AI 모델 검증 작업이 추가되었습니다.",
                candidate="AI 모델 검증 작업이 추가된 상황입니다.",
            )
        )

    @patch("app.services.suggest_hcx.predict_missing_with_rules")
    def test_filters_generated_candidates_and_preserves_generation_order(
        self,
        mock_predict_missing,
    ):
        baseline = state(CONTEXT=1)

        mock_predict_missing.side_effect = [
            state(CONTEXT=0),          # A 통과
            state(CONTEXT=0, TASK=1),  # B 회귀로 탈락
            state(CONTEXT=0),          # C 통과
        ]

        result = _validate_generated_candidates(
            text="회의 내용 정리해 줘",
            element="CONTEXT",
            candidates=[
                "A 후보.",
                "B 후보.",
                "C 후보.",
            ],
            baseline=baseline,
        )

        self.assertEqual(
            result,
            [
                "A 후보.",
                "C 후보.",
            ],
        )

        self.assertEqual(
            mock_predict_missing.call_count,
            3,
        )

    def test_audience_guard_accepts_prompt_instruction(self):
        self.assertTrue(
            _candidate_is_audience_safe(
                "팀장님께 전달하는 메일로 작성해줘."
            )
        )

    def test_audience_guard_rejects_email_body_sentence(self):
        self.assertFalse(
            _candidate_is_audience_safe(
                "관련 팀에 전달하였습니다."
            )
        )

    def test_audience_guard_rejects_action_only_sentence(self):
        self.assertFalse(
            _candidate_is_audience_safe(
                "프로젝트 일정 연기에 대한 사항을 팀원들에게 공유해 주세요."
            )
        )
        
if __name__ == "__main__":
    unittest.main()