package com.promptune.service;

import com.promptune.dto.PipelineDtos.DiagnoseResult;
import com.promptune.dto.PipelineDtos.ImprovePromptResult;
import com.promptune.dto.PipelineDtos.PromptRuleResult;
import com.promptune.dto.PipelineDtos.SuggestResult;
import com.promptune.dto.PipelineDtos.SuggestionAnchor;
import com.promptune.dto.PipelineDtos.SuggestionItem;
import com.promptune.domain.ModelUsageLog;
import com.promptune.repository.ModelUsageLogRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.multipart.MultipartFile;
import java.net.http.HttpClient;
import java.time.Duration;
import java.util.Map;
import java.util.List;

@Service
public class AiServiceClient {

    private final RestClient client;

    @Autowired
    private ModelUsageLogRepository logRepository;

    // promptune-portfolio(데모 사이트) 전용 스위치. true면 아래 5개 메서드
    // (diagnose/suggest/retrievalExecute/generate/validate)가 실제
    // ai-service(AI_SERVICE_URL)를 호출하는 대신 demo-scenarios.json에서 찾은
    // 시나리오로 즉시 응답한다. Render의 promptune-portfolio 백엔드 서비스에서만
    // AI_DEMO_ENABLED=true로 켠다 - 실제 운영(promptune)에는 켜지 않는다.
    //
    // generateDocument()도 같은 이유로 데모 모드에서 우회한다: "~보고서 파일로
    // 만들어줘" 같은 요청은 (PipelineController의 DocumentIntentResolver가) ai.generate()를
    // 거치지 않고 바로 이 메서드를 호출하는데, 데모 배포에는 실제 ai-service가 없어서
    // 그대로 두면 다운로드 버튼을 누를 때마다 500이 난다. 데모에서는 POI/PDFBox로
    // 백엔드에서 직접 docx/pdf/xlsx/txt/md를 만들어 내려준다 (buildDemoDocumentBytes).
    //
    // 주의: docs/MOCK_GUIDE.md의 "mock"(나중에 실제 모델로 교체할 임시 구현)과는
    // 다른 개념이라 일부러 "mock"이 아닌 "demo"로 이름 붙였다.
    @Value("${ai.demo.enabled:false}")
    private boolean demoEnabled;

    @Autowired
    private DemoScenarioService demoScenarioService;

    public AiServiceClient(@Value("${ai.service.url:http://localhost:8000}") String baseUrl) {
        // 2026-09-08: connectTimeout/readTimeout이 전혀 없어서, ai-service가 없거나
        // (이 데모 배포처럼) 도달 불가능한 주소일 때 demoEnabled 분기를 하나라도
        // 빠뜨리면 요청 스레드가 OS 소켓 타임아웃(수십 초~수 분)까지 그대로
        // 붙잡혀 있었다(retrieve() 누락 버그로 실제 발생 - 위 주석 참고). 실제
        // ai-service 호출도 보통 수 초~수십 초면 응답하므로, 안전망으로 연결은
        // 5초, 응답은 30초로 제한해서 이런 종류의 무한 대기를 원천 차단한다.
        HttpClient httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(5))
                .build();

        JdkClientHttpRequestFactory requestFactory = new JdkClientHttpRequestFactory(httpClient);
        requestFactory.setReadTimeout(Duration.ofSeconds(30));

