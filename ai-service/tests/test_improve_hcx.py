import unittest
from unittest.mock import patch

import torch

from app.schemas.models import (
    ImprovePromptRequest,
    PreferenceInput,
    PromptRuleResponse,
)
from app.services.improve_hcx import (
    _build_fallback_prompt,
    _build_missing_instructions,
    _build_preference_instructions,
    _build_prompt,
    _build_strategy_instructions,
    _contains_meta_output,
    _is_acceptable_output,
    improve,
)


def make_request(
    *,
    text="회의 내용 정리해줘",
    task_type="email",
    speed="accurate",
    detail="detailed",
    preserve="improve",
    missing_elements=None,
    use_role=False,
    role_hint=None,
    decompose_task=False,
    use_positive_instruction=True,
    use_few_shot=False,
):
    return ImprovePromptRequest(
        text=text,
        task_type=task_type,
        preference=PreferenceInput(
            speed=speed,
            detail=detail,
            preserve=preserve,
        ),
        prompt_rule=PromptRuleResponse(
            missing_elements=missing_elements or [],
            use_role=use_role,
            role_hint=role_hint,
            decompose_task=decompose_task,
            use_positive_instruction=use_positive_instruction,
            use_few_shot=use_few_shot,
        ),
    )


def _make_runtime_request() -> ImprovePromptRequest:
    return ImprovePromptRequest(
        text="회의 내용 정리해줘",
        task_type="email",
        preference=PreferenceInput(
            speed="accurate",
            detail="detailed",
            preserve="improve",
        ),
        prompt_rule=PromptRuleResponse(
            missing_elements=["CONTEXT"],
            use_role=False,
            role_hint=None,
            decompose_task=False,
            use_positive_instruction=True,
            use_few_shot=False,
        ),
    )

class _FakeBatchEncoding(dict):
    def to(self, device):
        return self

class _FakeTokenizer:
    eos_token_id = 0

    def __init__(self, decoded_text: str):
        self.decoded_text = decoded_text

    def apply_chat_template(
        self,
        messages,
        tokenize,
        add_generation_prompt,
        return_dict,
        return_tensors,
    ):
        return _FakeBatchEncoding(
            {
                "input_ids": torch.tensor(
                    [[1, 2]],
                    dtype=torch.long,
                )
            }
        )

    def decode(self, tokens, skip_special_tokens=True):
        return self.decoded_text


class _FakeModel:
    def generate(self, input_ids=None, **kwargs):
        return torch.tensor([[1, 2, 3]], dtype=torch.long)


class _FailingModel:
    def generate(self, input_ids=None, **kwargs):
        raise RuntimeError("mock HCX generation failure")


