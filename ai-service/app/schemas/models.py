"""
AI 서비스 입출력 스키마 (팀원 교체의 '계약서').

mock이든 실제 구현이든 이 형식만 지키면 파이프라인 나머지는 안 건드려도 된다.
흐름도의 각 박스(보라=기능)가 여기 요청/응답으로 대응된다.
"""
from pydantic import BaseModel, Field
from typing import Literal

# 8요소 (흐름도 "8요소 누락 진단")
ELEMENTS = ["TASK", "AUDIENCE", "CONTEXT", "FORMAT", "TONE", "LENGTH", "CONSTRAINT", "EXAMPLE"]

# 업무유형 7종 (흐름도 "업무 유형 판단")
TaskType = Literal[
    "email", "report", "report_internal",
    "notice", "notice_internal", "support", "application",
]


# ---------- 5번: 통합 진단 ----------
class DiagnoseRequest(BaseModel):
    text: str = Field(..., description="사용자 원문 프롬프트")


class Typo(BaseModel):
    span: str          # 오탈자 부분
    suggest: str       # 교정 제안


class DiagnoseResponse(BaseModel):
    # 8요소 누락 (1=누락/보완필요, 0=충분)
    missing: dict[str, int]
    task_type: TaskType
    typos: list[Typo]
    needs_internal_docs: bool   # 흐름도 분기: _internal 또는 application이면 True

# ---------- Phase 2-B: Prompt Rule ----------
class PreferenceInput(BaseModel):
    speed: Literal["fast", "accurate"]
    detail: Literal["brief", "detailed"]
    preserve: Literal["keep", "improve"]


class PromptRuleRequest(BaseModel):
    text: str
    missing: dict[str, int]
    task_type: TaskType
    preference: PreferenceInput


class PromptRuleResponse(BaseModel):
    missing_elements: list[str]
    use_role: bool
    role_hint: str | None = None
    decompose_task: bool
    use_positive_instruction: bool
    use_few_shot: bool

# ---------- Phase 2-C: 개선 프롬프트 생성 ----------
class ImprovePromptRequest(BaseModel):
    text: str
    task_type: TaskType
    preference: PreferenceInput
    prompt_rule: PromptRuleResponse


class ImprovePromptResponse(BaseModel):
    improved_prompt: str
    used_fallback: bool = False


# ---------- 7번: 추천문구 생성 ----------
class SuggestRequest(BaseModel):
    text: str
    target_elements: list[str]   # 6번에서 선정된 1~3개 요소
    context: str | None = None   # 업무 맥락, 없으면 원문만 사용


class SuggestionAnchor(BaseModel):
    sentence_index: int
    char_offset: int


class Suggestion(BaseModel):
    element: str
    primary: str
    alternatives: list[str]
    anchor: SuggestionAnchor


class SuggestResponse(BaseModel):
    suggestions: list[Suggestion]


# ---------- 8번: 추천문구 안전검사 ----------
class SafetyRequest(BaseModel):
    original: str
    suggestion: str


class SafetyResponse(BaseModel):
    safe: bool
    reason: str                  # 안전하지 않으면 이유


# ---------- 12번: Retrieval Route 판단 ----------
RetrievalRoute = Literal[
    "internal_rag",
    "web_search",
    "external_or_realtime",
    "user_context",
    "no_retrieval",
    "not_rag_or_restricted",
]


class RetrievalRouteRequest(BaseModel):
    query: str


class RetrievalRouteResponse(BaseModel):
    route: RetrievalRoute


# ---------- 13번: 내부문서 검색 (RAG) ----------
class RetrieveRequest(BaseModel):
    query: str
    owner_user_id: int
    top_k: int = 3
    # 2026-08-26: 이 메시지에 사용자가 직접 첨부한 문서 id 목록. 채워져 있으면
    # query와의 의미 유사도 검색 대신 이 문서들의 내용을 그대로 가져온다 -
    # "DOCX 첨부하고 '이게 무슨 내용이야?' 라고 물으면 이전 대화 내용으로
    # 엉뚱하게 답하는" 문제의 원인이 여기 있었음(문서 id가 retrieval까지
    # 전달된 적이 없어서 매번 순수 의미 유사도 검색만 하고 있었음).
    document_ids: list[int] = Field(default_factory=list)


DocumentType = Literal[
    "POLICY",
    "TEMPLATE",
    "GUIDE",
    "REPORT",
    "OTHER",
]


class Document(BaseModel):
    document_id: int | None = None
    chunk_id: int | None = None
    chunk_index: int | None = None

    title: str
    document_type: DocumentType = "OTHER"
    description: str | None = None

    content: str
    score: float


class RetrieveResponse(BaseModel):
    documents: list[Document]


class WebSearchResult(BaseModel):
    title: str = ""
    url: str = ""
    content: str = ""
    score: float = 0.0


# ---------- 14번: 최종 답변 생성 ----------
class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class GenerateRequest(BaseModel):
    prompt: str
    task_type: TaskType
    documents: list[Document] = Field(default_factory=list)
    web_results: list[WebSearchResult] = Field(default_factory=list)
    user_context: dict[str, str] = Field(default_factory=dict)
    preference: dict[str, str] = Field(default_factory=dict)
    history: list[ConversationMessage] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    result: str
    used_web_search: bool


# ---------- 15번: 최종 검증 ----------
class ValidateRequest(BaseModel):
    original: str
    generated: str
    documents: list[Document] = Field(default_factory=list)
    web_results: list[WebSearchResult] = Field(default_factory=list)


class ValidateResponse(BaseModel):
    passed: bool
    rule_ok: bool
    semantic_ok: bool
    semantic_score: float
    facts_preserved: bool
    issues: list[str]

# ---------- 대화 제목 요약 ----------

class SummarizeTitleRequest(BaseModel):
    text: str


class SummarizeTitleResponse(BaseModel):
    title: str

# ---------- 12-1번: Retrieval 실행 ----------

class RetrievalExecuteRequest(BaseModel):
    query: str
    owner_user_id: int | None = None
    top_k: int = 3
    history: list[ConversationMessage] = Field(default_factory=list)
    # Action routing에서 현재 사용자 본인 여부를 판별하기 위한 최소 identity.
    # 생성용 전체 user_context와 분리하며 name/email/displayName 정도만 전달한다.
    routing_user_context: dict[str, str] = Field(default_factory=dict)
    # 사용자가 명시적으로 Web 검색을 요청한 경우.
    # document_ids와 동시에 주어질 수 있으며 이 경우 INTERNAL + WEB을 모두 실행한다.
    use_web_search: bool = False
    # 2026-08-26: RetrieveRequest.document_ids와 동일한 목적 - 이 메시지에
    # 직접 첨부된 문서가 있으면 라우팅 판단(ML)보다 우선해서 internal_rag로
    # 보내고, 그 문서들의 내용을 그대로 가져온다.
    document_ids: list[int] = Field(default_factory=list)


class RetrievalExecuteResponse(BaseModel):
    route: RetrievalRoute
    documents: list[Document] = Field(default_factory=list)
    web_results: list[WebSearchResult] = Field(default_factory=list)
    used_internal_rag: bool = False
    used_web_search: bool = False
