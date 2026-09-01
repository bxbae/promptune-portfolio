import unittest
from unittest.mock import patch

from app.routers.pipeline import validate
from app.schemas.models import ValidateRequest
from app.services.validation.validator import FinalValidationResult


class ValidateEndpointTest(unittest.TestCase):

    @patch("app.routers.pipeline.validate_response")
    def test_validate_endpoint_uses_real_validator(
        self,
        mock_validate_response,
    ):
        mock_validate_response.return_value = FinalValidationResult(
            passed=True,
            rule_ok=True,
            semantic_ok=True,
            semantic_score=0.82,
            facts_preserved=True,
            issues=[],
        )

        request = ValidateRequest(
            original="회의 내용을 3개 항목으로 정리해줘",
            generated="- 첫째\n- 둘째\n- 셋째",
        )

        response = validate(request)

        mock_validate_response.assert_called_once_with(
            original=request.original,
            generated=request.generated,
        )

        self.assertTrue(response.passed)
        self.assertTrue(response.rule_ok)
        self.assertTrue(response.semantic_ok)
        self.assertEqual(response.semantic_score, 0.82)
        self.assertTrue(response.facts_preserved)
        self.assertEqual(response.issues, [])


if __name__ == "__main__":
    unittest.main()