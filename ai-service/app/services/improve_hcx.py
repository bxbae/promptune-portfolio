from __future__ import annotations

import re

import logging

import torch

from app.schemas.models import ImprovePromptRequest, ImprovePromptResponse
from app.services.hcx_runtime import hcx_lock, load_hcx_runtime
from app.services.validation.rule_validator import extract_numbers

logger = logging.getLogger(__name__)


_PLACEHOLDERS = {
    "TASK": "[해야 할 작업]",
    "AUDIENCE": "[대상/수신자]",
    "CONTEXT": "[배경/상황 정보]",
    "FORMAT": "[원하는 출력 형식]",
    "TONE": "[원하는 어조]",
    "LENGTH": "[원하는 길이]",
    "CONSTRAINT": "[제약 조건]",
    "EXAMPLE": "[참고 예시]",
}


def _build_missing_instructions(req: ImprovePromptRequest) -> str:
    if not req.prompt_rule.missing_elements:
        return "부족하다고 판정된 요소 없음."

    lines: list[str] = []

    for element in req.prompt_rule.missing_elements:
        placeholder = _PLACEHOLDERS.get(element)

        if placeholder is None:
            continue

        lines.append(
            f"- {element}: 사용자가 제공하지 않은 정보를 임의로 만들어내지 말고, "
            f"해당 정보가 원문에 없으므로 {placeholder} placeholder를 사용해 표시하고, "
            f"구체적인 내용을 추측해서 채우지 마."
        )

    return "\n".join(lines) if lines else "부족하다고 판정된 요소 없음."


def _build_preference_instructions(req: ImprovePromptRequest) -> str:
    if req.preference.preserve == "keep":
        preserve_instruction = (
            "원문의 의미와 표현을 최대한 유지하고, 필요한 부분만 최소한으로 보완해."
        )
    else:
        preserve_instruction = (
            "원문의 의도와 사용자가 제공한 사실은 반드시 보존하되, "
            "더 명확한 프롬프트가 되도록 구조와 표현을 적극적으로 재구성해도 돼."
        )

    if req.preference.detail == "brief":
        detail_instruction = (
            "개선된 프롬프트는 짧고 바로 사용할 수 있게 작성해."
        )
    else:
        detail_instruction = (
            "개선된 프롬프트에는 필요한 조건과 구조를 충분히 명시해."
        )

    # speed는 Prompt Rule 단계에서 전략 선택에 이미 사용한다.
    return f"- {preserve_instruction}\n- {detail_instruction}"


def _build_strategy_instructions(req: ImprovePromptRequest) -> str:
    rule = req.prompt_rule
    lines: list[str] = []

    if rule.use_role and rule.role_hint:
        lines.append(
            f"- 프롬프트에 다음 역할을 자연스럽게 반영해: {rule.role_hint}"
        )

    if rule.decompose_task:
        lines.append(
            "- 복합 작업은 실행하기 쉬운 단계 또는 하위 작업으로 나눠 표현해."
        )

    if rule.use_positive_instruction:
        lines.append(
            "- 금지 사항을 나열하기보다 수행해야 할 행동을 명확한 긍정형 지시로 표현해."
        )

    if not rule.use_few_shot:
        lines.append(
            "- 사용자가 제공하지 않은 예시나 샘플 내용을 새로 만들어내지 마."
        )

    return "\n".join(lines) if lines else "- 추가 전략 없음."


def _build_prompt(req: ImprovePromptRequest) -> str:
    missing_instructions = _build_missing_instructions(req)
    preference_instructions = _build_preference_instructions(req)
    strategy_instructions = _build_strategy_instructions(req)

    return (
        "아래 원본 업무 요청을 더 명확하고 실행 가능한 프롬프트로 다시 작성해.\n\n"

        "원본 요청:\n"
        f"{req.text}\n\n"

        "작성 조건:\n"
        f"{preference_instructions}\n"
        f"{missing_instructions}\n"
        f"{strategy_instructions}\n\n"

        "중요 규칙:\n"
        "- 원본 요청의 목적은 반드시 유지해.\n"
        "- 사용자가 제공하지 않은 사람, 날짜, 숫자, 사건, 회사 정보나 배경 사실을 "
        "새로 만들지 마.\n"
        "- 부족한 정보는 위에서 지정한 placeholder 문자열을 그대로 포함해.\n"
        "- 사용자가 제공한 고유명사, 숫자, 기한, 조건을 변경하지 마.\n"
        "- 결과는 실제로 AI에게 바로 입력할 수 있는 업무 요청문 한 개로 작성해.\n"
        "- 결과 앞뒤에 제목이나 설명을 추가하지 마.\n"
    )

