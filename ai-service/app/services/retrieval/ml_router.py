from __future__ import annotations

import json
import re
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

from app.services.retrieval.query_intent import is_external_entity_lookup_query


APP = Path(__file__).resolve().parents[2]
TRAIN_PATH = APP / "data/rag/routing_train_242.json"


class MLRetrievalRouter:
    def __init__(self):
        self.model = Pipeline([
            (
                "tfidf",
                TfidfVectorizer(
                    analyzer="char",
                    ngram_range=(2, 5),
                    min_df=1,
                    sublinear_tf=True,
                ),
            ),
            (
                "svc",
                LinearSVC(
                    class_weight="balanced",
                    random_state=42,
                ),
            ),
        ])

    def fit(self, queries, labels):
        self.model.fit(queries, labels)
        return self

    def predict(self, query):
        return str(self.model.predict([query])[0])


def _is_restricted(query: str) -> bool:
    """
    타인의 고위험 개인정보 요청은 ML 판단보다 먼저 차단한다.
    일반적인 '내 프로필/내 조직정보' 요청은 여기서 차단하지 않는다.
    """
    text = query.strip().lower()

    other_person_markers = [
        "다른 직원",
        "다른 사용자",
        "다른 사람",
        "동료",
        "팀원",
        "직원들",
        "회사 사람",
    ]

    sensitive_markers = [
        "주민등록번호",
        "주민번호",
        "비밀번호",
        "카드번호",
        "결제번호",
        "계좌번호",
        "계좌 잔액",
        "은행 거래",
        "금융정보",
        "금융 내역",
        "신용정보",
        "인증 코드",
        "인증정보",
        "인증서 비밀번호",
        "신분증 번호",
        "집 주소",
    ]

    has_other_person = any(x in text for x in other_person_markers)
    has_sensitive_info = any(x in text for x in sensitive_markers)

    return has_other_person and has_sensitive_info


def _load_router() -> MLRetrievalRouter:
    rows = json.loads(TRAIN_PATH.read_text(encoding="utf-8"))

    router = MLRetrievalRouter()
    router.fit(
        [row["query"] for row in rows],
        [row["expected_route"] for row in rows],
    )

    return router


# 프로세스 시작 시 한 번만 학습한다.
_ROUTER = _load_router()


def _is_explicit_internal_rag(query: str) -> bool:
    """사용자가 내부/업로드 문서를 명시적으로 지칭하면 ML보다 우선한다."""
    text = query.strip().lower()

    internal_markers = [
        "내부 문서",
        "내부문서",
        "업로드한 문서",
        "업로드 문서",
        "업로드한 파일",
        "사내 문서",
        "회사 문서",
        "첨부 문서",
        "첨부파일",
    ]

    file_markers = [
        ".pdf",
        ".docx",
        ".doc",
        ".xlsx",
        ".xls",
        ".pptx",
        ".txt",
        ".md",
    ]

    return (
        any(marker in text for marker in internal_markers)
        or any(marker in text for marker in file_markers)
    )


