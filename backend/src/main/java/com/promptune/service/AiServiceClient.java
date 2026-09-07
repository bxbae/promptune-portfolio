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
        HttpClient httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .build();

        JdkClientHttpRequestFactory requestFactory = new JdkClientHttpRequestFactory(httpClient);

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
                    .map(this::toSuggestResult)
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

    public PromptRuleResult promptRule(
            String text,
            Map<String, Integer> missing,
            String taskType,
            String speed,
            String detail,
            String preserve) {

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
            return demoScenarioService.findBestMatch(prompt)
                    .map(this::toGenerateResult)
                    .orElseGet(this::fallbackGenerateResult);
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

    private static final Map<String, DemoTemplateFile> DEMO_TEMPLATE_FILES = Map.of(
            "daily-report", new DemoTemplateFile(
                    "demo-templates/daily-report.docx",
                    "일일 업무 보고서.docx",
                    MediaType.parseMediaType(
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")));

    public ResponseEntity<byte[]> demoTemplateFile(String key) {
        DemoTemplateFile template = DEMO_TEMPLATE_FILES.get(key);

        if (template == null) {
            throw new ResponseStatusException(
                    HttpStatus.NOT_FOUND,
                    "존재하지 않는 데모 템플릿입니다: " + key);
        }

        byte[] bytes;

        try (java.io.InputStream in =
                getClass().getClassLoader().getResourceAsStream(template.resourcePath())) {

            if (in == null) {
                throw new java.io.IOException(
                        "템플릿 리소스를 찾을 수 없습니다: " + template.resourcePath());
            }

            bytes = in.readAllBytes();
        } catch (java.io.IOException e) {
            throw new ResponseStatusException(
                    HttpStatus.INTERNAL_SERVER_ERROR,
                    "데모 템플릿을 불러오지 못했습니다: " + e.getMessage(),
                    e);
        }

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

    private SuggestResult toSuggestResult(DemoScenario scenario) {
        if (scenario.suggestions == null || scenario.suggestions.isEmpty()) {
            return new SuggestResult(List.of());
        }
        List<SuggestionItem> items = scenario.suggestions.stream()
                .map(s -> new SuggestionItem(
                        s.element,
                        s.primary,
                        s.alternatives == null ? List.of() : s.alternatives,
                        new SuggestionAnchor(s.sentenceIndex, s.charOffset)))
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

    private Map<String, Object> fallbackGenerateResult() {
        Map<String, Object> result = new java.util.HashMap<>();
        result.put("result", fallbackAnswerText());
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
