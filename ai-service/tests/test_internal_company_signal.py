import unittest

from app.services.retrieval.ml_router import (
    resolve_strong_retrieval_route,
)


class InternalCompanySignalTest(unittest.TestCase):

    def test_company_report_template_is_internal(self):
        self.assertEqual(
            resolve_strong_retrieval_route(
                "우리회사 보고서 양식 알려줘"
            ),
            "internal_rag",
        )

    def test_company_policy_is_internal(self):
        self.assertEqual(
            resolve_strong_retrieval_route(
                "우리 회사 연차 규정 알려줘"
            ),
            "internal_rag",
        )

    def test_internal_security_guide_is_internal(self):
        self.assertEqual(
            resolve_strong_retrieval_route(
                "사내 정보보안 지침 찾아줘"
            ),
            "internal_rag",
        )

    def test_generic_report_is_not_forced_internal(self):
        self.assertIsNone(
            resolve_strong_retrieval_route(
                "보고서 작성법 알려줘"
            )
        )

    def test_external_company_profile_is_not_internal(self):
        self.assertIsNone(
            resolve_strong_retrieval_route(
                "삼성전자 회사 소개 알려줘"
            )
        )


if __name__ == "__main__":
    unittest.main()