class ImproveHcxPromptTest(unittest.TestCase):
    def test_missing_elements_become_placeholders(self):
        req = make_request(
            missing_elements=["CONTEXT", "FORMAT"],
        )

        result = _build_missing_instructions(req)

        self.assertIn("[배경/상황 정보]", result)
        self.assertIn("[원하는 출력 형식]", result)
        self.assertIn("임의로 만들어내지 말고", result)

    def test_no_missing_elements(self):
        req = make_request(missing_elements=[])

        result = _build_missing_instructions(req)

        self.assertEqual("부족하다고 판정된 요소 없음.", result)

    def test_keep_and_brief_preferences(self):
        req = make_request(
            speed="fast",
            detail="brief",
            preserve="keep",
        )

        result = _build_preference_instructions(req)

        self.assertIn("최대한 유지", result)
        self.assertIn("짧고 바로 사용할 수 있게", result)

    def test_improve_and_detailed_preferences(self):
        req = make_request(
            detail="detailed",
            preserve="improve",
        )

        result = _build_preference_instructions(req)

        self.assertIn("적극적으로 재구성", result)
        self.assertIn("조건과 구조를 충분히 명시", result)

    def test_role_and_positive_instruction(self):
        req = make_request(
            task_type="report",
            use_role=True,
            role_hint="업무 보고서 작성 전문가",
            use_positive_instruction=True,
        )

        result = _build_strategy_instructions(req)

        self.assertIn("업무 보고서 작성 전문가", result)
        self.assertIn("긍정형 지시", result)

    def test_false_role_does_not_apply_role_hint(self):
        req = make_request(
            use_role=False,
            role_hint="업무 보고서 작성 전문가",
        )

        result = _build_strategy_instructions(req)

        self.assertNotIn("업무 보고서 작성 전문가", result)

    def test_full_prompt_contains_hallucination_guards(self):
        req = make_request(
            text="회의 내용 정리해줘",
            missing_elements=["CONTEXT"],
        )

        result = _build_prompt(req)

        # 원본 목적 보존
        self.assertIn("회의 내용 정리해줘", result)
        self.assertIn("원본 요청의 목적은 반드시 유지", result)

        # missing 요소는 deterministic placeholder로 처리
        self.assertIn("[배경/상황 정보]", result)
        self.assertIn("구체적인 내용을 추측해서 채우지 마", result)
        self.assertIn("placeholder 문자열을 그대로 포함", result)

        # hallucination 방지
        self.assertIn(
            "사용자가 제공하지 않은 사람, 날짜, 숫자, 사건",
            result,
        )
        self.assertIn("회사 정보나 배경 사실", result)

        # 사용자 원문에 있는 중요 정보 보존
        self.assertIn("고유명사, 숫자, 기한, 조건을 변경하지 마", result)

        # 메타 설명이 아니라 실제 재사용 가능한 프롬프트를 생성하도록 제한
        self.assertIn(
            "실제로 AI에게 바로 입력할 수 있는 업무 요청문 한 개",
            result,
        )
        self.assertIn("제목이나 설명을 추가하지 마", result)

    def test_acceptable_output_with_all_required_placeholders(self):
        req = make_request(
            missing_elements=["CONTEXT", "FORMAT"],
        )

        output = (
            "[배경/상황 정보]를 바탕으로 회의 내용을 정리해줘. "
            "결과는 [원하는 출력 형식]에 맞춰 작성해줘."
        )

        self.assertTrue(_is_acceptable_output(req, output))

    def test_output_missing_required_placeholder_is_rejected(self):
        req = make_request(
            missing_elements=["CONTEXT", "FORMAT"],
        )

        output = "[배경/상황 정보]를 바탕으로 회의 내용을 정리해줘."

        self.assertFalse(_is_acceptable_output(req, output))

    def test_meta_output_is_rejected(self):
        req = make_request(
            missing_elements=["CONTEXT"],
        )

        output = (
            "[설명] 프롬프트를 개선했습니다. "
            "[배경/상황 정보]를 입력하세요."
        )

        self.assertFalse(_is_acceptable_output(req, output))

    def test_empty_output_is_rejected(self):
        req = make_request(
            missing_elements=["CONTEXT"],
        )

        self.assertFalse(_is_acceptable_output(req, "   "))

    def test_fallback_preserves_original_and_required_placeholders(self):
        req = make_request(
            text="회의 내용 정리해줘",
            missing_elements=["CONTEXT", "FORMAT"],
            use_positive_instruction=True,
        )

        result = _build_fallback_prompt(req)

        self.assertIn("회의 내용 정리해줘", result)
        self.assertIn("[배경/상황 정보]", result)
        self.assertIn("[원하는 출력 형식]", result)
        self.assertIn(
            "해야 할 행동과 원하는 결과를 명확하게 표현해",
            result,
        )