        this.client = RestClient.builder()
                .baseUrl(baseUrl)
                .requestFactory(requestFactory)
                .build();
    }

    public DiagnoseResult diagnose(String text) {
        if (demoEnabled) {
            return demoScenarioService.findBestMatch(text)
                    .map(this::toDiagnoseResult)
                    .orElseGet(this::fallbackDiagnoseResult);
        }

        long start = System.currentTimeMillis();
        try {
            DiagnoseResult result = client.post()
                    .uri("/api/ai/diagnose")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of("text", text))
                    .retrieve()
                    .body(DiagnoseResult.class);
            log("ai-service", "/api/ai/diagnose", start, "success");
            return result;
        } catch (Exception e) {
            log("ai-service", "/api/ai/diagnose", start, "error");
            throw e;
        }
    }

    public SuggestResult suggest(
            String text,
            List<String> targetElements) {
        if (demoEnabled) {
            return demoScenarioService.findBestMatch(text)
                    .map(scenario -> toSuggestResult(scenario, text))
                    .orElseGet(() -> new SuggestResult(List.of()));
        }

        long start = System.currentTimeMillis();

        try {
            SuggestResult result = client.post()
                    .uri("/api/ai/suggest")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of(
                            "text", text,
                            "target_elements", targetElements))
                    .retrieve()
                    .body(SuggestResult.class);

            log("ai-service", "/api/ai/suggest", start, "success");

            return result;
        } catch (Exception e) {
            log("ai-service", "/api/ai/suggest", start, "error");
            throw e;
        }
    }

    // ImproveController.ELEMENT_PLACEHOLDERS와 문자 그대로 일치해야 한다 - improve()
    // 데모 폴백이 만든 문장에서 ImproveController가 이 placeholder 텍스트를 찾아
    // foundElements를 판단하고, 그걸 ai.suggest()(이미 demoEnabled 분기 있음)로 넘긴다.
    private static final Map<String, String> DEMO_ELEMENT_PLACEHOLDERS = Map.of(
            "TASK", "[해야 할 작업]",
            "AUDIENCE", "[대상/수신자]",
            "CONTEXT", "[배경/상황 정보]",
            "FORMAT", "[원하는 출력 형식]",
            "TONE", "[원하는 어조]",
            "LENGTH", "[원하는 길이]",
            "CONSTRAINT", "[제약 조건]",
            "EXAMPLE", "[참고 예시]");

    public PromptRuleResult promptRule(
            String text,
            Map<String, Integer> missing,
            String taskType,
            String speed,
            String detail,
            String preserve) {
        // 2026-09-08: diagnose/suggest 등과 달리 promptRule()/improvePrompt()에는
        // demoEnabled 분기가 아예 없었다 - "다듬기"(ImproveController./api/improve)
        // 버튼을 누르면 매번 존재하지 않는 ai-service를 호출하며 (새로 추가한
        // connectTimeout/readTimeout 전까지는) 최대 몇 분씩 응답 없이 멈춰 있었다.
        // 데모에서는 실제 LLM 재작성 없이, missing(diagnose 결과)의 요소들을
        // 그대로 "부족한 요소"로 돌려준다.
        if (demoEnabled) {
            List<String> missingElements =
                    missing == null ? List.of() : new java.util.ArrayList<>(missing.keySet());
            return new PromptRuleResult(missingElements, false, null, false, true, false);
        }

        long start = System.currentTimeMillis();

        try {
            PromptRuleResult result = client.post()
                    .uri("/api/ai/prompt-rule")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of(
                            "text", text,
                            "missing", missing,
                            "task_type", taskType,
                            "preference", Map.of(
                                    "speed", speed,
                                    "detail", detail,
                                    "preserve", preserve)))
                    .retrieve()
                    .body(PromptRuleResult.class);

            log("ai-service", "/api/ai/prompt-rule", start, "success");

            return result;
        } catch (Exception e) {
            log("ai-service", "/api/ai/prompt-rule", start, "error");
            throw e;
        }
    }

    public ImprovePromptResult improvePrompt(
            String text,
            String taskType,
            String speed,
            String detail,
            String preserve,
            PromptRuleResult promptRule) {
        if (demoEnabled) {
            // 원문 뒤에 부족한 요소별 placeholder를 이어붙인다 - ImproveController가
            // 이 placeholder들을 찾아 "채울 후보"를 suggest()로 요청하는 흐름을
            // 그대로 태울 수 있게(placeholder 문자열이 정확히 일치해야 함).
            StringBuilder improved =
                    new StringBuilder(text == null ? "" : text.trim());

            List<String> missingElements =
                    promptRule == null ? List.of() : promptRule.missingElements();

            for (String element : missingElements) {
                String placeholder = DEMO_ELEMENT_PLACEHOLDERS.get(element);
                if (placeholder != null) {
                    improved.append(" ").append(placeholder);
                }
            }

            return new ImprovePromptResult(improved.toString(), true);
        }

        long start = System.currentTimeMillis();

        try {
            ImprovePromptResult result = client.post()
                    .uri("/api/ai/improve-prompt")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of(
                            "text", text,
                            "task_type", taskType,
                            "preference", Map.of(
                                    "speed", speed,
                                    "detail", detail,
                                    "preserve", preserve),
                            "prompt_rule", promptRule))
                    .retrieve()
                    .body(ImprovePromptResult.class);

            log("ai-service", "/api/ai/improve-prompt", start, "success");

            return result;
        } catch (Exception e) {
            log("ai-service", "/api/ai/improve-prompt", start, "error");
            throw e;
        }
    }

    @SuppressWarnings("unchecked")
    public List<Map<String, Object>> retrieve(String query, Long ownerUserId, int topK) {
        // 2026-09-08: diagnose/suggest/retrievalExecute/generate/validate/
        // summarizeTitle/indexDocument와 달리 이 retrieve()만 demoEnabled 분기가
        // 빠져 있었다. PipelineController.execute()가 파일관리 카탈로그 제목매칭에
        // 실패하고 shouldSearchCatalog(prompt)가 true일 때(첨부 문서를 언급하는
        // 새 대화 등) 이 메서드를 호출하는데, 이 Render 배포에는 실제 ai-service가
        // 없어서 client가 연결 자체를 못 맺고 - 아래 HttpClient에 connectTimeout이
        // 없어서(JDK 기본값은 사실상 무제한, OS 소켓 타임아웃에 의존) 요청 스레드가
        // 2분 넘게 응답 없이 붙잡혀 있다가 결국 Render 프록시가 503을 돌려주는
        // 패턴이었다 - 서버 로그에 인증 성공만 찍히고 그 뒤로 아무 것도 안 남는
        // "로그 없는 실패"가 정확히 이 증상이었다(프론트의 콜드스타트 재시도가
        // 이 매 재시도마다 같은 hang을 다시 트리거해서 최대 재시도까지 다 소진됨).
        if (demoEnabled) {
            return List.of();
        }

        long start = System.currentTimeMillis();
        try {
            Map result = client.post()
                    .uri("/api/ai/retrieve")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of(
                            "query", query,
                            "owner_user_id", ownerUserId,
                            "top_k", topK))
                    .retrieve()
                    .body(Map.class);

            log("ai-service", "/api/ai/retrieve", start, "success");
            Object documents = result != null ? result.get("documents") : null;
            return documents instanceof List<?> ? (List<Map<String, Object>>) documents : List.of();
        } catch (Exception e) {
            log("ai-service", "/api/ai/retrieve", start, "error");
            throw e;
        }
    }

    // 문서 업로드 직후 ai-service에 청킹·임베딩 요청 (document_chunks 채우기)
    public Map<String, Object> indexDocument(Long documentId, Long ownerUserId, String fileType, MultipartFile file) {
        // 2026-09-08: 데모 배포에는 실제 ai-service가 없는데, 이 메서드는
        // diagnose/suggest/retrievalExecute/generate/validate와 달리 demoEnabled
        // 분기가 아예 빠져 있었다 - 그래서 데모 사이트에서 파일을 첨부하면
        // 형식(pdf/docx/...)과 무관하게 항상 "실패"로 떴다(존재하지 않는
        // ai-service로 진짜 인덱싱 요청을 보내다 커넥션 실패). 데모는 내부
        // 문서 검색 자체를 다루지 않으므로(항상 빈 목록), 실제 청킹/임베딩 없이
        // "인덱싱 성공"만 흉내 내서 첨부가 막히지 않게 한다.
        if (demoEnabled) {
            return Map.of("status", "ready");
        }
        long start = System.currentTimeMillis();
        try {
            MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
            body.add("document_id", documentId);
            body.add("owner_user_id", ownerUserId);
            body.add("file_type", fileType);
            body.add("file", file.getResource()); // 원본 파일을 그대로 전달 (S3 재조회 없음)

            Map result = client.post()
                    .uri("/api/ai/index-document")
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(body)
                    .retrieve()
                    .body(Map.class);

            log("ai-service", "/api/ai/index-document", start, "success");
            return result;
        } catch (Exception e) {
            log("ai-service", "/api/ai/index-document", start, "error");
            throw e;
        }
    }

    public Map<String, Object> indexDocument(
            Long documentId,
            Long ownerUserId,
            String fileType,
            byte[] fileBytes,
            String filename) {

        // 2026-09-08: 실제 업로드/재인덱싱 경로(DocumentController)가 쓰는 오버로드는
        // 이쪽이다. 위 MultipartFile 오버로드와 같은 이유로 demoEnabled 분기 누락 -
        // 데모 사이트에서 pdf/docx 등 지원 형식을 첨부해도 항상 "실패"로 떴던 원인.
        if (demoEnabled) {
            return Map.of("status", "ready");
        }

        long start = System.currentTimeMillis();

        try {
            MultiValueMap<String, Object> body =
                    new LinkedMultiValueMap<>();

            ByteArrayResource resource =
                    new ByteArrayResource(fileBytes) {
                        @Override
                        public String getFilename() {
                            return filename == null || filename.isBlank()
                                    ? "document." + fileType
                                    : filename;
                        }
                    };

            body.add("document_id", documentId);
            body.add("owner_user_id", ownerUserId);
            body.add("file_type", fileType);
            body.add("file", resource);

            Map result = client.post()
                    .uri("/api/ai/index-document")
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(body)
                    .retrieve()
                    .body(Map.class);

            log(
                    "ai-service",
                    "/api/ai/index-document",
                    start,
                    "success");

            return result;

        } catch (Exception e) {
            log(
                    "ai-service",
                    "/api/ai/index-document",
                    start,
                    "error");
            throw e;
        }
    }


    // Retrieval Router/Orchestrator 연동 (승연님 PR #67) — 내부문서/웹검색 여부까지 통째로 판단·실행
    public Map<String, Object> retrievalExecute(
            String query,
            Long ownerUserId,
            int topK,
            List<Map<String, String>> history,
            List<Long> documentIds,
            boolean useWebSearch) {

        return retrievalExecute(
                query,
                ownerUserId,
                topK,
                history,
                documentIds,
                useWebSearch,
                Map.of());
    }

    public Map<String, Object> retrievalExecute(
            String query,
            Long ownerUserId,
            int topK,
            List<Map<String, String>> history,
            List<Long> documentIds,
            boolean useWebSearch,
            Map<String, String> routingUserContext) {

        if (demoEnabled) {
            return demoScenarioService.findBestMatch(query)
                    .map(this::toRetrievalExecuteResult)
                    .orElseGet(this::fallbackRetrievalExecuteResult);
        }

        long start = System.currentTimeMillis();

        try {
            Map<String, Object> body =
                    new java.util.HashMap<>();

            body.put("query", query);
            body.put("owner_user_id", ownerUserId);
            body.put("top_k", topK);
            body.put(
                    "history",
                    history == null ? List.of() : history);
            body.put(
                    "document_ids",
                    documentIds == null ? List.of() : documentIds);
            body.put(
                    "use_web_search",
                    useWebSearch);
            body.put(
                    "routing_user_context",
                    routingUserContext == null
                            ? Map.of()
                            : routingUserContext);

            Map result = client.post()
                    .uri("/api/ai/retrieval-execute")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(body)
                    .retrieve()
                    .body(Map.class);

            log("ai-service", "/api/ai/retrieval-execute", start, "success");
            return result;
        } catch (Exception e) {
            log("ai-service", "/api/ai/retrieval-execute", start, "error");
            throw e;
        }
    }

    public Map<String, Object> retrievalExecute(
            String query,
            Long ownerUserId,
            int topK,
            List<Map<String, String>> history,
            List<Long> documentIds) {

        return retrievalExecute(
                query,
                ownerUserId,
                topK,
                history,
                documentIds,
                false);
    }

    public Map<String, Object> retrievalExecute(
            String query,
            Long ownerUserId,
            int topK,
            List<Map<String, String>> history) {

        return retrievalExecute(
                query,
                ownerUserId,
                topK,
                history,
                List.of(),
                false);
    }

    public Map<String, Object> retrievalExecute(
            String query,
            Long ownerUserId,
            int topK) {

        return retrievalExecute(
                query,
                ownerUserId,
                topK,
                List.of(),
                List.of(),
                false);
    }

    public Map generate(
            String prompt,
            String taskType,
            List<Map<String, Object>> documents,
            List<Map<String, Object>> webResults,
            Map<String, String> userContext,
            Map<String, String> preference,
            List<Map<String, String>> history) {
        if (demoEnabled) {
            // 2026-09-07: 큐레이션된 demo-scenarios.json 매칭에 걸리지 않는
            // 표현("성과관리 실적보고서.pptx 양식 보내줘"처럼 시나리오
            // matchQuestions와 문자 유사도가 낮은 문장)이어도, 사용자가 원래
            // 문장에 "성과관리/실적보고", "주간"+"업무보고", "일일"+"업무보고"를
            // 실제로 언급했다면 그냥 "준비된 질문만 답할 수 있어요" 안내문만
            // 보내지 말고 실제 서식 파일을 같이 붙여준다 - 안 그러면 사용자는
            // 파일 대신 제목 없는 빈 목업 문서만 받게 된다("PrompTune 생성
            // 문서.pdf" 버그).
            return demoScenarioService.findBestMatch(prompt)
                    .map(this::toGenerateResult)
                    .orElseGet(() -> fallbackGenerateResult(prompt));
        }

        long start = System.currentTimeMillis();

        try {
            Map result = client.post()
                    .uri("/api/ai/generate")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of(
                            "prompt", prompt,
                            "task_type", taskType,
                            "documents", documents,
                            "web_results", webResults,
                            "user_context", userContext,
                            "preference", preference,
                            "history", history))
                    .retrieve()
                    .body(Map.class);

            log("ai-service", "/api/ai/generate", start, "success");
            return result;
        } catch (HttpServerErrorException e) {
            log("ai-service", "/api/ai/generate", start, "error");
            // 2026-08-25: ai-service가 HCX 모델 락을 제한시간 안에 못 얻으면
            // (동시 요청 겹침) 이제 몇 분씩 기다리게 두지 않고 503으로 빠르게
            // 알려줌 — 그걸 여기서 명확한 메시지로 다시 감싸서 위로 던짐.
            if (e.getStatusCode().value() == 503) {
                throw new ResponseStatusException(
                        HttpStatus.SERVICE_UNAVAILABLE,
                        "AI가 지금 다른 요청을 처리하고 있습니다. 잠시 후 다시 시도해주세요.",
                        e);
            }
            throw e;
        } catch (Exception e) {
            log("ai-service", "/api/ai/generate", start, "error");
            throw e;
        }
    }

    public Map generate(
            String prompt,
            String taskType,
            List<Map<String, Object>> documents,
            List<Map<String, Object>> webResults,
            Map<String, String> userContext,
            Map<String, String> preference) {

        return generate(
                prompt,
                taskType,
                documents,
                webResults,
                userContext,
                preference,
                List.of());
    }

    // 기존 호출부 호환용
    public Map generate(
            String prompt,
            String taskType,
            List<Map<String, Object>> documents,
            List<Map<String, Object>> webResults,
            boolean useWebSearch) {

        return generate(
                prompt,
                taskType,
                documents,
                webResults,
                Map.of(),
                Map.of());
    }

    public ResponseEntity<byte[]> generateDocument(
            String title,
            String content,
            String format,
            byte[] templateBytes,
            String templateFilename) {

        if (templateBytes == null || templateBytes.length == 0) {
            return generateDocument(
                    title,
                    content,
                    format);
        }

        // 데모 모드에서는 사내 기존 양식(template)까지는 재현하지 않고,
        // 일반 목업 문서로 대체한다 - 어차피 실제 ai-service의 템플릿 채움
        // 로직을 그대로 흉내낼 수는 없다.
        if (demoEnabled) {
            ResponseEntity<byte[]> templateOverride = tryDemoTemplateOverride(title, content, format);
            if (templateOverride != null) {
                return templateOverride;
            }
            return buildDemoDocumentResponse(title, content, format);
        }

        long start = System.currentTimeMillis();

        try {
            MultiValueMap<String, Object> body =
                    new LinkedMultiValueMap<>();

            body.add("title", title);
            body.add("content", content);
            body.add("format", format);

            ByteArrayResource templateResource =
                    new ByteArrayResource(templateBytes) {
                        @Override
                        public String getFilename() {
                            if (templateFilename == null
                                    || templateFilename.isBlank()) {
                                return "template";
                            }
                            return templateFilename;
                        }
                    };

            body.add("template", templateResource);

            ResponseEntity<byte[]> response = client.post()
                    .uri("/api/ai/documents/generate-template")
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(body)
                    .retrieve()
                    .toEntity(byte[].class);

            log(
                    "ai-service",
                    "/api/ai/documents/generate-template",
                    start,
                    "success");

            return response;

        } catch (Exception e) {
            log(
                    "ai-service",
                    "/api/ai/documents/generate-template",
                    start,
                    "error");

            throw e;
        }
    }


    public ResponseEntity<byte[]> generateDocument(
            String title,
            String content,
            String format) {

        if (demoEnabled) {
            // DocumentIntentResolver는 "~보고서 파일로 만들어줘"류 문장이면
            // (demo-scenarios.json 매칭 여부와 무관하게) 무조건 이 메서드로
            // 바로 온다. "일일 업무보고서를 파일로 만들어줘"처럼 실제 사내
            // 서식 원본이 있는 요청이면, AI가 재조립한 목업 대신 원본 파일을
            // 내려준다 - 그래야 표/서식이 그대로 보인다.
            ResponseEntity<byte[]> templateOverride = tryDemoTemplateOverride(title, content, format);
            if (templateOverride != null) {
                return templateOverride;
            }
            return buildDemoDocumentResponse(title, content, format);
        }

        long start = System.currentTimeMillis();

        try {
            ResponseEntity<byte[]> response = client.post()
                    .uri("/api/ai/documents/generate")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of(
                            "title", title,
                            "content", content,
                            "format", format))
                    .retrieve()
                    .toEntity(byte[].class);

            log(
                    "ai-service",
                    "/api/ai/documents/generate",
                    start,
                    "success");

            return response;

        } catch (Exception e) {
            log(
                    "ai-service",
                    "/api/ai/documents/generate",
                    start,
                    "error");

            throw e;
        }
    }


    // ── 데모 모드 전용 목업 문서 생성 ───────────────────────────────────────
    // 실제 ai-service 없이도 "파일로 만들어줘" 요청이 500 없이 동작하도록,
    // title/content를 그대로 docx/pdf/xlsx/txt/md 바이트로 변환한다.
    // content에는 DocumentIntentResolver가 붙인 "[문서 생성 규칙]" 안내문이
    // 섞여 있을 수 있어 사용자에게 보여줄 본문에서는 그 부분을 잘라낸다.

    // 2026-09-07: Noto Sans CJK(OTTO/CFF 외곽선)로 처음 만들었다가
    // PDFBox 3.x가 "True Type fonts using CFF outlines are not supported"로
    // 임베드를 거부해서, 순수 glyf 외곽선 TrueType인 나눔고딕으로 교체했다.
    // PDType0Font.load()는 CIDFontType2(TrueType) 경로만 확실히 지원한다.
    private static final String DEMO_KOREAN_FONT_RESOURCE = "fonts/NanumGothic-Subset.ttf";

    // ── 데모 전용 "실제 원본 파일" 다운로드 ─────────────────────────────────
    // "~보고서 파일로 만들어줘"처럼 AI가 새로 만든 문서가 아니라, 실제로
    // 회사에서 쓰는 서식 원본을 그대로 다운로드시켜주고 싶을 때 쓴다.
    // demo-scenarios.json의 templateFile 값(예: "daily-report")이 여기 키와
    // 매칭되면, DocumentController#demoTemplate()가 이 파일 바이트를 그대로
    // 내려준다. GENERATE_DOCUMENT 흐름(POI/PDFBox로 재조립)과 달리 원본
    // 서식·표·스타일이 100% 그대로 유지된다.
    private record DemoTemplateFile(
            String resourcePath,
            String displayName,
            MediaType mediaType) {
    }

    private static final MediaType DOCX_MEDIA_TYPE = MediaType.parseMediaType(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document");

    private static final MediaType PPTX_MEDIA_TYPE = MediaType.parseMediaType(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation");

    // 2026-09-07: 사용자가 준 참고 캡쳐(네이비 헤더 표 서식)에 맞춰 daily-report도
    // 다시 만들고, weekly-report/performance-report를 새로 추가했다.
    private static final Map<String, DemoTemplateFile> DEMO_TEMPLATE_FILES = Map.of(
            "daily-report", new DemoTemplateFile(
                    "demo-templates/daily-report.docx",
                    "일일 업무 보고서.docx",
                    DOCX_MEDIA_TYPE),
            "weekly-report", new DemoTemplateFile(
                    "demo-templates/weekly-report.docx",
                    "주간 업무 보고서.docx",
                    DOCX_MEDIA_TYPE),
            "performance-report", new DemoTemplateFile(
                    "demo-templates/performance-report.pptx",
                    "성과관리 실적보고서.pptx",
                    PPTX_MEDIA_TYPE));

    private DemoTemplateFile demoTemplateOrThrow(String key) {
        DemoTemplateFile template = DEMO_TEMPLATE_FILES.get(key);

        if (template == null) {
            throw new ResponseStatusException(
                    HttpStatus.NOT_FOUND,
                    "존재하지 않는 데모 템플릿입니다: " + key);
        }

        return template;
    }

    private byte[] readTemplateResourceBytes(DemoTemplateFile template) {
        try (java.io.InputStream in =
                getClass().getClassLoader().getResourceAsStream(template.resourcePath())) {

            if (in == null) {
                throw new java.io.IOException(
                        "템플릿 리소스를 찾을 수 없습니다: " + template.resourcePath());
            }

            return in.readAllBytes();
        } catch (java.io.IOException e) {
            throw new ResponseStatusException(
                    HttpStatus.INTERNAL_SERVER_ERROR,
                    "데모 템플릿을 불러오지 못했습니다: " + e.getMessage(),
                    e);
        }
    }

    public ResponseEntity<byte[]> demoTemplateFile(String key) {
        DemoTemplateFile template = demoTemplateOrThrow(key);
        byte[] bytes = readTemplateResourceBytes(template);

        org.springframework.http.ContentDisposition disposition =
                org.springframework.http.ContentDisposition.attachment()
                        .filename(template.displayName(), java.nio.charset.StandardCharsets.UTF_8)
                        .build();

        return ResponseEntity.ok()
                .contentType(template.mediaType())
                .header(
                        org.springframework.http.HttpHeaders.CONTENT_DISPOSITION,
                        disposition.toString())
                .body(bytes);
    }

    // 2026-09-07: 사용자가 "PDF로 줘"처럼 명시적으로 PDF를 요청하면, 원본
    // docx/pptx를 그대로 내려주는 대신 실제 서식(표/색상)이 그대로 보이는
    // PDF로 변환해서 내려준다. buildDemoDocumentResponse()의 PDFBox 기반
    // 목업 PDF는 표 없이 텍스트만 나열하는 수준이라 원본과 전혀 다르게
    // 보였다("업무보고서 4.pdf"가 표 없이 문단만 나온 문제) - 서버에 설치된
    // LibreOffice(soffice)로 원본 파일을 그대로 변환해서 원본과 동일한
    // 모양의 PDF를 만든다.
    public ResponseEntity<byte[]> demoTemplateFileAsPdf(String key) {
        DemoTemplateFile template = demoTemplateOrThrow(key);
        byte[] sourceBytes = readTemplateResourceBytes(template);
        String sourceExt = extensionOf(template.resourcePath());

        byte[] pdfBytes;
        try {
            pdfBytes = convertToPdfViaLibreOffice(sourceBytes, sourceExt);
        } catch (Exception e) {
            throw new ResponseStatusException(
                    HttpStatus.INTERNAL_SERVER_ERROR,
                    "PDF 변환에 실패했습니다: " + e.getMessage(),
                    e);
        }

        String pdfFilename = demoTemplateBaseName(key) + ".pdf";

        org.springframework.http.ContentDisposition disposition =
                org.springframework.http.ContentDisposition.attachment()
                        .filename(pdfFilename, java.nio.charset.StandardCharsets.UTF_8)
                        .build();

        return ResponseEntity.ok()
                .contentType(MediaType.APPLICATION_PDF)
                .header(
                        org.springframework.http.HttpHeaders.CONTENT_DISPOSITION,
                        disposition.toString())
                .body(pdfBytes);
    }

    private String extensionOf(String resourcePath) {
        int dot = resourcePath.lastIndexOf('.');
        return dot >= 0 ? resourcePath.substring(dot + 1) : "bin";
    }

    // soffice --headless --convert-to pdf를 서브프로세스로 돌려서 변환한다.
    // 요청마다 새 프로세스를 띄우는 방식이라 몇 초 걸리지만, 데모 사이트의
    // 저빈도 다운로드 요청에는 충분하다 - 상시 리스너 방식은 과한 복잡도.
    private byte[] convertToPdfViaLibreOffice(byte[] sourceBytes, String sourceExt)
            throws java.io.IOException, InterruptedException {

        java.nio.file.Path tempDir =
                java.nio.file.Files.createTempDirectory("demo-template-pdf-");

        try {
            java.nio.file.Path sourceFile = tempDir.resolve("source." + sourceExt);
            java.nio.file.Files.write(sourceFile, sourceBytes);

            // 요청마다 별도의 LibreOffice 사용자 프로필 디렉터리를 지정한다 -
            // 기본 프로필을 공유하면 동시에 여러 변환 요청이 들어올 때 프로필
            // 잠금(lock) 충돌로 변환이 실패할 수 있다.
            java.nio.file.Path profileDir = tempDir.resolve("lo-profile");

            ProcessBuilder pb = new ProcessBuilder(
                    "soffice",
                    "--headless",
                    "--norestore",
                    "-env:UserInstallation=file://" + profileDir,
                    "--convert-to", "pdf",
                    "--outdir", tempDir.toString(),
                    sourceFile.toString());
            pb.redirectErrorStream(true);

            Process process = pb.start();

            // 표준출력 버퍼가 가득 차서 프로세스가 멈추지 않도록 반드시 소비한다.
            try (java.io.InputStream processOutput = process.getInputStream()) {
                processOutput.readAllBytes();
            }

            boolean finishedInTime = process.waitFor(30, java.util.concurrent.TimeUnit.SECONDS);
            if (!finishedInTime) {
                process.destroyForcibly();
                throw new java.io.IOException("PDF 변환이 30초 내에 끝나지 않았습니다.");
            }
            if (process.exitValue() != 0) {
                throw new java.io.IOException(
                        "soffice 변환이 실패했습니다 (exit=" + process.exitValue() + ")");
            }

            java.nio.file.Path pdfFile = tempDir.resolve("source.pdf");
            if (!java.nio.file.Files.exists(pdfFile)) {
                throw new java.io.IOException("변환된 PDF 파일을 찾을 수 없습니다.");
            }

            return java.nio.file.Files.readAllBytes(pdfFile);
        } finally {
            // 실패해도 서비스에 영향 없도록 임시파일 정리 에러는 조용히 무시한다.
            try {
                java.nio.file.Files.walk(tempDir)
                        .sorted(java.util.Comparator.reverseOrder())
                        .forEach(p -> {
                            try {
                                java.nio.file.Files.delete(p);
                            } catch (java.io.IOException ignored) {
                                // no-op
                            }
                        });
            } catch (java.io.IOException ignored) {
                // no-op
            }
        }
    }

    // DocumentIntentResolver.detectTitle()은 "~보고서"가 들어간 문장이면 거의 다
    // (근태관리 시스템 비교 보고서든, 일일/주간 업무보고서든, 성과관리 실적보고서든)
    // title을 "업무보고서"(또는 "주간 업무보고서")로 뭉뚱그려버려서 title만으로는
    // 구분이 안 된다. 그래서 title + content(원문)를 합친 문장에서 실제로 어떤
    // 원본 서식을 원하는지 키워드로 좁혀서 판단한다.
    //
    // 2026-09-07: PipelineController.executeDocumentAction()/
    // executeGroundedDocumentAction()도 GENERATE_DOCUMENT 응답을 만들 때 이
    // 메서드로 미리 매칭 여부를 확인해서 documentAction.format/title을 실제
    // 서식 파일에 맞게 보정한다("업무보고서 3.pdf"가 사실은 docx였던 버그의
    // 근본 수정 - 프론트가 Content-Disposition 헤더를 못 읽는 상황이 와도
    // 폴백 파일명이 항상 맞는 확장자를 쓰게 된다). 그래서 private이 아니라
    // public이다.
    // 주의: 이 메서드는 반드시 idempotent(같은 입력이면 항상 같은 결과)해야 한다.
    // PipelineController가 documentAction.title을 서식에 맞게 한 번 보정해두면
    // (예: "업무보고서" -> "일일 업무 보고서"), 프론트가 그 보정된 title을 그대로
    // 다시 generateDocumentFile()로 보내서 여기가 두 번째로 호출된다. 첫 번째
    // 호출 때와 다른 title 문자열이 됐다고 매칭이 깨지면 안 된다.
    public String resolveDemoTemplateKey(String title, String content) {
        String normalizedTitle = title == null ? "" : title.trim();
        String haystack = normalizedTitle + " " + (content == null ? "" : content);

        boolean mentionsPerformance =
                haystack.contains("성과관리") || haystack.contains("성과 관리")
                        || haystack.contains("실적보고") || haystack.contains("실적 보고");
        if (mentionsPerformance) {
            return "performance-report";
        }

        boolean mentionsReportWord =
                haystack.contains("업무보고") || haystack.contains("업무 보고");
        if (!mentionsReportWord) {
            return null;
        }

        // 회의록/월간/검토 보고서처럼 명백히 다른 문서인 경우는 제외한다
        // (DocumentIntentResolver.detectTitle()이 같은 "업무보고서" 생김새로
        // 뭉뚱그리는 걸 막기 위한 최소한의 안전장치).
        boolean looksUnrelatedReport =
                normalizedTitle.contains("회의록")
                        || normalizedTitle.contains("월간")
                        || normalizedTitle.contains("검토");
        if (looksUnrelatedReport) {
            return null;
        }

        // "주간"이 실제로 언급됐으면(제목이 이미 "주간 업무보고서"로 뭉뚱그려졌든,
        // 뭉뚱그려지기 전이든, PipelineController가 이미 "주간 업무 보고서"로
        // 보정해뒀든) 주간 서식으로 판단한다.
        boolean mentionsWeekly =
                normalizedTitle.contains("주간") || haystack.contains("주간");
        if (mentionsWeekly) {
            return "weekly-report";
        }

        // 그 외에는 "일일"이 실제로 언급된 경우만 일일업무보고 원본으로
        // 바꿔치기한다.
        boolean mentionsDaily = haystack.contains("일일");
        return mentionsDaily ? "daily-report" : null;
    }

    // 2026-09-07: resolveDemoTemplateKey()는 "업무보고"/"성과관리" 같은
    // 정확한 키워드가 문자 그대로 들어있어야만 찾는다. 그런데
    // DocumentIntentResolver가 직전 대화 맥락 없이 현재 발화만으로 문서 생성
    // 의도를 판단하는 경우("이 문서 파일로 만들어줘"처럼 구체적인 보고서
    // 종류를 이번 발화에 다시 안 적는 경우) content에 그 키워드 자체가 아예
    // 없을 수 있다. 그럴 때 demo-scenarios.json의 matchQuestions와 문자
    // 유사도로 대충 비슷한 시나리오를 찾아(DemoScenarioService, ai.generate()가
    // 쓰는 것과 같은 로직) 그 시나리오에 연결된 templateFile을 2차 안전장치로
    // 쓴다. resolveDemoTemplateKey()가 이미 찾았으면 이 메서드는 호출할
    // 필요가 없다 - PipelineController.applyDemoTemplateCorrection 참고.
    public String resolveDemoTemplateKeyViaScenario(String text) {
        if (text == null || text.isBlank()) {
            return null;
        }
        return demoScenarioService.findBestMatch(text)
                .map(scenario -> scenario.templateFile)
                .filter(key -> key != null && DEMO_TEMPLATE_FILES.containsKey(key))
                .orElse(null);
    }

    // 2026-09-08: PipelineController.executeGroundedDocumentAction()은
    // (documentAction이 있으면서 첨부/활성 문서도 있는 경우) demo-scenarios.json
    // 매칭을 건너뛰고 항상 "현재 첨부 문서를 바탕으로 {title} 문서를 생성합니다."
    // 라는 정형 문구 + 원문 그대로만 문서 내용으로 썼다. 그런데 "이 비교 내용
    // 바탕으로 최종 검토 보고서로 정리해서 파일로 만들어줘"처럼 이미
    // demo-scenarios.json에 잘 정리된 생성 답변(generatedAnswer)이 있는
    // 요청도 있어서, 그 경우엔 정형 문구 대신 실제로 준비된 답변을 그대로
    // 채팅 응답/문서 내용으로 쓰는 게 훨씬 낫다. 데모 시나리오 매칭
    // (DemoScenarioService, ai.generate()/retrievalExecute()가 쓰는 것과
    // 동일한 문자 유사도 로직)에서 찾은 답변이 있으면 그걸 돌려주고, 없으면
    // 호출한 쪽이 기존 정형 문구 폴백을 쓰도록 빈 Optional을 돌려준다.
    public java.util.Optional<String> demoScenarioGeneratedAnswer(String query) {
        if (!demoEnabled || query == null || query.isBlank()) {
            return java.util.Optional.empty();
        }
        return demoScenarioService.findBestMatch(query)
                .map(scenario -> scenario.generatedAnswer)
                .filter(answer -> answer != null && !answer.isBlank());
    }

    public boolean isDemoEnabled() {
        return demoEnabled;
    }

    // documentAction.format 보정용 - 서식 파일의 실제 확장자.
    public String demoTemplateFormat(String key) {
        DemoTemplateFile template = DEMO_TEMPLATE_FILES.get(key);
        if (template == null) return null;
        String name = template.displayName();
        int dot = name.lastIndexOf('.');
        return dot >= 0 ? name.substring(dot + 1).toLowerCase(java.util.Locale.ROOT) : null;
    }

    // documentAction.title 보정용 - 서식 파일의 표시 이름(확장자 제외).
    public String demoTemplateBaseName(String key) {
        DemoTemplateFile template = DEMO_TEMPLATE_FILES.get(key);
        if (template == null) return null;
        String name = template.displayName();
        int dot = name.lastIndexOf('.');
        return dot >= 0 ? name.substring(0, dot) : name;
    }

    // 2026-09-07: DocumentIntentResolver.detectFormat()은 형식을 아예 안
    // 밝히면 기본값으로도 "pdf"를 돌려주기 때문에, format 문자열만으로는
    // "진짜 PDF로 달라고 했는지"와 "그냥 기본값이 pdf인 건지"를 구분할 수
    // 없다. 그래서 원문(title+content)에 "pdf"라는 단어가 실제로 있는지로
    // 판단한다 - 명시적으로 pdf를 언급하지 않았으면 원본 서식(docx/pptx)을
    // 그대로 내려주고, 실제로 "pdf"라고 말했을 때만 변환해서 내려준다.
    private boolean wantsExplicitPdf(String title, String content) {
        String haystack =
                ((title == null ? "" : title) + " " + (content == null ? "" : content))
                        .toLowerCase(java.util.Locale.ROOT);
        return haystack.contains("pdf");
    }

    // 메시지별 "파일로 저장" 버튼처럼, format이 채팅 문구 추론이 아니라 사용자가
    // 직접 고른 값(버튼 클릭)으로 넘어오는 호출부에서는 그 값 자체가 신뢰할 수
    // 있는 명시적 신호다. 반대로 documentAction.format은 DocumentIntentResolver가
    // 기본값으로 채워 넣을 수 있어 그 자체만으로는 신뢰할 수 없으므로, 텍스트에
    // "pdf"가 실제로 언급된 경우와 OR로 묶어서 판단한다.
    private boolean wantsExplicitPdf(String title, String content, String format) {
        return wantsExplicitPdf(title, content)
                || "pdf".equalsIgnoreCase(format == null ? "" : format.trim());
    }

    // documentAction.format 보정용 - PDF를 명시적으로 요청했으면 "pdf",
    // 아니면 서식 파일의 실제 확장자(docx/pptx)를 돌려준다.
    public String demoTemplateActualFormat(String title, String content, String key) {
        if (wantsExplicitPdf(title, content)) {
            return "pdf";
        }
        return demoTemplateFormat(key);
    }

    private ResponseEntity<byte[]> tryDemoTemplateOverride(String title, String content, String format) {
        String key = resolveDemoTemplateKey(title, content);
        if (key == null) {
            return null;
        }
        if (wantsExplicitPdf(title, content, format)) {
            return demoTemplateFileAsPdf(key);
        }
        return demoTemplateFile(key);
    }

    private ResponseEntity<byte[]> buildDemoDocumentResponse(
            String title,
            String content,
            String format) {

        String safeTitle = (title == null || title.isBlank())
                ? "PrompTune 생성 문서"
                : title.trim();

        String body = stripDemoGenerationRules(content);
        String fmt = (format == null ? "" : format.trim().toLowerCase(java.util.Locale.ROOT));

        byte[] bytes;
        MediaType mediaType;

        try {
            switch (fmt) {
                case "docx" -> {
                    bytes = buildDemoDocx(safeTitle, body);
                    mediaType = MediaType.parseMediaType(
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
                }
                case "xlsx" -> {
                    bytes = buildDemoXlsx(safeTitle, body);
                    mediaType = MediaType.parseMediaType(
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
                }
                case "md" -> {
                    bytes = ("# " + safeTitle + "\n\n" + body)
                            .getBytes(java.nio.charset.StandardCharsets.UTF_8);
                    mediaType = MediaType.valueOf("text/markdown; charset=UTF-8");
                }
                case "txt" -> {
                    bytes = (safeTitle + "\n\n" + body)
                            .getBytes(java.nio.charset.StandardCharsets.UTF_8);
                    mediaType = MediaType.valueOf("text/plain; charset=UTF-8");
                }
                default -> {
                    // pdf 및 그 외 미지원 포맷은 전부 pdf로 내려준다
                    // (DocumentIntentResolver의 기본값도 pdf).
                    bytes = buildDemoPdf(safeTitle, body);
                    mediaType = MediaType.APPLICATION_PDF;
                }
            }
        } catch (Exception e) {
            throw new ResponseStatusException(
                    HttpStatus.INTERNAL_SERVER_ERROR,
                    "데모 문서 생성에 실패했습니다: " + e.getMessage(),
                    e);
        }

        String extension = fmt.isBlank() ? "pdf" : fmt;

        String downloadFilename = safeTitle.replaceAll("[\\\\/:*?\"<>|\\r\\n]", "_")
                + "." + extension;

        org.springframework.http.ContentDisposition disposition =
                org.springframework.http.ContentDisposition.attachment()
                        .filename(downloadFilename, java.nio.charset.StandardCharsets.UTF_8)
                        .build();

        return ResponseEntity.ok()
                .contentType(mediaType)
                .header(
                        org.springframework.http.HttpHeaders.CONTENT_DISPOSITION,
                        disposition.toString())
                .body(bytes);
    }

    private String stripDemoGenerationRules(String content) {
        if (content == null) {
            return "";
        }

        int idx = content.indexOf("[문서 생성 규칙]");

        if (idx < 0) {
            return content.trim();
        }

        return content.substring(0, idx).trim();
    }

    private byte[] buildDemoDocx(
            String title,
            String body) throws java.io.IOException {

        try (org.apache.poi.xwpf.usermodel.XWPFDocument doc =
                new org.apache.poi.xwpf.usermodel.XWPFDocument()) {

            org.apache.poi.xwpf.usermodel.XWPFParagraph titlePara = doc.createParagraph();
            org.apache.poi.xwpf.usermodel.XWPFRun titleRun = titlePara.createRun();
            titleRun.setText(title);
            titleRun.setBold(true);
            titleRun.setFontSize(20);
            titleRun.setFontFamily("맑은 고딕");

            doc.createParagraph();

            for (String rawLine : body.split("\n", -1)) {
                String line = rawLine.trim();

                org.apache.poi.xwpf.usermodel.XWPFParagraph p = doc.createParagraph();
                org.apache.poi.xwpf.usermodel.XWPFRun r = p.createRun();
                r.setFontFamily("맑은 고딕");
                r.setFontSize(11);

                if (line.isEmpty()) {
                    continue;
                } else if (line.startsWith("### ")) {
                    r.setText(line.substring(4));
                    r.setBold(true);
                    r.setFontSize(12);
                } else if (line.startsWith("## ")) {
                    r.setText(line.substring(3));
                    r.setBold(true);
                    r.setFontSize(13);
                } else if (line.startsWith("# ")) {
                    r.setText(line.substring(2));
                    r.setBold(true);
                    r.setFontSize(15);
                } else if (line.startsWith("- ") || line.startsWith("· ") || line.startsWith("* ")) {
                    r.setText("•  " + line.substring(2).trim());
                } else {
                    r.setText(line);
                }
            }

            java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
            doc.write(out);
            return out.toByteArray();
        }
    }

    private byte[] buildDemoXlsx(
            String title,
            String body) throws java.io.IOException {

        try (org.apache.poi.xssf.usermodel.XSSFWorkbook wb =
                new org.apache.poi.xssf.usermodel.XSSFWorkbook()) {

            org.apache.poi.xssf.usermodel.XSSFSheet sheet = wb.createSheet(
                    title.length() > 31 ? title.substring(0, 31) : title);

            int rowIdx = 0;
            org.apache.poi.ss.usermodel.Row titleRow = sheet.createRow(rowIdx++);
            titleRow.createCell(0).setCellValue(title);

            rowIdx++;

            for (String rawLine : body.split("\n", -1)) {
                String line = rawLine.trim();

                if (line.isEmpty()) {
                    continue;
                }

                org.apache.poi.ss.usermodel.Row row = sheet.createRow(rowIdx++);

                if (line.startsWith("- ") || line.startsWith("· ") || line.startsWith("* ")) {
                    row.createCell(0).setCellValue(line.substring(2).trim());
                } else {
                    row.createCell(0).setCellValue(line);
                }
            }

            sheet.setColumnWidth(0, 20000);

            java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
            wb.write(out);
            return out.toByteArray();
        }
    }

    private byte[] buildDemoPdf(
            String title,
            String body) throws java.io.IOException {

        try (org.apache.pdfbox.pdmodel.PDDocument doc = new org.apache.pdfbox.pdmodel.PDDocument()) {
            org.apache.pdfbox.pdmodel.font.PDType0Font font;

            try (java.io.InputStream fontStream =
                    getClass().getClassLoader()
                            .getResourceAsStream(DEMO_KOREAN_FONT_RESOURCE)) {

                if (fontStream == null) {
                    throw new java.io.IOException(
                            "한글 폰트 리소스를 찾을 수 없습니다: " + DEMO_KOREAN_FONT_RESOURCE);
                }

                font = org.apache.pdfbox.pdmodel.font.PDType0Font.load(doc, fontStream);
            }

            float margin = 50f;
            float pageWidth = org.apache.pdfbox.pdmodel.common.PDRectangle.A4.getWidth();
            float pageHeight = org.apache.pdfbox.pdmodel.common.PDRectangle.A4.getHeight();
            float maxTextWidth = pageWidth - margin * 2;

            java.util.List<String> lines = new java.util.ArrayList<>();
            lines.add(" TITLE " + title);
            lines.add("");

            for (String rawLine : body.split("\n", -1)) {
                lines.addAll(wrapPdfLine(rawLine.trim(), font, 11f, maxTextWidth));
            }

            org.apache.pdfbox.pdmodel.PDPage page =
                    new org.apache.pdfbox.pdmodel.PDPage(org.apache.pdfbox.pdmodel.common.PDRectangle.A4);
            doc.addPage(page);

            org.apache.pdfbox.pdmodel.PDPageContentStream stream =
                    new org.apache.pdfbox.pdmodel.PDPageContentStream(doc, page);

            float y = pageHeight - margin;
            float leading = 16f;

            try {
                for (String line : lines) {
                    if (y < margin) {
                        stream.close();
                        page = new org.apache.pdfbox.pdmodel.PDPage(org.apache.pdfbox.pdmodel.common.PDRectangle.A4);
                        doc.addPage(page);
                        stream = new org.apache.pdfbox.pdmodel.PDPageContentStream(doc, page);
                        y = pageHeight - margin;
                    }

                    boolean isTitle = line.startsWith(" TITLE ");
                    String text = isTitle ? line.substring(7) : line;
                    float fontSize = isTitle ? 18f : 11f;

                    stream.beginText();
                    stream.setFont(font, fontSize);
                    stream.newLineAtOffset(margin, y);
                    stream.showText(sanitizeForFont(text, font));
                    stream.endText();

                    y -= isTitle ? leading * 1.6f : leading;
                }
            } finally {
                stream.close();
            }

            java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
            doc.save(out);
            return out.toByteArray();
        }
    }

    /** 한 줄을 폰트/폭 기준으로 여러 줄로 감싼다 (아주 단순한 word-wrap). */
    private java.util.List<String> wrapPdfLine(
            String line,
            org.apache.pdfbox.pdmodel.font.PDType0Font font,
            float fontSize,
            float maxWidth) throws java.io.IOException {

        java.util.List<String> result = new java.util.ArrayList<>();

        if (line.isEmpty()) {
            result.add("");
            return result;
        }

        StringBuilder current = new StringBuilder();

        for (int i = 0; i < line.length(); i++) {
            char c = line.charAt(i);
            String candidate = current.toString() + c;

            float width;
            try {
                width = font.getStringWidth(sanitizeForFont(candidate, font)) / 1000f * fontSize;
            } catch (Exception e) {
                width = 0f;
            }

            if (width > maxWidth && current.length() > 0) {
                result.add(current.toString());
                current = new StringBuilder();
                current.append(c);
            } else {
                current.append(c);
            }
        }

        if (current.length() > 0 || result.isEmpty()) {
            result.add(current.toString());
        }

        return result;
    }

    /** 임베드한 서브셋 폰트에 없는 글자는 PDFBox가 예외를 던지므로 안전하게 대체한다. */
    private String sanitizeForFont(
            String text,
            org.apache.pdfbox.pdmodel.font.PDType0Font font) {

        StringBuilder out = new StringBuilder(text.length());

        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);

            try {
                font.encode(String.valueOf(c));
                out.append(c);
            } catch (Exception e) {
                out.append('?');
            }
        }

        return out.toString();
    }

    public ResponseEntity<byte[]> previewDocument(
            byte[] fileBytes,
            String filename) {

        long start = System.currentTimeMillis();

        try {
            MultiValueMap<String, Object> body =
                    new LinkedMultiValueMap<>();

            ByteArrayResource resource =
                    new ByteArrayResource(fileBytes) {
                        @Override
                        public String getFilename() {
                            return filename;
                        }
                    };

            body.add("file", resource);

            ResponseEntity<byte[]> response = client.post()
                    .uri("/api/ai/documents/preview")
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(body)
                    .retrieve()
                    .toEntity(byte[].class);

            log(
                    "ai-service",
                    "/api/ai/documents/preview",
                    start,
                    "success");

            return response;

        } catch (Exception e) {
            log(
                    "ai-service",
                    "/api/ai/documents/preview",
                    start,
                    "error");
            throw e;
        }
    }


    public Map validate(
            String original,
            String generated,
            List<Map<String, Object>> documents,
            List<Map<String, Object>> webResults) {

        if (demoEnabled) {
            // 데모 모드에서는 항상 통과 처리한다. 시나리오 답변은 이미 검증된
            // 고정 텍스트이므로, 여기서 통과시키지 않으면 validateWithRetry()가
            // 불필요하게 재생성을 시도하게 된다.
            Map<String, Object> passed = new java.util.HashMap<>();
            passed.put("passed", true);
            passed.put("issues", null);
            return passed;
        }

        long start = System.currentTimeMillis();

        try {
            Map<String, Object> body =
                    new java.util.HashMap<>();

            body.put("original", original);
            body.put("generated", generated);
            body.put(
                    "documents",
                    documents == null
                            ? List.of()
                            : documents);
            body.put(
                    "web_results",
                    webResults == null
                            ? List.of()
                            : webResults);

            Map result = client.post()
                    .uri("/api/ai/validate")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(body)
                    .retrieve()
                    .body(Map.class);

            log(
                    "ai-service",
                    "/api/ai/validate",
                    start,
                    "success");

            return result;

        } catch (Exception e) {
            log(
                    "ai-service",
                    "/api/ai/validate",
                    start,
                    "error");

            throw e;
        }
    }

    public Map validate(
            String original,
            String generated) {

        return validate(
                original,
                generated,
                List.of(),
                List.of());
    }

    public String summarizeTitle(String text) {
        if (demoEnabled) {
            // 채팅 목록에 쓸 제목이라 굳이 시나리오 매칭 없이, 원문 앞부분을
            // 그대로 잘라서 쓴다 (ai-service 호출 없이 즉시 반환).
            if (text == null || text.isBlank()) {
                return null;
            }
            String trimmed = text.strip();
            return trimmed.length() > 20 ? trimmed.substring(0, 20) + "…" : trimmed;
        }

        long start = System.currentTimeMillis();
        try {
            Map result = client.post()
                    .uri("/api/ai/summarize-title")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of("text", text))
                    .retrieve()
                    .body(Map.class);
            log("ai-service", "/api/ai/summarize-title", start, "success");
            return (String) result.get("title");
        } catch (Exception e) {
            log("ai-service", "/api/ai/summarize-title", start, "error");
            return null; // 실패해도 전체 흐름은 안 끊기게, null 반환
        }
    }

    // ── 아래는 데모 모드 전용 변환/기본값 헬퍼 ─────────────────────────────

    private DiagnoseResult toDiagnoseResult(DemoScenario scenario) {
        DemoScenario.DiagnoseFields d =
                scenario.diagnose != null ? scenario.diagnose : new DemoScenario.DiagnoseFields();
        return new DiagnoseResult(
                d.missing == null ? Map.of() : d.missing,
                d.taskType == null ? "chat" : d.taskType,
                d.typos == null ? List.of() : d.typos,
                d.needsInternalDocs);
    }

    private DiagnoseResult fallbackDiagnoseResult() {
        return new DiagnoseResult(Map.of(), "chat", List.of(), false);
    }

    private SuggestResult toSuggestResult(DemoScenario scenario, String queryText) {
        if (scenario.suggestions == null || scenario.suggestions.isEmpty()) {
            return new SuggestResult(List.of());
        }

        // 2026-09-08: demo-scenarios.json의 charOffset은 matchQuestions[0](기준 문장)을
        // 놓고 "여기 삽입하면 된다"고 미리 재놓은 값이다. 문제는, 사용자가 진단 화면에서
        // 제안을 하나 적용하면(예: CONTEXT 적용) 문장이 그만큼 길어지는데, 같은 화면에
        // 남아 있는 다음 제안(TONE)을 이어서 적용할 때도 프런트가 이 "원본 기준" 값을
        // 그대로 재사용해서 이미 길어진 문장의 엉뚱한 위치(단어 중간)에 끼워 넣는다 -
        // 실사용 중 "시스"+"템" 사이에 다른 제안 문구가 끼어들며 문장이 깨지는 걸로
        // 확인됨. charOffset은 항상 "뒤에 남는 동사구 앞"을 가리키도록 작성돼 있으므로,
        // "문장 끝에서부터 몇 글자 지점인지"(suffixLen)로 바꿔 저장한 것처럼 취급해
        // 매 호출마다 실제 현재 질의 문장(queryText) 길이 기준으로 다시 계산해서
        // 돌려준다 - JSON 값 자체는 그대로 두고 여기서만 보정한다.
        String reference =
                scenario.matchQuestions == null || scenario.matchQuestions.isEmpty()
                        ? ""
                        : scenario.matchQuestions.get(0);
        int referenceLength = reference.length();
        int queryLength = queryText == null ? 0 : queryText.length();

        List<SuggestionItem> items = scenario.suggestions.stream()
                .map(s -> {
                    int suffixLen = Math.max(0, referenceLength - s.charOffset);
                    int adjustedOffset = Math.max(0, queryLength - suffixLen);
                    return new SuggestionItem(
                            s.element,
                            s.primary,
                            s.alternatives == null ? List.of() : s.alternatives,
                            new SuggestionAnchor(s.sentenceIndex, adjustedOffset));
                })
                .toList();
        return new SuggestResult(items);
    }

    private Map<String, Object> toRetrievalExecuteResult(DemoScenario scenario) {
        Map<String, Object> result = new java.util.HashMap<>();
        result.put("documents", List.of()); // 데모는 내부 문서 검색을 다루지 않음(항상 빈 목록)
        result.put(
                "web_results",
                scenario.webResults == null
                        ? List.of()
                        : scenario.webResults);
        return result;
    }

    private Map<String, Object> fallbackRetrievalExecuteResult() {
        Map<String, Object> result = new java.util.HashMap<>();
        result.put("documents", List.of());
        result.put("web_results", List.of());
        return result;
    }

    private Map<String, Object> toGenerateResult(DemoScenario scenario) {
        Map<String, Object> result = new java.util.HashMap<>();
        result.put(
                "result",
                scenario.generatedAnswer == null
                        ? fallbackAnswerText()
                        : scenario.generatedAnswer);

        // "~파일로 만들어줘" 같은 별도 요청 없이도, 시나리오에 templateFile이
        // 지정돼 있으면 바로 다운로드 카드가 뜨도록 키를 그대로 실어 보낸다.
        // 실제 파일은 프론트가 GET /api/documents/demo-template/{key}로 받는다.
        if (scenario.templateFile != null
                && DEMO_TEMPLATE_FILES.containsKey(scenario.templateFile)) {

            result.put("templateFile", scenario.templateFile);
            result.put(
                    "templateFileName",
                    DEMO_TEMPLATE_FILES.get(scenario.templateFile).displayName());
        }

        return result;
    }

    private Map<String, Object> fallbackGenerateResult(String prompt) {
        Map<String, Object> result = new java.util.HashMap<>();
        result.put("result", fallbackAnswerText());

        String templateKey = resolveDemoTemplateKey(null, prompt);
        if (templateKey != null) {
            result.put("templateFile", templateKey);
            result.put(
                    "templateFileName",
                    DEMO_TEMPLATE_FILES.get(templateKey).displayName());
        }

        return result;
    }

    private String fallbackAnswerText() {
        return "이 데모는 미리 준비된 질문에 대해서만 답변할 수 있어요. "
                + "다른 질문도 궁금하시다면 담당 팀에 문의해 주세요.";
    }

    private void log(String provider, String endpoint, long startTime, String status) {
        int elapsed = (int) (System.currentTimeMillis() - startTime);
        logRepository.save(new ModelUsageLog(provider, endpoint, elapsed, status));
    }
}