def _is_likely_realtime_fact(query: str) -> bool:
    """
    2026-08-26: "어제 잠실 경기장의 날씨를 안내해주고 lg 트윈스의 승리여부를
    안내해줘." 같은 질의가 ML 라우터에서 no_retrieval로 잘못 분류되어
    웹검색이 아예 실행되지 않고, 모델이 완전히 지어낸 답("2023년 10월 5일
    현재, LG 트윈스는...")을 내놓는 사례가 확인됨.

    원인은 routing_train_242.json 학습 데이터가 날씨/환율/주가/일반 AI
    뉴스 카테고리 위주로만 구성돼 있고 스포츠 경기 결과 카테고리가 아예
    없었기 때문 - 242개 예시를 char n-gram + LinearSVC로 학습하는 구조라,
    학습 데이터에 없는 패턴은 우연히 가까운 다른 클래스로 분류돼버림.
    같은 취지로 확장 프로그램이 사용자 질문 뒤에 붙이는 톤/포맷 지시문
    ("3문단으로", "친근하게" 등) 유무에 따라서도 분류가 뒤집히는 게 확인돼,
    이런 취약한 경계에 기대지 않도록 결정적 규칙을 추가한다.

    학습 데이터를 보강하는 것과 별개로(방어적 이중 장치), _is_restricted/
    _is_explicit_internal_rag와 동일한 패턴으로 - 시간 표현(오늘/어제/지금/
    현재/최근 등)과 실시간성 사실 키워드(날씨/환율/주가/뉴스/경기 결과 등)가
    함께 있으면 ML 판단보다 먼저 검색 라우트로 보낸다.
    """
    text = query.strip().lower()

    time_markers = [
        "오늘", "어제", "그제", "그저께", "내일", "모레",
        "지금", "현재", "최근", "최신", "요즘", "방금",
    ]

    # "뉴스"/"속보"는 일부러 뺌 - 학습 데이터에 "최근/최신/요즘 OO 뉴스"류가
    # 이미 충분히 있어서(web_search) ML이 그 카테고리는 잘 맞히고 있었고,
    # 여기 넣으면 라벨만 external_or_realtime으로 바뀔 뿐 실제 동작(둘 다
    # search_web 호출)은 동일해서 불필요한 라벨 혼선만 생김.
    #
    # 2026-08-26: 부동산 관련 질의도 같은 부류의 문제가 있어서 추가함 -
    # "요즘 뜨는 부동산 정책 알려줘"가 internal_rag로 잘못 분류돼(학습
    # 데이터에 부동산 카테고리가 아예 없다 보니 우연히 "회사 정책"류 내부
    # 문서 질의와 비슷한 걸로 오분류됨) 사내 문서에서만 찾다가 아무것도
    # 못 찾고 끝나는 사례가 확인됨.
    fact_markers = [
        "날씨", "기온", "환율", "주가", "지수", "시세", "코스피", "코스닥",
        "비트코인",
        "경기", "경기결과", "경기 결과", "승리여부", "승패", "스코어",
        "이겼", "졌나요", "우승", "결승",
        "부동산", "아파트", "전세", "월세", "집값", "매매가", "청약",
    ]

    has_time = any(marker in text for marker in time_markers)
    has_fact = any(marker in text for marker in fact_markers)

    return has_time and has_fact


def _is_third_party_profile_query(query: str) -> bool:
    """
    2026-08-26: "이강인 소속과 프로필을 알려줘"가 웹검색을 전혀 안 하는
    user_context로 잘못 분류되어(로그인한 사용자 자신의 정보로 오인),
    HCX가 근거자료 없이 완전히 지어낸 답(예: "이강인은 PSG 소속,
    1996년생...")을 내놓은 사례가 재현 확인됨 - 출처 링크도 당연히
    안 붙었음(검색 자체를 안 했으므로).

    routing_train_242.json의 user_context 학습 예시(39개)는 "내 소속",
    "내 프로필의 부서" 처럼 "프로필"/"소속" 관련 예시가 전부 "내 "로
    시작하는 1인칭 소유 표현을 동반한다 - 예외 없음. 242개 char n-gram
    학습 데이터로는 "내 프로필" vs "이강인 프로필"을 의미상 구분하지
    못하고 "프로필"/"소속" 패턴 자체에 끌려가 오분류가 나므로, 1인칭
    소유 표현이 없는 프로필/소속/약력 질의는 ML 판단보다 먼저 실시간
    웹 검색(external_or_realtime)으로 보낸다.
    """
    text = query.strip().lower()

    profile_markers = ["프로필", "소속", "약력"]
    has_profile = any(marker in text for marker in profile_markers)

    # 단순 부분 문자열 매칭("제 " in text)은 "현제 이강인"(오타: 현재)처럼
    # 앞에 다른 한글 음절이 붙어 우연히 "제 "로 끝나는 단어에도 걸려서,
    # "내"/"제" 앞이 문장 시작이거나 공백/구두점일 때만(즉 실제로 독립된
    # 1인칭 대명사일 때만) 매치하도록 부정 전방탐색을 둔다.
    has_first_person = bool(
        re.search(r"(?<![가-힣])(?:내|제)\s", text)
        or any(marker in text for marker in ("저의", "나의", "제가", "내가"))
    )

    return has_profile and not has_first_person


