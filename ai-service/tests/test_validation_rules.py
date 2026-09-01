import unittest

from app.services.validation.rule_validator import validate_rules


class ValidationRuleTest(unittest.TestCase):

    def test_max_length_passes(self):
        original = "100자 이내로 작성해줘"
        generated = "짧게 작성한 답변입니다."

        result = validate_rules(original, generated)

        self.assertTrue(result.length_ok)

    def test_max_length_fails(self):
        original = "10자 이내로 작성해줘"
        generated = "이 문장은 열 글자를 명확하게 초과하는 답변입니다."

        result = validate_rules(original, generated)

        self.assertFalse(result.length_ok)

    def test_requested_item_count_passes(self):
        original = "핵심 내용을 3개 항목으로 정리해줘"
        generated = "- 첫 번째\n- 두 번째\n- 세 번째"

        result = validate_rules(original, generated)

        self.assertTrue(result.item_count_ok)

    def test_requested_item_count_range_passes(self):
        original = "핵심 내용을 2~3가지로 정리해줘"
        generated = "- 첫 번째\n- 두 번째"

        result = validate_rules(original, generated)

        self.assertTrue(result.item_count_ok)
        self.assertTrue(result.facts_preserved)

    def test_requested_item_count_range_fails_below_minimum(self):
        original = "핵심 내용을 2~3가지로 정리해줘"
        generated = "- 첫 번째"

        result = validate_rules(original, generated)

        self.assertFalse(result.item_count_ok)

    def test_requested_item_count_range_fails_above_maximum(self):
        original = "핵심 내용을 2~3가지로 정리해줘"
        generated = "- 첫 번째\n- 두 번째\n- 세 번째\n- 네 번째"

        result = validate_rules(original, generated)

        self.assertFalse(result.item_count_ok)

    def test_item_count_range_numbers_are_not_treated_as_facts(self):
        original = "핵심 내용을 2~3가지로 정리해줘"
        generated = "- 핵심 A\n- 핵심 B"

        result = validate_rules(original, generated)

        self.assertTrue(result.facts_preserved)

    def test_markdown_table_passes(self):
        original = "결과를 표 형식으로 정리해줘"
        generated = (
            "| 항목 | 내용 |\n"
            "| --- | --- |\n"
            "| A | 설명 |\n"
        )

        result = validate_rules(original, generated)

        self.assertTrue(result.format_ok)

    def test_plain_text_fails_when_table_requested(self):
        original = "결과를 표 형식으로 정리해줘"
        generated = "A 항목에 대한 설명입니다."

        result = validate_rules(original, generated)

        self.assertFalse(result.format_ok)

    def test_fact_numbers_are_preserved(self):
        original = "매출은 120억이고 성장률은 15%야. 이를 요약해줘"
        generated = "매출은 120억이며 성장률은 15%입니다."

        result = validate_rules(original, generated)

        self.assertTrue(result.facts_preserved)

    def test_missing_fact_number_fails(self):
        original = "매출은 120억이고 성장률은 15%야. 이를 요약해줘"
        generated = "매출은 120억입니다."

        result = validate_rules(original, generated)

        self.assertFalse(result.facts_preserved)

    def test_constraint_number_is_not_treated_as_fact(self):
        original = "핵심 내용을 3개 항목으로 정리해줘"
        generated = "- A\n- B\n- C"

        result = validate_rules(original, generated)

        self.assertTrue(result.facts_preserved)

    def test_product_quantity_is_not_item_count_constraint(self):
        original = "사과 3개 가격을 요약해줘"
        generated = "사과 3개의 가격을 요약했습니다."

        result = validate_rules(original, generated)

        self.assertTrue(result.item_count_ok)


    def test_product_quantity_is_treated_as_fact_number(self):
        original = "사과 3개 가격을 요약해줘"
        generated = "사과 가격을 요약했습니다."

        result = validate_rules(original, generated)

        self.assertFalse(result.facts_preserved)

    def test_paragraph_count_directive_is_not_treated_as_fact(self):
        # 2026-08-26: "이강인 선수의 프로필을 안내해줘...3문단으로..." 질의에서
        # 모델이 정확히 3문단(항목별 정리)으로 답했는데도 본문에 숫자 "3"이
        # 없다는 이유로 facts_preserved=False가 되어, generate 재시도까지
        # 실패하면서 "검증을 통과하는 답변을 생성하지 못했습니다" 503이 실제로
        # 재현된 사례.
        original = "이강인 선수의 프로필을 안내해줘. 3문단으로. 전문적으로."
        generated = "- 소속: 아틀레티코 마드리드\n- 생년월일: 2001년 2월 19일\n- 체중: 66kg"

        result = validate_rules(original, generated)

        self.assertTrue(result.facts_preserved)

    def test_sentence_count_range_directive_is_not_treated_as_fact(self):
        original = "핵심만 3~4줄로 요약해줘"
        generated = "핵심 내용을 짧게 정리했습니다."

        result = validate_rules(original, generated)

        self.assertTrue(result.facts_preserved)

    def test_max_sentence_count_directive_is_not_treated_as_fact(self):
        original = "5문장 이내로 답해줘"
        generated = "짧게 답한 문장입니다."

        result = validate_rules(original, generated)

        self.assertTrue(result.facts_preserved)

    def test_paragraph_count_directive_does_not_affect_real_facts(self):
        # 서식 지시어 숫자는 빠지되, 진짜 사실 숫자(매출 등)는 여전히 보존
        # 검사 대상이어야 한다 - 이번 수정이 기존 사실 보존 검사를 느슨하게
        # 만들지 않았는지 확인.
        original = "매출은 120억이야. 이를 3문단으로 요약해줘"
        generated = "핵심 내용을 짧게 정리했습니다."

        result = validate_rules(original, generated)

        self.assertFalse(result.facts_preserved)
        self.assertIn("120", "".join(result.issues))


if __name__ == "__main__":
    unittest.main()