import unittest
from unittest.mock import patch

from app.services.validation.semantic_validator import (
    SemanticValidationResult,
)
from app.services.validation.validator import validate_response


class FinalValidatorTest(unittest.TestCase):

    @patch(
        "app.services.validation.validator.ENABLE_SEMANTIC_VALIDATION_TELEMETRY",
        True,
    )
    @patch("app.services.validation.validator.validate_semantic")
    def test_passes_when_rule_and_semantic_both_pass(
        self,
        mock_semantic,
    ):
        mock_semantic.return_value = SemanticValidationResult(
            semantic_ok=True,
            score=0.82,
            issues=[],
        )

        result = validate_response(
            original="핵심 내용을 3개 항목으로 정리해줘",
            generated="- 첫째\n- 둘째\n- 셋째",
        )

        self.assertTrue(result.passed)
        self.assertTrue(result.rule_ok)
        self.assertTrue(result.semantic_ok)
        self.assertEqual(result.issues, [])

    @patch("app.services.validation.validator.validate_semantic")
    def test_fails_when_rule_validation_fails(
        self,
        mock_semantic,
    ):
        mock_semantic.return_value = SemanticValidationResult(
            semantic_ok=True,
            score=0.85,
            issues=[],
        )

        result = validate_response(
            original="10자 이내로 작성해줘",
            generated="이 문장은 요청된 길이 제한을 분명하게 초과합니다.",
        )

        self.assertFalse(result.passed)
        self.assertFalse(result.rule_ok)
        self.assertTrue(result.semantic_ok)
        self.assertTrue(result.issues)

    @patch(
        "app.services.validation.validator.ENABLE_SEMANTIC_VALIDATION_TELEMETRY",
        True,
    )
    @patch("app.services.validation.validator.validate_semantic")
    def test_semantic_failure_is_telemetry_only(
        self,
        mock_semantic,
    ):
        mock_semantic.return_value = SemanticValidationResult(
            semantic_ok=False,
            score=0.30,
            issues=["의미 기반 지시 준수 점수가 기준보다 낮습니다."],
        )

        result = validate_response(
            original="회의 내용을 요약해줘",
            generated="오늘 날씨는 맑습니다.",
        )

        self.assertTrue(result.passed)
        self.assertTrue(result.rule_ok)
        self.assertFalse(result.semantic_ok)
        self.assertTrue(result.issues)

    @patch(
        "app.services.validation.validator.ENABLE_SEMANTIC_VALIDATION_TELEMETRY",
        True,
    )
    @patch("app.services.validation.validator.validate_semantic")
    def test_rule_and_semantic_issues_are_merged(
        self,
        mock_semantic,
    ):
        mock_semantic.return_value = SemanticValidationResult(
            semantic_ok=False,
            score=0.30,
            issues=["의미 기반 지시 준수 실패"],
        )

        result = validate_response(
            original="10자 이내로 회의 내용을 요약해줘",
            generated="오늘 날씨에 대한 아주 긴 설명을 작성했습니다.",
        )

        self.assertFalse(result.passed)
        self.assertFalse(result.rule_ok)
        self.assertFalse(result.semantic_ok)
        self.assertGreaterEqual(len(result.issues), 2)

    @patch("app.services.validation.validator.validate_semantic")
    def test_range_format_directive_length_does_not_require_leaked_number(
        self,
        mock_semantic,
    ):
        mock_semantic.return_value = SemanticValidationResult(
            semantic_ok=True,
            score=0.90,
            issues=[],
        )

        original = (
            "리센느. 요약해줘. 나에게. 발매 곡 기준으로 추가로 필요한 정보: "
            "[대상/수신자], [배경/상황 정보], [원하는 출력 형식], 전문적으로, "
            "3~4줄로, [제약 조건]. 숫자는 꼭 포함해서"
        )
        generated = (
            "리센느는 대한민국의 가수입니다. "
            "정확한 정보를 찾기 어렵습니다."
        )

        result = validate_response(
            original=original,
            generated=generated,
        )

        self.assertTrue(result.facts_preserved)
        self.assertTrue(result.rule_ok)
        self.assertTrue(result.passed)
        self.assertEqual(result.issues, [])

    @patch("app.services.validation.validator.validate_semantic")
    def test_other_range_format_directives_are_also_excluded(
        self,
        mock_semantic,
    ):
        mock_semantic.return_value = SemanticValidationResult(
            semantic_ok=True,
            score=0.90,
            issues=[],
        )

        for phrase in (
            "3~4문단으로",
            "5~6줄로",
        ):
            with self.subTest(phrase=phrase):
                result = validate_response(
                    original=f"아무 주제나 요약해줘. {phrase}. 숫자는 꼭 포함해서",
                    generated="요청하신 내용을 정리했습니다.",
                )

                self.assertTrue(result.facts_preserved, phrase)
                self.assertTrue(result.rule_ok, phrase)
                self.assertTrue(result.passed, phrase)

    @patch("app.services.validation.validator.validate_semantic")
    def test_real_fact_number_is_still_required(
        self,
        mock_semantic,
    ):
        mock_semantic.return_value = SemanticValidationResult(
            semantic_ok=True,
            score=0.90,
            issues=[],
        )

        result = validate_response(
            original="2001년생 이강인 선수를 요약해서 알려줘",
            generated="이강인 선수에 대한 정보를 요약했습니다.",
        )

        self.assertFalse(result.facts_preserved)
        self.assertFalse(result.rule_ok)
        self.assertFalse(result.passed)
        self.assertTrue(
            any("2001" in issue for issue in result.issues)
        )

    @patch("app.services.validation.validator.validate_semantic")
    def test_single_number_format_directive_is_still_excluded(
        self,
        mock_semantic,
    ):
        mock_semantic.return_value = SemanticValidationResult(
            semantic_ok=True,
            score=0.90,
            issues=[],
        )

        result = validate_response(
            original="이강인 선수 프로필을 3문단으로 요약해줘",
            generated="이강인 선수에 대한 프로필을 요약했습니다.",
        )

        self.assertTrue(result.facts_preserved)
        self.assertTrue(result.rule_ok)
        self.assertTrue(result.passed)


    @patch(
        "app.services.validation.validator.ENABLE_SEMANTIC_VALIDATION_TELEMETRY",
        False,
    )
    def test_item_count_range_passes_final_validation(self):
        result = validate_response(
            original="핵심 내용을 2~3가지로 정리해줘",
            generated="- 첫째\n- 둘째",
        )

        self.assertTrue(result.rule_ok)
        self.assertTrue(result.passed)
        self.assertTrue(result.facts_preserved)

    @patch(
        "app.services.validation.validator.ENABLE_SEMANTIC_VALIDATION_TELEMETRY",
        False,
    )
    def test_item_count_range_violation_fails_final_validation(self):
        result = validate_response(
            original="핵심 내용을 2~3가지로 정리해줘",
            generated="- 첫째\n- 둘째\n- 셋째\n- 넷째",
        )

        self.assertFalse(result.rule_ok)
        self.assertFalse(result.passed)
        self.assertTrue(result.facts_preserved)
        self.assertTrue(
            any("항목 개수 조건 위반" in issue for issue in result.issues)
        )


if __name__ == "__main__":
    unittest.main()