# 2026-08-26: "침착맨에대해. 요약해줘. 최근 이슈와 관련해..."가 no_retrieval로
# 분류되어(patch 19의 위키 폴백은 search_web()이 아예 호출되지 않으니 무용지물
# 이었음) 웹검색 없이 HCX가 완전히 지어낸 인물 정보(가짜 데뷔 연도, 없는
# 앨범 등)로 답한 사례가 재현 확인됨. docker logs의 [Retrieval] 로그로
# route='no_retrieval'을 직접 확인한 뒤 원인을 찾음: routing_train_242.json의
# no_retrieval 학습 예시(43개)는 전부 "이 문장을/이 내용을/아래 글을 +
# 요약해줘/다듬어줘/번역해줘" 형태 - 즉 프롬프트에 이미 주어진 텍스트를
# 다듬는 요청뿐이고, "OO에 대해 요약해줘"처럼 "~에 대해/대하여/관해/관하여"
# 구문으로 특정 대상을 지칭하는 예시는 267개 학습 데이터 전체에 단 하나도
# 없음(직접 검증함) - 그래서 char n-gram 모델이 "~을 요약해줘"라는 표면적
# 겹침만 보고 이 구문 전체를 no_retrieval로 잘못 분류한 것으로 보인다.
# 학습 데이터에 아예 없는 구문이라 ML 예측이 사실상 정의되지 않은 영역이므로,
# 결정적 규칙으로 보정한다 - 단, 이 규칙은 ML이 no_retrieval 또는 user_context로
# 예측했을 때만 개입한다(다른 라벨을 예측했으면 그대로 둠 - 개입 범위를 최소화해서
# 이미 잘 맞히고 있는 다른 케이스에 영향이 없게 함).
#
# user_context도 개입 대상에 포함한 이유: 실제 테스트 중 "리센느에 대하여
# 소개해줘"가 no_retrieval이 아니라 user_context로 잘못 예측되는 사례가
# 발견됨(로그인한 사용자 자신의 정보로 오인) - _is_third_party_profile_query와
# 동일한 원인이지만 "프로필"/"소속"/"약력" 마커가 없어 그 필터에는 안 걸림.
# has_first_person 배제 조건이 이미 "내 프로필에 대해 알려줘"류 진짜 자기참조
# 질의는 걸러내므로, user_context를 개입 대상에 추가해도 회귀 위험은 없다.
_ABOUT_SUBJECT_RE = re.compile(r"에\s*(?:대|관)(?:해|하여)")

_SUMMARY_ASK_MARKERS = ["요약해", "알려", "설명해", "소개해", "정리해"]

# "우리 회사 정책에 대해 알려줘"처럼 실제로는 내부 문서를 찾아야 하는 질의까지
# 외부 검색으로 잘못 보내지 않도록, 내부/자기참조성 주제 마커가 있으면 이
# 보정을 적용하지 않는다.
_INTERNAL_TOPIC_MARKERS = [
    "내부", "사내", "회사", "우리 팀", "우리팀", "부서", "정책", "규정",
    "문서", "파일", "보고서",
]


def _is_external_subject_summary_query(query: str) -> bool:
    text = query.strip().lower()

    has_about = bool(_ABOUT_SUBJECT_RE.search(text))
    has_ask = any(marker in text for marker in _SUMMARY_ASK_MARKERS)

    has_first_person = bool(
        re.search(r"(?<![가-힣])(?:내|제)\s", text)
        or any(marker in text for marker in ("저의", "나의", "제가", "내가"))
    )

    has_internal_topic = any(marker in text for marker in _INTERNAL_TOPIC_MARKERS)

    return has_about and has_ask and not has_first_person and not has_internal_topic


