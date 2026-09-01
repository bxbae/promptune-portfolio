"""AI 서비스 라우터 — 각 파이프라인 단계를 엔드포인트로 노출."""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from app.services.validation.validator import validate_response
from app.services.validation.evidence_validator import validate_evidence_identity
from app.schemas.models import (
    DiagnoseRequest,
    DiagnoseResponse,
    SuggestRequest,
    SuggestResponse,
    SafetyRequest,
    SafetyResponse,
    RetrievalRouteRequest,
    RetrievalRouteResponse,
    RetrievalExecuteRequest,
    RetrievalExecuteResponse,
    RetrieveRequest,
    RetrieveResponse,
    GenerateRequest,
    GenerateResponse,
    ValidateRequest,
    ValidateResponse,
    SummarizeTitleRequest,
    SummarizeTitleResponse,
    PromptRuleRequest,
    PromptRuleResponse,
    ImprovePromptRequest,
    ImprovePromptResponse,
)

from app.services.retrieval.ml_router import classify_ml_retrieval_route
from app.services.retrieval.retrieval_orchestrator import execute_retrieval
from app.services.retrieval import document_indexer, rag_retriever

from app.services import (
    diagnose_real,
    generate_hcx,
    improve_hcx,
    prompt_rule,
    safety_rule,
    suggest_hcx,
    title_summary_hcx,
)

router = APIRouter()


@router.post(
    "/diagnose",
    response_model=DiagnoseResponse,
    tags=["5.통합진단"],
)
def diagnose(req: DiagnoseRequest):
    """8요소 누락 + 오탈자 + 업무유형 판정."""
    return diagnose_real.diagnose(req)

@router.post(
    "/prompt-rule",
    response_model=PromptRuleResponse,
    tags=["Prompt Rule"],
)
def apply_prompt_rule(req: PromptRuleRequest):
    """V6 진단 결과와 사용자 Preference를 개선 전략으로 변환."""
    return prompt_rule.apply_prompt_rule(req)

@router.post(
    "/improve-prompt",
    response_model=ImprovePromptResponse,
    tags=["Prompt Improvement"],
)
def improve_prompt(req: ImprovePromptRequest):
    """Phase 2-C: Prompt Rule을 반영해 개선 프롬프트를 생성."""
    return improve_hcx.improve(req)

@router.post(
    "/suggest",
    response_model=SuggestResponse,
    tags=["7.추천생성"],
)
def suggest(req: SuggestRequest):
    return suggest_hcx.suggest(req)


@router.post(
    "/safety-check",
    response_model=SafetyResponse,
    tags=["8.안전검사"],
)
def safety_check(req: SafetyRequest):
    return safety_rule.safety_check(req)



@router.post(
    "/retrieval-route",
    response_model=RetrievalRouteResponse,
    tags=["12.Retrieval Route"],
)
def retrieval_route(req: RetrievalRouteRequest):
    return RetrievalRouteResponse(
        route=classify_ml_retrieval_route(req.query)
    )



@router.post(
    "/retrieval-execute",
    response_model=RetrievalExecuteResponse,
    tags=["12.Retrieval Execute"],
)
def retrieval_execute(req: RetrievalExecuteRequest):
    try:
        return execute_retrieval(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        print(f"[Retrieval] execute failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Retrieval 실행 중 오류가 발생했습니다.",
        ) from exc


@router.post(
    "/retrieve",
    response_model=RetrieveResponse,
    tags=["13.내부검색"],
)
def retrieve(req: RetrieveRequest):
    return rag_retriever.retrieve(req)

@router.post(
    "/generate",
    response_model=GenerateResponse,
    tags=["14.답변생성"],
)
def generate(req: GenerateRequest):
    web_results = [item.model_dump() for item in req.web_results]
    used_web_search = bool(web_results)

    # 동시에 여러 요청이 겹쳐 HCX lock을 제한시간 안에 얻지 못하면
    # 명확한 503으로 반환한다.
    from app.services.hcx_runtime import HcxBusyError

    try:
        return generate_hcx.generate(
            req,
            web_results=web_results,
            used_web_search=used_web_search,
        )
    except HcxBusyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@router.post(
    "/validate",
    response_model=ValidateResponse,
    tags=["15.최종 검증"],
)
def validate(req: ValidateRequest):

    result = validate_response(
        original=req.original,
        generated=req.generated,
    )

    evidence_issues = validate_evidence_identity(
        req.generated,
        documents=[
            item.model_dump()
            for item in req.documents
        ],
        web_results=[
            item.model_dump()
            for item in req.web_results
        ],
    )

    issues = [
        *result.issues,
        *evidence_issues,
    ]

    facts_preserved = (
        result.facts_preserved
        and not evidence_issues
    )

    passed = (
        result.passed
        and not evidence_issues
    )

    print(
        f"[Validate] passed={passed!r} "
        f"rule_ok={result.rule_ok!r} "
        f"semantic_ok={result.semantic_ok!r} "
        f"semantic_score={result.semantic_score!r} "
        f"facts_preserved={facts_preserved!r} "
        f"issues={issues!r} "
        f"original={req.original[:300]!r} "
        f"generated={req.generated[:300]!r}"
    )

    return ValidateResponse(
        passed=passed,
        rule_ok=result.rule_ok,
        semantic_ok=result.semantic_ok,
        semantic_score=result.semantic_score,
        facts_preserved=facts_preserved,
        issues=issues,
    )


@router.post(
    "/summarize-title",
    response_model=SummarizeTitleResponse,
    tags=["대화 제목 요약"],
)
def summarize_title(req: SummarizeTitleRequest):
    """Generate a short conversation title using the shared HCX runtime."""
    return title_summary_hcx.summarize(req)

@router.post(
    "/index-document",
    tags=["13.내부검색"],
)
async def index_document(
    document_id: int = Form(...),
    owner_user_id: int = Form(...),
    file_type: str | None = Form(None),
    file: UploadFile = File(...),
):
    try:
        file_bytes = await file.read()

        result = document_indexer.index_document(
            document_id=document_id,
            owner_user_id=owner_user_id,
            file_bytes=file_bytes,
            filename=file.filename,
            file_type=file_type,
        )

        return result

    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        print(f"[INDEX] document indexing failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail="문서 인덱싱에 실패했습니다.",
        ) from exc
