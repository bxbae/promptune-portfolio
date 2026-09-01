import unittest

from app.services.generate_hcx import (
    _build_web_context,
    _compact_web_content,
)


class WebContextCompactionTest(unittest.TestCase):

    def test_preserves_identity_fact_beyond_prefix(self):
        content = (
            "일반 소개 내용 " * 100
            + " 본명이병건 (Lee Byeong-geon) "
            + "이말년은 필명이다."
        )

        compact = _compact_web_content(content)

        self.assertIn(
            "본명이병건",
            compact,
        )

        self.assertLessEqual(
            len(compact),
            700,
        )

    def test_web_context_contains_late_profile_fact(self):
        content = (
            "방송과 콘텐츠 소개 " * 100
            + " 본명이병건 "
            + "이말년은 필명이다."
        )

        context = _build_web_context([
            {
                "title": "침착맨",
                "url": "https://example.com/chim",
                "content": content,
            },
        ])

        self.assertIn(
            "본명이병건",
            context,
        )


if __name__ == "__main__":
    unittest.main()
