import sys
import types
import unittest
from datetime import datetime

from app.services.retrieval.date_resolver import KST

# 2026-08-26: generate_hcx가 모듈 최상단에서 `import torch`와
# `from app.services.hcx_runtime import hcx_lock, load_hcx_runtime`를 하는데,
# 이 테스트는 순수 문자열 조립 함수(_build_system_prompt)만 확인하므로 실제
# 모델 로딩은 필요 없다. test_retrieval_orchestrator.py와 동일한 최소 스텁으로
# 무거운 import 체인을 끊는다 (ai-service Docker 이미지에는 실제 torch/
# transformers가 설치돼 있음 - requirements.txt 참고, 여기선 샌드박스 한정 우회).
#
# 주의: 이 스텁을 module import 시점에 sys.modules에 영구로 남기면(예전 시도),
# 같은 프로세스에서 `python -m unittest discover`로 여러 테스트 파일을 한 번에
# 돌릴 때 알파벳순으로 뒤에 실행되는 다른 파일(예: test_improve_hcx.py)이 진짜
# torch 대신 이 가짜 스텁을 import하게 돼서, 원래는 "torch 없음"으로 깔끔하게
# import 에러가 나야 할 테스트가 스텁의 부족한 기능 때문에 엉뚱하게 실패하는
# 부작용이 확인됨. setUpModule/tearDownModule로 이 파일이 실행되는 동안만
# 스텁을 걸고, 끝나면 반드시 원상복구한다.
_installed_torch_stub = False
_installed_hcx_runtime_stub = False

_build_system_prompt = None
GenerateRequest = None


def setUpModule():
    global _installed_torch_stub, _installed_hcx_runtime_stub
    global _build_system_prompt, GenerateRequest

    if "torch" not in sys.modules:
        import contextlib

        torch_stub = types.ModuleType("torch")
        torch_stub.inference_mode = contextlib.nullcontext

        class _StubTensor:
            pass

        torch_stub.Tensor = _StubTensor
        sys.modules["torch"] = torch_stub
        _installed_torch_stub = True

    if "app.services.hcx_runtime" not in sys.modules:
        hcx_runtime_stub = types.ModuleType("app.services.hcx_runtime")
        hcx_runtime_stub.hcx_lock = lambda timeout=None: None
        hcx_runtime_stub.load_hcx_runtime = lambda: (None, None, None)
        sys.modules["app.services.hcx_runtime"] = hcx_runtime_stub
        _installed_hcx_runtime_stub = True

    from app.schemas.models import GenerateRequest as _GenerateRequest
    from app.services.generate_hcx import _build_system_prompt as _bsp

    GenerateRequest = _GenerateRequest
    _build_system_prompt = _bsp


def tearDownModule():
    # 이 파일이 실제로 설치한 스텁만 제거한다 (이미 다른 곳에서 진짜 torch가
    # 로드돼 있던 경우는 절대 건드리지 않음).
    sys.modules.pop("app.services.generate_hcx", None)

    if _installed_torch_stub:
        sys.modules.pop("torch", None)

    if _installed_hcx_runtime_stub:
        sys.modules.pop("app.services.hcx_runtime", None)


class BuildSystemPromptRelevanceRulesTest(unittest.TestCase):
    """
    2026-08-26: "이강인 축구선수" 질의에서 웹 검색 결과에 실제 관련 기사가
    있었는데도 모델이 그걸 무시하고 오래된 사전 지식(소속팀 "PSG", 존재하지
    않는 "K리그1 데뷔")으로 답한 사례, "침착맨" 질의에서 무관한 정치 기사
    1건을 근거로 답변한 사례가 확인됨. 시스템 프롬프트에 "검색 결과가 질문
    대상과 실제로 관련 있는지 확인" + "시간에 따라 바뀌는 사실은 사전 지식보다
    참고자료를 우선" 규칙이 반드시 포함돼야 한다.
    """

    def _prompt(self, web_results, now=None):
        req = GenerateRequest(
            prompt="이강인 축구선수에 대해 알려줘",
            task_type="report",
            documents=[],
            web_results=[],
            user_context={},
            preference={},
            history=[],
        )
        return _build_system_prompt(req, web_results, now=now)

    def test_includes_relevance_check_rule(self):
        prompt = self._prompt([])
        self.assertIn("무관한", prompt)
        self.assertIn("질문 대상", prompt)

    def test_includes_prefer_current_reference_over_prior_knowledge_rule(self):
        prompt = self._prompt([])
        self.assertIn("사전 지식", prompt)
        self.assertIn("참고자료를 따르고", prompt)

    def test_includes_no_vague_filler_rule(self):
        # 2026-08-26: "이강인 축구선수 최근 소식" 질의에서 구체적 사실 없이
        # "관심이 높아지고 있다" 같은 문장으로만 3문단을 채운 사례가 확인됨.
        prompt = self._prompt([])
        self.assertIn("분량만 채우는 문장을 쓰지 마라", prompt)

    def test_includes_structured_profile_answer_rule(self):
        # 2026-08-26: "프로필을 알려줘" 질의에 문단형 설명만 주고 확인 안 된
        # 수치(체중/생년월일 등)까지 섞은 사례가 확인됨 - '개요/기본 프로필/
        # 경력/주요 특징' 구조 + 미확인 항목 생략을 명시해야 한다.
        prompt = self._prompt([])
        self.assertIn("'개요'", prompt)
        self.assertIn("'기본 프로필'", prompt)
        self.assertIn("'경력'", prompt)
        self.assertIn("추측하지 마라", prompt)

    def test_structured_profile_format_overrides_paragraph_count_request(self):
        # 2026-08-26: "이강인 소속과 프로필을 알려줘...3문단으로..." 질의에서
        # 구조화된 정리 대신 사실이 거의 없는 두루뭉술한 문단형 답변("활약이
        # 주목받고 있습니다" 등)이 나온 사례가 확인됨 - 사용자가 문단 수를
        # 같이 요청해도 프로필 요청에는 이 구조가 우선해야 한다는 걸
        # 명시해야 한다.
        prompt = self._prompt([])
        self.assertIn("3문단으로", prompt)
        self.assertIn("프로필 요청에는 이 구조를 우선하라", prompt)

    def test_includes_profile_answer_completeness_rule(self):
        # 같은 사례에서 위키/나무위키 자료가 실제로 있었는데도 이름/소속만
        # 짧게 쓰고 생년월일/신체정보 등은 다 빠뜨린 채 답이 끝난 경우가
        # 확인됨 - 참고자료에 있는 항목은 최대한 빠짐없이 담아야 한다.
        prompt = self._prompt([])
        self.assertIn("빠짐없이 반영하라", prompt)

    def test_includes_inline_citation_rule(self):
        # 2026-08-26: 프로필 답변에 출처가 "출처 더보기" 목록에만 붙고,
        # 어느 항목이 어느 출처에서 나온 사실인지 본문에서는 알 수 없는
        # 경우가 있었음 - 참고자료가 여러 개일 때는 항목/문장 끝에
        # "[숫자](URL)" 형식의 인라인 출처 표시를 명시해야 한다.
        prompt = self._prompt([])
        self.assertIn("[숫자](출처 URL)", prompt)
        self.assertIn("지어내지 마라", prompt)


