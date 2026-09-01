import sys
import types
import unittest
from unittest.mock import patch

# 2026-08-26: retrieval_orchestrator -> conversation_context가 모듈 최상단에서
# `import torch`를 하는데(실제 HCX 추론은 지연 로딩이라 무거운 모델 자체는
# 여기서 안 올라옴), 이 테스트 샌드박스에는 torch가 설치돼 있지 않다
# (ai-service Docker 이미지에서는 transformers/FlagEmbedding의 전이
# 의존성으로 항상 설치되어 있음 - requirements.txt 참고). import 자체만
# 통과시키면 되므로 최소한의 더미 모듈로 대체한다.
#
# 2026-08-26(수정): 이 스텁을 module import 시점에 sys.modules에 영구로
# 남기면, `python -m unittest discover`로 여러 테스트 파일을 한 프로세스에서
# 돌릴 때 알파벳순으로 뒤에 실행되는 다른 파일(예: test_improve_hcx.py)이
# 진짜 torch 대신 이 가짜 스텁을 넘겨받아서, 원래는 "torch 없음"으로 깔끔하게
# import 에러가 나야 할 테스트가 스텁의 부족한 기능(torch.tensor 등 없음)
# 때문에 엉뚱하게 실패하는 부작용이 실제로 확인됨(test_generate_hcx_system_prompt.py
# 작성 중 발견). setUpModule/tearDownModule로 이 파일이 실행되는 동안만
# 스텁을 걸고, 끝나면 반드시 원상복구한다.
_installed_torch_stub = False
_installed_hcx_runtime_stub = False

ConversationMessage = None
RetrievalExecuteRequest = None
RetrieveResponse = None
Document = None
execute_retrieval = None


def setUpModule():
    global _installed_torch_stub, _installed_hcx_runtime_stub
    global ConversationMessage, RetrievalExecuteRequest, RetrieveResponse, Document
    global execute_retrieval

    if "torch" not in sys.modules:
        import contextlib

        torch_stub = types.ModuleType("torch")
        torch_stub.inference_mode = contextlib.nullcontext

        class _StubTensor:  # scipy/sklearn의 array-api 호환 체크가 torch.Tensor를
            pass            # getattr/issubclass로 조회하길래 최소한만 채워둠.

        torch_stub.Tensor = _StubTensor
        sys.modules["torch"] = torch_stub
        _installed_torch_stub = True

    # conversation_context가 실제로 필요로 하는 건 hcx_lock/load_hcx_runtime
    # "함수가 존재한다"는 것뿐 - 이 테스트는 두 함수 다 호출되지 않는 경로만
    # 다루므로(document_ids가 있거나, 대화 이력 자체가 없거나 짧은 케이스),
    # transformers(및 그게 필요로 하는 실제 torch 런타임) 전체를 로드할 필요가
    # 없다. hcx_runtime 모듈 자체를 더미로 대체해서 무거운 import 체인을 끊는다.
    if "app.services.hcx_runtime" not in sys.modules:
        import contextlib

        hcx_runtime_stub = types.ModuleType("app.services.hcx_runtime")

        def _unexpected_hcx_call(*args, **kwargs):
            raise AssertionError(
                "이 테스트 경로에서는 HCX 런타임이 호출되면 안 됨"
            )

        hcx_runtime_stub.hcx_lock = lambda timeout=None: contextlib.nullcontext()
        hcx_runtime_stub.load_hcx_runtime = _unexpected_hcx_call
        sys.modules["app.services.hcx_runtime"] = hcx_runtime_stub
        _installed_hcx_runtime_stub = True

    from app.schemas.models import (
        ConversationMessage as _ConversationMessage,
        RetrievalExecuteRequest as _RetrievalExecuteRequest,
        RetrieveResponse as _RetrieveResponse,
        Document as _Document,
    )
    from app.services.retrieval.retrieval_orchestrator import (
        execute_retrieval as _execute_retrieval,
    )

    ConversationMessage = _ConversationMessage
    RetrievalExecuteRequest = _RetrievalExecuteRequest
    RetrieveResponse = _RetrieveResponse
    Document = _Document
    execute_retrieval = _execute_retrieval


def tearDownModule():
    # 이 파일이 실제로 설치한 스텁만 제거한다 (이미 다른 곳에서 진짜 torch가
    # 로드돼 있던 경우는 절대 건드리지 않음).
    sys.modules.pop("app.services.retrieval.retrieval_orchestrator", None)
    sys.modules.pop("app.services.retrieval.conversation_context", None)

    if _installed_torch_stub:
        sys.modules.pop("torch", None)

    if _installed_hcx_runtime_stub:
        sys.modules.pop("app.services.hcx_runtime", None)


