import unittest

from app.services.retrieval.retrieval_orchestrator import (
    _is_document_catalog_query,
)


class DocumentCatalogIntentTest(
    unittest.TestCase
):

    def test_internal_document_list(self):
        self.assertTrue(
            _is_document_catalog_query(
                "내부문서에는 무슨 파일이 있어?"
            )
        )

    def test_internal_document_what_exists(self):
        self.assertTrue(
            _is_document_catalog_query(
                "내부 문서에 뭐 있어?"
            )
        )

    def test_document_box_list(self):
        self.assertTrue(
            _is_document_catalog_query(
                "문서함 목록 보여줘"
            )
        )

    def test_specific_internal_document_is_not_catalog(self):
        self.assertFalse(
            _is_document_catalog_query(
                "내부문서에 있는 회사 보고서 양식 알려줘"
            )
        )

    def test_generic_report_is_not_catalog(self):
        self.assertFalse(
            _is_document_catalog_query(
                "회사 보고서 양식 알려줘"
            )
        )


if __name__ == "__main__":
    unittest.main()
