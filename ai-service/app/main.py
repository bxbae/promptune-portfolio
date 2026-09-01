"""
PrompTune AI Service (FastAPI).

단계 5, 7, 8, 13, 14, 15를 담당한다.
AI 파이프라인은 실제 구현만 사용하며,
맞춤법 검사(Bareun)는 환경 설정으로 선택적으로 활성화한다.
"""

import os

import torch
from fastapi import FastAPI

from app.routers import documents, pipeline

USE_REAL_SPELLCHECK = os.getenv("USE_REAL_SPELLCHECK", "false").lower() == "true"

app = FastAPI(
    title="PrompTune AI Service",
    description="8요소 진단·추천·생성·검증 AI Service",
    version="0.2.0",
)

app.include_router(
    pipeline.router,
    prefix="/api/ai",
)

app.include_router(
    documents.router,
    prefix="/api/ai",
)


@app.get("/health", tags=["시스템"])
def health():
    return {
        "status": "ok",
    }


@app.get("/runtime-status")
def runtime_status():
    if USE_REAL_SPELLCHECK:
        stage5_status = "real(KcELECTRA + Bareun + Rule)"
    else:
        stage5_status = "real(KcELECTRA + Rule)"

    stage7_status = "real(HyperCLOVAX-SEED-Vision-Instruct-3B)"

    return {
        "use_real_models": True,
        "use_real_diagnosis": True,
        "use_real_spellcheck": USE_REAL_SPELLCHECK,
        "use_real_suggestion": True,
        "stages": {
            "5_diagnose": stage5_status,
            "7_suggest": stage7_status,
            "8_safety": "real(규칙)",
            "13_retrieve": "real(BGE-M3 + pgvector)",
            "14_generate": "real(HyperCLOVAX-SEED-Vision-Instruct-3B)",
            "15_validate": "real(Rule Validator + optional semantic telemetry)",
        },
        "runtime": {
            "cuda_available": torch.cuda.is_available(),
            "cuda_device_count": torch.cuda.device_count(),
            "hcx_device_requested": os.getenv("HF_HCX_DEVICE", "auto"),
            "hcx_dtype_requested": os.getenv("HF_HCX_DTYPE", "auto"),
            "bge_device_requested": os.getenv("BGE_M3_DEVICE", "auto"),
            "bge_fp16_requested": os.getenv("BGE_M3_USE_FP16", "auto"),
        },
    }
