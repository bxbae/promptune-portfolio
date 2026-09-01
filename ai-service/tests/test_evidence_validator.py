import unittest

from app.services.validation.evidence_validator import (
    validate_evidence_identity,
)


class EvidenceValidatorTest(unittest.TestCase):

    def setUp(self):
        self.web = [
            {
                "title": "침착맨",
                "content": (
                    "침착맨 프로필. "
                    "본명이병건 (Lee Byeong-geon). "
                    "이말년은 필명이다."
                ),
            }
        ]

    def test_rejects_unsupported_real_name(self):
        issues = validate_evidence_identity(
            "침착맨은 이말년(본명 김완수)입니다.",
            web_results=self.web,
        )

        self.assertTrue(issues)

    def test_accepts_supported_real_name(self):
        issues = validate_evidence_identity(
            "침착맨의 본명은 이병건이며 이말년은 필명입니다.",
            web_results=self.web,
        )

        self.assertEqual(
            issues,
            [],
        )

    def test_no_evidence_does_not_block_chat(self):
        issues = validate_evidence_identity(
            "제 본명은 홍길동입니다.",
            web_results=[],
            documents=[],
        )

        self.assertEqual(
            issues,
            [],
        )


if __name__ == "__main__":
    unittest.main()