class DocumentIdsRoutingTest(unittest.TestCase):
    """
    2026-08-26: DOCX를 첨부하고 "이게 무슨 내용인지 알려줘" 처럼 질문
    자체에는 "문서"/"파일" 같은 키워드가 전혀 없는 메시지를 보내면, ML
    라우터가 no_retrieval로 잘못 분류해서 첨부 문서 내용이 답변에 전혀
    반영되지 않고, 대신 이전 대화 주제가 그대로 튀어나오는 문제가 있었음.

    document_ids가 있으면 질의 텍스트/대화 맥락 override와 무관하게 항상
    internal_rag로 보내지고, 그 문서 id들이 실제 RetrieveRequest까지
    전달되는지 고정한다.
    """

    def test_document_ids_forces_internal_rag_even_without_doc_keywords(self):
        req = RetrievalExecuteRequest(
            query="이게 무슨 내용인지 알려줘",
            owner_user_id=1,
            top_k=3,
            history=[],
            document_ids=[42],
        )

        captured = {}

        def fake_overview(owner_user_id, document_ids):
            captured["owner_user_id"] = owner_user_id
            captured["document_ids"] = document_ids
            return RetrieveResponse(
                documents=[
                    Document(
                        document_id=42,
                        chunk_id=1,
                        chunk_index=0,
                        title="차승연_프로젝트_이력서_초안.docx",
                        document_type="OTHER",
                        description=None,
                        content="실제 문서 본문...",
                        score=1.0,
                    )
                ]
            )

        with patch(
            "app.services.retrieval.retrieval_orchestrator.retrieve_document_overview",
            side_effect=fake_overview,
        ):
            result = execute_retrieval(req)

        self.assertEqual(result.route, "internal_rag")
        self.assertTrue(result.used_internal_rag)
        self.assertEqual(len(result.documents), 1)
        self.assertEqual(result.documents[0].document_id, 42)
        self.assertEqual(captured["owner_user_id"], 1)
        self.assertEqual(captured["document_ids"], [42])

    def test_document_ids_overrides_conversation_route_override(self):
        req = RetrievalExecuteRequest(
            query="그거 다시 설명해줘",
            owner_user_id=1,
            top_k=3,
            history=[
                ConversationMessage(role="user", content="침착맨 몇살이야?"),
                ConversationMessage(role="assistant", content="확인이 어렵습니다."),
            ],
            document_ids=[7],
        )

        captured = {}

        def fake_retrieve(retrieve_req):
            captured["req"] = retrieve_req
            return RetrieveResponse(documents=[])

        with patch(
            "app.services.retrieval.retrieval_orchestrator.retrieve",
            side_effect=fake_retrieve,
        ):
            result = execute_retrieval(req)

        self.assertEqual(result.route, "internal_rag")
        self.assertEqual(captured["req"].document_ids, [7])

    def test_no_document_ids_falls_back_to_existing_routing(self):
        # document_ids가 없을 때는 기존 동작(ML 라우팅)이 그대로 유지되어야
        # 한다 - 이번 수정이 회귀를 만들지 않았는지 확인.
        req = RetrievalExecuteRequest(
            query="오늘 날씨 어때?",
            owner_user_id=1,
            top_k=3,
            history=[],
            document_ids=[],
        )

        with patch(
            "app.services.retrieval.retrieval_orchestrator.search_web",
            return_value=[],
        ):
            result = execute_retrieval(req)

        self.assertIn(result.route, {"web_search", "external_or_realtime"})

    def test_search_query_has_style_directives_stripped(self):
        # 2026-08-26: PrompTune 8요소 다듬기 지시문("나에게", "3문단으로",
        # "친근하게" 등)까지 그대로 Tavily에 넘어가면 엉뚱한 결과가 상위로
        # 올라오는 사례가 확인됨(search_query_cleanup.py 참고) - 실제로
        # search_web()에 넘어가는 검색어에서 지시문이 빠졌는지 확인한다.
        req = RetrievalExecuteRequest(
            query=(
                "lg 트윈스 단장님의 이름과 약력을 안내해줘. 나에게. 최근 "
                "이슈와 관련해. 간단하게. 친근하게. 간결하게"
            ),
            owner_user_id=1,
            top_k=3,
            history=[],
            document_ids=[],
        )

        captured = {}

        def fake_search_web(
            query,
            max_results,
            time_range=None,
            search_intent=None,
            entity=None,
        ):
            captured["query"] = query
            return []

        with patch(
            "app.services.retrieval.retrieval_orchestrator.search_web",
            side_effect=fake_search_web,
        ):
            execute_retrieval(req)

        self.assertEqual(
            captured["query"], "lg 트윈스 단장님의 이름과 약력을 안내해줘"
        )


if __name__ == "__main__":
    unittest.main()