_COMPANY_INTERNAL_SCOPE_MARKERS = (
    "우리회사",
    "우리 회사",
    "사내",
    "내부",
    "우리팀",
    "우리 팀",
)

_INTERNAL_ARTIFACT_MARKERS = (
    "보고서",
    "양식",
    "템플릿",
    "규정",
    "정책",
    "지침",
    "가이드",
    "매뉴얼",
    "문서",
    "파일",
)


def _is_company_internal_artifact_query(query: str) -> bool:
    text = str(query or "").strip().lower()

    if not text:
        return False

    compact = "".join(text.split())

    has_scope = any(
        "".join(marker.split()) in compact
        for marker in _COMPANY_INTERNAL_SCOPE_MARKERS
    )

    has_artifact = any(
        marker in text
        for marker in _INTERNAL_ARTIFACT_MARKERS
    )

    return has_scope and has_artifact


def resolve_strong_retrieval_route(query: str) -> str | None:
    """
    ML 예측과 무관하게 retrieval source가 명확한 질의를 먼저 판정한다.

    이 함수의 반환값은 confidence가 낮은 ActionClassifier 결과보다 우선할 수 있다.
    명백한 문서 참조, 실시간 사실, 외부 entity/profile 같은 경우만 다룬다.
    """
    if _is_restricted(query):
        return "not_rag_or_restricted"

    if (
        _is_explicit_internal_rag(query)
        or _is_company_internal_artifact_query(query)
    ):
        return "internal_rag"

    if is_external_entity_lookup_query(query):
        return "external_or_realtime"

    if _is_likely_realtime_fact(query):
        return "external_or_realtime"

    if _is_third_party_profile_query(query):
        return "external_or_realtime"

    # 2026-08-31: PR #207(action-aware retrieval 리팩터)이 라우팅 판단을
    # classify_ml_retrieval_route(ML SVC + 이 함수의 결정적 규칙들)에서
    # resolve_action(TF-IDF/LogisticRegression 기반 ActionClassifier,
    # confidence < 0.25면 검색 자체를 포기)으로 옮기면서, 바로 아래
    # _is_external_subject_summary_query 체크(2026-08-26에 "리센느에 대하여
    # 소개해줘" 오분류를 고치려고 추가했던 규칙)를 이 함수로 옮기는 걸
    # 누락했다. 그 결과 "고마워! 리센느 걸그룹에 대해 알려줘." 같은 질의가
    # 실제 운영에서 재현됨: action_train.json에 "고마워"를 포함하는 학습
    # 예시가 "고마워"(CHAT) 단 1건뿐이라, 앞에 "고마워!"가 붙은 WEB_FACT성
    # 질의는 char n-gram 특성이 CHAT 쪽으로 끌려가 confidence가 0.239로
    # 떨어져 reason='low_confidence_needs_strong_signal'로 검색을 완전히
    # 건너뛰고, HCX가 근거 없이 리센느 멤버/NFT 사업 등을 지어내는 답을
    # 냈다(sources=() - "출처 더보기"가 안 뜬 이유). "OO에 대해 알려줘/
    # 소개해줘/설명해줘/요약해줘/정리해줘" 패턴은 (내부 문서/자기참조 주제가
    # 아닌 한) ActionClassifier의 confidence와 무관하게 항상 실시간 검색으로
    # 보내야 하므로, 결정적 규칙으로 다시 여기에 포함시킨다.
    if _is_external_subject_summary_query(query):
        return "external_or_realtime"

    return None


def classify_ml_retrieval_route(query: str) -> str:
    strong_route = resolve_strong_retrieval_route(query)

    if strong_route is not None:
        return strong_route

    predicted = _ROUTER.predict(query)

    if (
        predicted in ("no_retrieval", "user_context")
        and _is_external_subject_summary_query(query)
    ):
        return "external_or_realtime"

    return predicted
