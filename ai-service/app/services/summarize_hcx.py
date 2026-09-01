from __future__ import annotations

import logging

import torch

from app.schemas.models import SummarizeTitleRequest, SummarizeTitleResponse
from app.services.hcx_runtime import hcx_lock, load_hcx_runtime


logger = logging.getLogger(__name__)


def _build_prompt(text: str) -> str:
    return (
        f"다음 문장을 대화 목록에 표시할 15자 이내의 짧은 제목으로 요약해줘.\n"
        f"설명 없이 제목만 출력해.\n\n"
        f"문장: {text}\n\n"
        f"제목:"
    )


def summarize_title(req: SummarizeTitleRequest) -> SummarizeTitleResponse:
    tokenizer, model, device = load_hcx_runtime()

    prompt = _build_prompt(req.text)

    messages = [
        {
            "role": "user",
            "content": prompt,
        }
    ]

    inputs = tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    )
    inputs = inputs.to(device)

    with hcx_lock():
        with torch.inference_mode():
            outputs = model.generate(
                **inputs,
                max_new_tokens=20,
                do_sample=False,
                eos_token_id=tokenizer.eos_token_id,
                stop_strings=[
                    "<|endofturn|>",
                    "<|stop|>",
                ],
                tokenizer=tokenizer,
            )

    generated = outputs[0][
        inputs["input_ids"].shape[-1]:
    ]

    title = tokenizer.decode(
        generated,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    ).strip()

    if len(title) > 30:
        title = title[:30]

    logger.info(
        "Title summary input=%r output=%r",
        req.text,
        title,
    )

    return SummarizeTitleResponse(title=title)