_META_PREFIXES = (
    "[개선된 프롬프트]",
    "[재작성된 프롬프트]",
    "[설명]",
    "[분석]",
    "개선된 프롬프트:",
    "재작성된 프롬프트:",
    "개선 결과:",
    "다음은 개선된",
    "다음은 재작성된",
)

def _contains_meta_output(output: str) -> bool:
    normalized = output.strip()

    # Markdown 제목/목록 기호가 앞에 붙어도 검사할 수 있도록 제거한다.
    while normalized.startswith(("#", "*", "-", ">")):
        normalized = normalized[1:].lstrip()

    return any(
        normalized.startswith(prefix)
        for prefix in _META_PREFIXES
    )

def _required_placeholders(req: ImprovePromptRequest) -> list[str]:
    return [
        _PLACEHOLDERS[element]
        for element in req.prompt_rule.missing_elements
        if element in _PLACEHOLDERS
    ]

def _preserves_original_numbers(
    req: ImprovePromptRequest,
    output: str,
) -> bool:
    original_numbers = extract_numbers(req.text)
    output_numbers = extract_numbers(output)

    return original_numbers.issubset(output_numbers)

_CONSTRAINT_MARKERS = (
    "반드시",
    "꼭",
    "하지 마",
    "하지마",
    "제외",
    "포함하지",
    "금지",
)


def _preserves_explicit_constraints(
    req: ImprovePromptRequest,
    output: str,
) -> bool:
    clauses = re.split(r"[,\n.!?]+", req.text)

    constraints = [
        clause.strip()
        for clause in clauses
        if clause.strip()
        and any(
            marker in clause
            for marker in _CONSTRAINT_MARKERS
        )
    ]

    return all(
        constraint in output
        for constraint in constraints
    )

def _is_acceptable_output(
    req: ImprovePromptRequest,
    output: str,
) -> bool:
    if not output.strip():
        return False

    if _contains_meta_output(output):
        return False

    if not all(
        placeholder in output
        for placeholder in _required_placeholders(req)
    ):
        return False

    if not _preserves_original_numbers(req, output):
        return False

    return _preserves_explicit_constraints(req, output)



def _build_fallback_prompt(req: ImprovePromptRequest) -> str:
    parts: list[str] = []

    if req.prompt_rule.use_role and req.prompt_rule.role_hint:
        parts.append(f"너는 {req.prompt_rule.role_hint}다.")

    parts.append(req.text.strip())

    placeholders = _required_placeholders(req)

    if placeholders:
        parts.append(
            "다음 정보를 반영해 요청을 수행해: "
            + ", ".join(placeholders)
            + "."
        )

    if req.prompt_rule.use_positive_instruction:
        parts.append(
            "해야 할 행동과 원하는 결과를 명확하게 표현해."
        )

    return "\n".join(parts)


def improve(req: ImprovePromptRequest) -> ImprovePromptResponse:
    """HyperCLOVA X로 개선 프롬프트를 생성하고, 실패 시 deterministic fallback을 반환."""
    fallback_prompt = _build_fallback_prompt(req)

    try:
        tokenizer, model, device = load_hcx_runtime()

        prompt = _build_prompt(req)

        messages = [
            {
                "role": "system",
                "content": (
                    "너는 업무용 프롬프트를 재작성하는 도구다. "
                    "응답은 재작성된 실제 업무 요청문만 출력한다. "
                    "원문에 없는 사실은 만들지 않는다."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]

        inputs = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        )
        inputs = inputs.to(device)

        with hcx_lock(timeout=60):
            with torch.inference_mode():
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=512,
                    do_sample=False,
                    eos_token_id=tokenizer.eos_token_id,
                    stop_strings=["<|endofturn|>", "<|stop|>"],
                    tokenizer=tokenizer,
                )

        generated = outputs[0][inputs["input_ids"].shape[-1]:]
        improved_prompt = tokenizer.decode(
            generated,
            skip_special_tokens=True,
        ).strip()

        if not _is_acceptable_output(req, improved_prompt):
            logger.warning(
                "HCX prompt improvement fallback task_type=%s missing=%s",
                req.task_type,
                req.prompt_rule.missing_elements,
            )
            return ImprovePromptResponse(
                improved_prompt=fallback_prompt,
                used_fallback=True,
            )

        return ImprovePromptResponse(
            improved_prompt=improved_prompt,
            used_fallback=False,
        )

    except Exception:
        logger.exception(
            "HCX prompt improvement failed; using fallback "
            "task_type=%s missing=%s",
            req.task_type,
            req.prompt_rule.missing_elements,
        )

        return ImprovePromptResponse(
            improved_prompt=fallback_prompt,
            used_fallback=True,
        )