class TestImproveRuntime(unittest.TestCase):
    def test_improve_returns_hcx_output_when_guard_passes(self):
        req = _make_runtime_request()

        tokenizer = _FakeTokenizer(
            "회의 내용 정리해줘. [배경/상황 정보]를 반영해 정리해줘."
        )
        model = _FakeModel()

        with patch(
            "app.services.improve_hcx.load_hcx_runtime",
            return_value=(tokenizer, model, "cpu"),
        ):
            result = improve(req)

        self.assertFalse(result.used_fallback)
        self.assertIn("회의 내용 정리해줘", result.improved_prompt)
        self.assertIn("[배경/상황 정보]", result.improved_prompt)

    def test_improve_uses_fallback_when_guard_rejects_output(self):
        req = _make_runtime_request()

        # CONTEXT가 필요한데 placeholder를 빠뜨린 HCX 출력
        tokenizer = _FakeTokenizer("회의 내용을 깔끔하게 정리해줘.")
        model = _FakeModel()

        with patch(
            "app.services.improve_hcx.load_hcx_runtime",
            return_value=(tokenizer, model, "cpu"),
        ):
            result = improve(req)

        self.assertTrue(result.used_fallback)
        self.assertIn("회의 내용 정리해줘", result.improved_prompt)
        self.assertIn("[배경/상황 정보]", result.improved_prompt)

    def test_improve_uses_fallback_when_hcx_generation_raises(self):
        req = _make_runtime_request()

        tokenizer = _FakeTokenizer("")
        model = _FailingModel()

        with patch(
            "app.services.improve_hcx.load_hcx_runtime",
            return_value=(tokenizer, model, "cpu"),
        ):
            with patch(
                "app.services.improve_hcx.logger.exception"
            ) as mock_log:
                result = improve(req)

        self.assertTrue(result.used_fallback)
        self.assertIn("회의 내용 정리해줘", result.improved_prompt)
        self.assertIn("[배경/상황 정보]", result.improved_prompt)
        mock_log.assert_called_once()

    def test_meta_output_prefix_detection(self):
        rejected_outputs = [
            "[개선된 프롬프트] 회의 내용을 정리해줘",
            "[재작성된 프롬프트] 회의 내용을 정리해줘",
            "개선된 프롬프트: 회의 내용을 정리해줘",
            "재작성된 프롬프트: 회의 내용을 정리해줘",
            "개선 결과: 회의 내용을 정리해줘",
            "다음은 개선된 요청입니다: 회의 내용을 정리해줘",
            "### 다음은 재작성된 요청입니다: 회의 내용을 정리해줘",
            "**개선 결과:** 회의 내용을 정리해줘",
        ]

        for output in rejected_outputs:
            with self.subTest(output=output):
                self.assertTrue(_contains_meta_output(output))

        # 업무 내용 자체에 '분석' 같은 단어가 들어가는 것은 허용해야 한다.
        self.assertFalse(
            _contains_meta_output("매출 분석 보고서를 작성해줘")
        )

    def test_output_preserves_original_numbers(self):
        req = make_request(
            text="개발 일정이 3일 지연됐고 완료 예정일은 8월 28일이야",
            missing_elements=[],
        )

        output = (
            "개발 일정이 3일 지연됐고 "
            "완료 예정일은 8월 28일이야."
        )

        self.assertTrue(_is_acceptable_output(req, output))


    def test_output_missing_original_number_is_rejected(self):
        req = make_request(
            text="개발 일정이 3일 지연됐고 완료 예정일은 8월 28일이야",
            missing_elements=[],
        )

        output = "개발 일정이 지연됐고 완료 예정일은 8월 28일이야."

        self.assertFalse(_is_acceptable_output(req, output))

    def test_output_missing_explicit_constraint_is_rejected(self):
        req = make_request(
            text="회의 내용을 요약해줘. 개인정보는 포함하지 마.",
            missing_elements=[],
        )

        output = "회의 내용을 명확하게 요약해줘."

        self.assertFalse(
            _is_acceptable_output(req, output)
        )    

    def test_output_preserves_explicit_constraint(self):
        req = make_request(
            text="회의 내용을 요약해줘. 개인정보는 포함하지 마.",
            missing_elements=[],
        )

        output = (
            "회의 내용을 명확하게 요약해줘. "
            "개인정보는 포함하지 마."
        )

        self.assertTrue(
            _is_acceptable_output(req, output)
        )

if __name__ == "__main__":
    unittest.main()