from __future__ import annotations

import re

import torch

from app.schemas.models import SummarizeTitleRequest, SummarizeTitleResponse
from app.services.hcx_runtime import hcx_lock, load_hcx_runtime


MAX_TITLE_LENGTH = 24


def _clean_title(value: str) -> str:
    title = (value or "").strip()

    if not title:
        return ""

    title = title.splitlines()[0].strip()

    prefixes = (
        "\uC81C\uBAA9:",
        "\uC81C\uBAA9\uFF1A",
        "\uB300\uD654 \uC81C\uBAA9:",
        "\uB300\uD654 \uC81C\uBAA9\uFF1A",
    )

    for prefix in prefixes:
        if title.startswith(prefix):
            title = title[len(prefix):].strip()
            break

    title = title.strip(" \"'`#*-")

    if len(title) > MAX_TITLE_LENGTH:
        title = title[:MAX_TITLE_LENGTH].rstrip()

    return title

def summarize(req: SummarizeTitleRequest) -> SummarizeTitleResponse:
    text = " ".join((req.text or "").split()).strip()

    if not text:
        return SummarizeTitleResponse(title="\uC0C8 \uB300\uD654")

    tokenizer, model, device = load_hcx_runtime()

    messages = [
        {
            "role": "system",
            "content": (
                "Create a concise Korean conversation title summarizing the user request. "
                "Return only the title, without quotes or explanations. "
                "Keep the title within 24 characters when possible."
            ),
        },
        {
            "role": "user",
            "content": text,
        },
    ]

    inputs = tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    ).to(device)

    with hcx_lock(timeout=120):
        with torch.inference_mode():
            outputs = model.generate(
                **inputs,
                max_new_tokens=32,
                do_sample=False,
                eos_token_id=tokenizer.eos_token_id,
                stop_strings=["<|endofturn|>", "<|stop|>"],
                tokenizer=tokenizer,
            )

    generated = outputs[0][inputs["input_ids"].shape[-1]:]

    title = _clean_title(
        tokenizer.decode(
            generated,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )
    )

    if not title:
        title = text[:MAX_TITLE_LENGTH].rstrip()

    return SummarizeTitleResponse(title=title)
