package com.promptune.service;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;
import java.util.Map;

/**
 * promptune-portfolio(데모 사이트) 전용: 실제 ai-service를 호출하는 대신
 * 미리 준비된 시나리오로 응답하기 위한 데이터 형태.
 *
 * 주의: 이 파일의 "데모(demo)"는 docs/MOCK_GUIDE.md에서 말하는 "mock"과는
 * 다른 개념이다. MOCK_GUIDE.md의 mock은 "나중에 실제 모델로 교체할 임시
 * 구현"이고, 여기 데모는 "promptune-portfolio 사이트에서 영구적으로 쓸,
 * 사람이 직접 작성한 고정 답변"이다. 헷갈리지 않게 클래스/설정 이름을 전부
 * mock이 아닌 demo로 지었다.
 *
 * resources/demo-scenarios.json 한 항목 = 시나리오 하나.
 * 팀에서 준비한 질문 목록으로 항목을 추가하면 된다 (자세한 방법은
 * docs/데모_시나리오_가이드.md 참고).
 */
public class DemoScenario {

    // 이 시나리오를 찾을 때 비교할 예시 질문들. 사용자가 입력한 문장과
    // 글자 단위 유사도가 가장 높은 시나리오가 선택된다(정확히 일치할 필요 없음).
    @JsonProperty("matchQuestions")
    public List<String> matchQuestions;

    // /api/ai/diagnose 응답(진단 결과) 자리를 채운다.
    @JsonProperty("diagnose")
    public DiagnoseFields diagnose;

    // /api/ai/suggest 응답(추천 문구) 자리를 채운다. 없으면 빈 목록으로 처리.
    @JsonProperty("suggestions")
    public List<SuggestionFields> suggestions;

    // /api/ai/retrieval-execute 응답 중 web_results 자리를 채운다(근거자료로
    // 표시됨). 내부 문서(documents)는 데모에서 다루지 않는다 - 항상 빈 목록.
    @JsonProperty("webResults")
    public List<Map<String, String>> webResults;

    // /api/ai/generate 응답(최종 답변 텍스트) 자리를 채운다.
    @JsonProperty("generatedAnswer")
    public String generatedAnswer;

    public static class DiagnoseFields {
        @JsonProperty("missing")
        public Map<String, Integer> missing = Map.of();

        @JsonProperty("taskType")
        public String taskType = "chat";

        @JsonProperty("typos")
        public List<Map<String, String>> typos = List.of();

        @JsonProperty("needsInternalDocs")
        public boolean needsInternalDocs = false;
    }

    public static class SuggestionFields {
        @JsonProperty("element")
        public String element;

        @JsonProperty("primary")
        public String primary;

        @JsonProperty("alternatives")
        public List<String> alternatives = List.of();

        @JsonProperty("sentenceIndex")
        public int sentenceIndex = 0;

        @JsonProperty("charOffset")
        public int charOffset = 0;
    }
}
