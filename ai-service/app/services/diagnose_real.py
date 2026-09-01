"""
5번 통합 진단 실제 구현.

역할:
- KcELECTRA: 8요소 누락 여부 판단
- Bareun + Rule Engine: 맞춤법/오탈자 진단
- Rule Engine: task_type, 내부문서 필요 여부 판단

KcELECTRA는 Promptune의 8개 missing label만 담당한다.

Label order:
0 = TASK
1 = AUDIENCE
2 = CONTEXT
3 = FORMAT
4 = TONE
5 = LENGTH
6 = CONSTRAINT
7 = EXAMPLE
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app.schemas.models import (
    DiagnoseRequest,
    DiagnoseResponse,
    ELEMENTS,
)
from app.services.diagnose_rules import (
    detect_task_type,
    detect_typos,
    needs_internal_docs,
    should_force_missing_audience,
)

from app.services.spellcheck_bareun import check_spelling_hybrid


# ------------------------------------------------------------------
# 환경 설정
# ------------------------------------------------------------------

MODEL_PATH = Path(
    os.getenv(
        "AI_DIAGNOSIS_MODEL_PATH",
        "ai-service/models/prompt-diagnosis",
    )
)

MAX_LENGTH = int(
    os.getenv(
        "AI_DIAGNOSIS_MAX_LENGTH",
        "128",
    )
)

DEVICE_SETTING = os.getenv(
    "AI_DIAGNOSIS_DEVICE",
    "cpu",
).lower()

USE_REAL_SPELLCHECK = (
    os.getenv("USE_REAL_SPELLCHECK", "false").lower() == "true"
)


# ------------------------------------------------------------------
# 모델 캐시
#
# 요청이 올 때마다 417MB 모델을 다시 읽지 않도록
# 최초 추론 시 한 번만 로딩한다.
# ------------------------------------------------------------------

_tokenizer = None
_model = None
_thresholds: dict[str, float] | None = None
_device: torch.device | None = None


def _resolve_device() -> torch.device:
    """
    초기 서비스 통합에서는 CPU 사용을 기본값으로 한다.

    AI_DIAGNOSIS_DEVICE=cuda 로 설정했고
    CUDA를 실제 사용할 수 있는 경우에만 GPU를 사용한다.
    """

    if DEVICE_SETTING == "cuda":
        if torch.cuda.is_available():
            return torch.device("cuda")

        raise RuntimeError(
            "AI_DIAGNOSIS_DEVICE=cuda 이지만 CUDA를 사용할 수 없습니다."
        )

    return torch.device("cpu")


def _load_thresholds() -> dict[str, float]:
    """
    학습/Validation에서 결정한 라벨별 threshold를 읽는다.
    """

    threshold_path = MODEL_PATH / "thresholds.json"

    if not threshold_path.exists():
        raise FileNotFoundError(
            f"thresholds.json을 찾을 수 없습니다: {threshold_path}"
        )

    with threshold_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        raw_thresholds = json.load(file)

    thresholds: dict[str, float] = {}

    for element in ELEMENTS:
        key = element.lower()

        if key not in raw_thresholds:
            raise ValueError(
                f"thresholds.json에 '{key}' 값이 없습니다."
            )

        value = float(raw_thresholds[key])

        if not 0.0 <= value <= 1.0:
            raise ValueError(
                f"{key} threshold가 0~1 범위를 벗어났습니다: {value}"
            )

        thresholds[key] = value

    return thresholds


def _ensure_model_loaded() -> None:
    """
    모델/tokenizer/threshold를 최초 한 번만 로드한다.
    """

    global _tokenizer
    global _model
    global _thresholds
    global _device

    if (
        _tokenizer is not None
        and _model is not None
        and _thresholds is not None
        and _device is not None
    ):
        return

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"KcELECTRA 모델 경로를 찾을 수 없습니다: {MODEL_PATH}"
        )

    _device = _resolve_device()

    _tokenizer = AutoTokenizer.from_pretrained(
        MODEL_PATH,
        local_files_only=True,
    )

    # Load model.safetensors explicitly as real CPU tensors.
    # This avoids parameters remaining on the meta device.
    # The model is moved to the resolved device after state loading.
    from transformers import AutoConfig
    from safetensors.torch import load_file

    config = AutoConfig.from_pretrained(
        MODEL_PATH,
        local_files_only=True,
    )

    _model = AutoModelForSequenceClassification.from_config(config)

    state_dict = load_file(
        str(MODEL_PATH / "model.safetensors"),
        device="cpu",
    )

    _model.load_state_dict(
        state_dict,
        strict=True,
    )

    _model.to(_device)
    _model.eval()

    _thresholds = _load_thresholds()


def predict_probabilities(text: str) -> dict[str, float]:
    """
    사용자 프롬프트에 대한 8개 누락 확률을 반환한다.

    예:
    {
        "TASK": 0.52,
        "AUDIENCE": 0.31,
        ...
    }
    """

    _ensure_model_loaded()

    assert _tokenizer is not None
    assert _model is not None
    assert _device is not None

    encoded = _tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        max_length=MAX_LENGTH,
    )

    encoded = {
        key: value.to(_device)
        for key, value in encoded.items()
    }

    with torch.inference_mode():
        outputs = _model(**encoded)

    logits = outputs.logits

    if logits.shape[-1] != len(ELEMENTS):
        raise RuntimeError(
            "KcELECTRA 출력 라벨 수가 API 라벨 수와 다릅니다. "
            f"model={logits.shape[-1]}, api={len(ELEMENTS)}"
        )

    probabilities = torch.sigmoid(logits)[0].cpu().tolist()

    return {
        element: float(probability)
        for element, probability in zip(
            ELEMENTS,
            probabilities,
        )
    }


def predict_missing(text: str) -> dict[str, int]:
    """
    확률에 라벨별 threshold를 적용하여
    1=보완 필요, 0=충분 으로 변환한다.
    """

    _ensure_model_loaded()

    assert _thresholds is not None

    probabilities = predict_probabilities(text)

    missing: dict[str, int] = {}

    for element in ELEMENTS:
        probability = probabilities[element]
        threshold = _thresholds[element.lower()]

        missing[element] = int(
            probability >= threshold
        )

    return missing

def predict_missing_with_rules(text: str) -> dict[str, int]:
    """
    KcELECTRA의 8요소 누락 판정에
    고신뢰 진단 규칙을 적용한 최종 missing 결과를 반환한다.
    """

    missing = predict_missing(text)
    task_type = detect_task_type(text)

    if should_force_missing_audience(text, task_type):
        missing["AUDIENCE"] = 1

    return missing

def diagnose(req: DiagnoseRequest) -> DiagnoseResponse:
    """
    실제 5번 통합 진단.

    - missing: KcELECTRA
    - task_type: Rule Engine
    - typos: Bareun API + Rule Engine
    - needs_internal_docs: Rule Engine
    """

    text = req.text

    missing = predict_missing_with_rules(text)

    task_type = detect_task_type(text)

    if USE_REAL_SPELLCHECK:
        typos = check_spelling_hybrid(text)
    else:
        typos = detect_typos(text)
    internal_docs = needs_internal_docs(task_type)

    return DiagnoseResponse(
        missing=missing,
        task_type=task_type,
        typos=typos,
        needs_internal_docs=internal_docs,
    )