class BuildSystemPromptDateGroundingTest(unittest.TestCase):
    """
    2026-08-26: "이강인 소속과 프로필" 답변에 실제 오늘 날짜(2026년)와 무관한
    "2024년 2월 기준"이 등장한 사례가 확인됨 - 시스템 프롬프트 어디에도 오늘
    날짜를 알려주는 부분이 없어서, 모델이 사전 지식 속 임의 시점을 기준으로
    삼은 것으로 보임. date_resolver.resolve_relative_dates(query, now=None)와
    동일하게 now를 주입 가능하게 만들어 테스트를 결정론적으로 고정한다.
    """

    def _prompt(self, now):
        req = GenerateRequest(
            prompt="이강인 소속과 프로필을 알려줘",
            task_type="report",
            documents=[],
            web_results=[],
            user_context={},
            preference={},
            history=[],
        )
        return _build_system_prompt(req, [], now=now)

    def test_includes_todays_date_grounding_sentence(self):
        now = datetime(2026, 8, 26, 15, 0, tzinfo=KST)
        prompt = self._prompt(now)
        self.assertIn("오늘 날짜는 2026년 8월 26일이다", prompt)
        self.assertIn("임의로 '기준 시점'이라고 답하지 마라", prompt)

    def test_date_grounding_reflects_injected_now_not_a_hardcoded_year(self):
        # 2024년 기준이 하드코딩된 게 아니라 실제로 now 파라미터를 반영하는지
        # 확인한다 - 날짜가 바뀌면 프롬프트도 그에 맞춰 바뀌어야 한다.
        now = datetime(2027, 1, 3, 9, 0, tzinfo=KST)
        prompt = self._prompt(now)
        self.assertIn("오늘 날짜는 2027년 1월 3일이다", prompt)
        self.assertNotIn("2026년 8월 26일", prompt)

    def test_recency_rule_references_todays_date(self):
        now = datetime(2026, 8, 26, 15, 0, tzinfo=KST)
        prompt = self._prompt(now)
        self.assertIn("'최근', '최신', '요즘' 소식을 요청받으면", prompt)
        self.assertIn("2026년 8월 26일) 기준으로 판단하라", prompt)

    def test_defaults_to_real_current_time_when_now_not_given(self):
        # now를 안 넘기면(실제 운영 경로) datetime.now(KST) 기준 연도가 프롬프트에
        # 들어가야 한다 - 최소한 하드코딩된 과거 연도(2024)가 나오지 않는지만
        # 확인한다(테스트 실행 시점의 정확한 날짜까지 고정하지 않기 위함).
        prompt = self._prompt(None)
        self.assertIn("오늘 날짜는", prompt)
        self.assertNotIn("2024년 2월 기준", prompt)

    def test_includes_format_compliance_rule(self):
        prompt = self._prompt(None)

        self.assertIn(
            "사용자가 표, 목록, 문단, JSON 등 출력 형식을 명시하면",
            prompt,
        )


    def test_includes_length_compliance_rule(self):
        prompt = self._prompt(None)

        self.assertIn(
            "사용자가 글자 수, 문장 수, 줄 수, 항목 수 등 분량을 명시하면",
            prompt,
        )


    def test_includes_constraint_compliance_rule(self):
        prompt = self._prompt(None)

        self.assertIn(
            "사용자가 '반드시', '제외', '포함하지 마', '하지 마' 등 명시적인 제약 조건을 주면",
            prompt,
        )   


if __name__ == "__main__":
    unittest.main()
