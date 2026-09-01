package com.promptune.controller;

import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import com.promptune.domain.User;
import com.promptune.dto.PipelineDtos.AnalyzeRequest;
import com.promptune.dto.PipelineDtos.AnalyzeResponse;
import com.promptune.dto.PipelineDtos.DiagnoseResult;
import com.promptune.dto.PipelineDtos.ExecuteRequest;
import com.promptune.dto.PipelineDtos.GateResult;
import com.promptune.dto.PipelineDtos.RecommendResult;
import com.promptune.dto.PipelineDtos.SuggestResult;
import com.promptune.repository.UserRepository;
import com.promptune.service.AiServiceClient;
import com.promptune.service.BehaviorLogService;
import com.promptune.service.ConsentService;
import com.promptune.service.GateService;
import com.promptune.service.GraphMockService;
import com.promptune.service.RecommendService;

/**
 * 파이프라인 오케스트레이터.
 * 흐름도의 백엔드 단계(3,4,6,11,12,16)를 지휘하고, AI 단계는 ai-service 호출.
 */
@RestController
@RequestMapping("/api")
public class PipelineController {

    private final GateService gate;
    private final AiServiceClient ai;
    private final RecommendService recommend;
    private final GraphMockService graph;
    private final UserRepository userRepository; // 추가 (companyId 조회용)
    private final BehaviorLogService behaviorLog; // 필드 추가
    private final com.promptune.repository.PromptSessionRepository promptSessionRepository;
    private final com.promptune.repository.ChatSessionRepository chatSessionRepository;

        private final ConsentService consentService;
    private final com.promptune.service.MicrosoftGraphService microsoftGraphService;
    private final com.promptune.service.PreferenceResolutionService preferenceResolutionService;
    private final com.promptune.repository.ReceiverProfileRepository receiverProfileRepository; // 추가
    private final com.promptune.repository.DocumentRepository documentRepository; // 추가
    private final com.promptune.service.DocumentIntentResolver documentIntentResolver;

    public PipelineController(GateService gate, AiServiceClient ai,
        RecommendService recommend, GraphMockService graph,
        UserRepository userRepository,
        BehaviorLogService behaviorLog,
        com.promptune.repository.PromptSessionRepository promptSessionRepository,
        com.promptune.repository.ChatSessionRepository chatSessionRepository,
        ConsentService consentService,
        com.promptune.service.MicrosoftGraphService microsoftGraphService,
        com.promptune.service.PreferenceResolutionService preferenceResolutionService,
        com.promptune.repository.ReceiverProfileRepository receiverProfileRepository,
        com.promptune.repository.DocumentRepository documentRepository,
        com.promptune.service.DocumentIntentResolver documentIntentResolver) {
        this.gate = gate;
        this.ai = ai;
        this.recommend = recommend;
        this.graph = graph;
        this.userRepository = userRepository;
        this.behaviorLog = behaviorLog;
        this.promptSessionRepository = promptSessionRepository;
        this.chatSessionRepository = chatSessionRepository;
        this.consentService = consentService;
        this.microsoftGraphService = microsoftGraphService;
        this.preferenceResolutionService = preferenceResolutionService;
        this.receiverProfileRepository = receiverProfileRepository;
        this.documentRepository = documentRepository;
        this.documentIntentResolver = documentIntentResolver;
    }

    /**
     * 2번: 프롬프트 분석 (입력 중단 시 프론트가 호출).
     * 흐름: 3게이트 → 5진단(AI) → 6수정요소선정 → 7추천문구선정(AI)
     */
    @PostMapping("/analyze")
    public AnalyzeResponse analyze(@RequestBody AnalyzeRequest req, org.springframework.security.core.Authentication authentication) {
        User currentUser = userRepository.findByEmail(authentication.getName())
                .orElseThrow(() -> new org.springframework.web.server.ResponseStatusException(
                        org.springframework.http.HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다."));

        // 3번 게이트
        GateResult g = gate.check(req.text());
        if (!g.passed()) {
            return new AnalyzeResponse(
                    g,
                    null,
                    null,
                    null);
        }
        // 5번 진단 (ai-service 호출)
        DiagnoseResult d = ai.diagnose(req.text());

        // 6번 수정요소 선정
        RecommendResult r = recommend.select(d, currentUser.getId());

        // 7번 문맥 기반 추천문구 선정
        SuggestResult s;

        if (r.targetElements().isEmpty()) {
            s = new SuggestResult(java.util.List.of());
        } else {
            s = ai.suggest(
                    req.text(),
                    r.targetElements());
        }

        return new AnalyzeResponse(
                g,
                d,
                r,
                s);
    }

    /**
     * 11번: 실행 (Enter).
     * 흐름: 12분류 → (13검색) → 14생성(AI) → 16저장
     */
    @PostMapping("/execute")
public Map<String, Object> execute(@RequestBody ExecuteRequest req, org.springframework.security.core.Authentication authentication) {
    User currentUser = userRepository.findByEmail(authentication.getName())
            .orElseThrow(() -> new org.springframework.web.server.ResponseStatusException(
                    org.springframework.http.HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다."));
    Long userId = currentUser.getId();

    java.util.List<java.util.Map<String, String>> conversationHistory =
            buildConversationHistory(req.chatSessionId(), userId);

    // 문서 생성 의도와 활성 문서를 먼저 각각 확정한다.
    // "이 파일을 보고서로 만들어줘"처럼 첨부문서를 재료로 쓰는 요청은
    // Retrieval 후 Document Generator로 넘겨야 현재 파일 본문을 잃지 않는다.
    java.util.Optional<com.promptune.service.DocumentIntentResolver.DocumentAction> documentAction =
            documentIntentResolver.resolve(req.finalPrompt(), conversationHistory);

    java.util.List<Long> retrievalDocumentIds =
            resolveRetrievalDocumentIds(
                    req.documentIds(),
                    req.chatSessionId(),
                    userId,
                    req.finalPrompt());

    String documentResolutionSource =
            retrievalDocumentIds.isEmpty()
                    ? "NONE"
                    : "CURRENT_OR_ACTIVE";

    /*
     * 현재 첨부/대화의 활성 문서가 없을 때만 파일관리 catalog를 본다.
     * 따라서 현재 첨부 > 대화 active document > 파일관리 검색 우선순위가 보존된다.
     */
    if (retrievalDocumentIds.isEmpty()) {
        java.util.List<com.promptune.domain.Document> ownedCatalogDocuments =
                documentRepository.findByOwnerUserId(userId);

        com.promptune.service.DocumentReferenceResolver.Resolution catalogResolution =
                com.promptune.service.DocumentReferenceResolver.resolveMetadata(
                        req.finalPrompt(),
                        ownedCatalogDocuments);

        /*
         * title / description / document_type만으로 확정하기 애매하면
         * 기존 /api/ai/retrieve를 직접 사용해 BGE-M3 semantic 후보를 얻는다.
         * ML Router를 거치지 않으므로 "파일관리 문서 찾아줘"가 web/chat으로
         * 오분류되는 문제와 분리된다.
         */
        if (!catalogResolution.found()
                && com.promptune.service.DocumentReferenceResolver
                        .shouldSearchCatalog(req.finalPrompt())) {
            try {
                java.util.List<java.util.Map<String, Object>> semanticCandidates =
                        ai.retrieve(
                                req.finalPrompt(),
                                userId,
                                8);

                catalogResolution =
                        com.promptune.service.DocumentReferenceResolver.resolveSemantic(
                                req.finalPrompt(),
                                semanticCandidates,
                                ownedCatalogDocuments);
            } catch (Exception e) {
                System.err.println(
                        "[DocumentResolver] semantic catalog search failed"
                                + " / userId=" + userId
                                + " / prompt=" + req.finalPrompt()
                                + " / error=" + e.getMessage());
            }
        }

        if (catalogResolution.found()) {
            retrievalDocumentIds =
                    catalogResolution.documentIds();

            documentResolutionSource =
                    catalogResolution.source();

            System.out.println(
                    "[DocumentResolver] source="
                            + catalogResolution.source()
                            + " / confidence="
                            + String.format(
                                    java.util.Locale.ROOT,
                                    "%.3f",
                                    catalogResolution.confidence())
                            + " / documentIds="
                            + catalogResolution.documentIds()
                            + " / candidates="
                            + catalogResolution.candidates().stream()
                                    .map(candidate ->
                                            candidate.documentId()
                                                    + ":"
                                                    + candidate.title()
                                                    + ":"
                                                    + String.format(
                                                            java.util.Locale.ROOT,
                                                            "%.3f",
                                                            candidate.score()))
                                    .toList());
        }
    }

    ensureActiveDocumentsReady(retrievalDocumentIds, userId);

    if (documentAction.isPresent() && retrievalDocumentIds.isEmpty()) {
        return executeDocumentAction(
                req,
                userId,
                documentAction.get());
    }

    DiagnoseResult d = ai.diagnose(req.finalPrompt());

    String persistedTaskType = documentAction.isPresent()
            ? "document_generation"
            : d.taskType();

    com.promptune.domain.PromptSession session =
            new com.promptune.domain.PromptSession(
                    userId,
                    req.finalPrompt(),
                    req.finalPrompt(),
                    persistedTaskType,
                    req.chatSessionId());

    promptSessionRepository.save(session);

    // RETRY_DUPLICATE_MESSAGE_BUG 후속 수정 (2026-08-27):
    // 위 aiText == null 케이스만 delete를 해주고 있었는데, 그건 ai.generate()/
    // validateWithRetry()가 "예외 없이 정상 리턴됐지만 result가 비어있는" 경우만
    // 커버한다. ai.retrievalExecute()/ai.generate()/validateWithRetry() 자체가
    // 타임아웃·네트워크 오류 등으로 예외를 던지며 실패하는 경우엔 그 if문에
    // 도달하지도 못해서, 파이프라인 초반에 저장해둔 이 빈 session이 그대로 DB에
    // 남았다. 아래 블록 전체를 try로 감싸고, 그 안에서 던져지는 모든 런타임
    // 예외를 여기서 잡아 session을 지운 뒤 그대로 다시 던지도록 해서 두 케이스를
    // 전부 커버한다.
    // (prompt_session_documents는 ON DELETE CASCADE라 첨부 연결도 같이 안전하게 정리됨)
    try {
    linkCurrentAttachments(
            req.documentIds(),
            userId,
            session.getId());

    // Retrieval Router/Orchestrator(승연님 PR #67)가 내부문서 검색·웹검색 여부까지
    // 통째로 판단·실행해서 결과를 돌려줌. 자바 쪽 needsInternalDocs/ai.retrieve()는 더 이상 안 씀.
    // 사용자 Web 검색 요청은 retrieval-execute까지 전달되며,
    // 내부 문서와 Web을 동시에 사용하는 복합 Retrieval도 지원한다.
    // 2026-08-25: TAVILY_API_KEY가 prod에 없으면 web_search/external_or_realtime
    // 라우트로 분류된 요청은 ai-service의 /retrieval-execute가 500을 던지는데,
    // 그걸 그대로 흘려보내면 /api/execute 전체가 실패해서 채팅 자체가 안 됐음
    // (아래 user_context/Microsoft 미연동과 동일한 부류의 fail-open 처리 필요 -
    // 검색이 안 되면 검색 없이라도 답변은 계속 생성돼야 함).
    Map<String, String> routingUserContext =
            buildRoutingUserContext(authentication);

    Map<String, Object> retrieval;
    try {
        // 2026-08-25: TAVILY_API_KEY 등록 후 실제 웹검색 결과가 붙자, 결과 하나당
        // 본문 최대 1200자(3개면 최대 3600자+)가 프롬프트에 통째로 들어가면서
        // 내부문서는 최대 4개 chunk를 사용한다.
        // Web 검색 결과 수는 ai-service에서 별도로 최대 3건으로 제한한다.
        // 현재 첨부/활성/파일관리에서 resolve된 실제 document ID를 반드시 전달한다.
        retrieval = ai.retrievalExecute(
                req.finalPrompt(),
                userId,
                4,
                conversationHistory,
                retrievalDocumentIds,
                Boolean.TRUE.equals(req.useWebSearch()),
                routingUserContext);
    } catch (Exception e) {
        // 첨부/이전 문서가 명확한 요청에서 Retrieval 실패를 숨기고 일반 HCX 답변으로
        // 넘어가면 모델이 과거 문서나 임의 문서를 근거로 답하는 치명적 오류가 난다.
        if (!retrievalDocumentIds.isEmpty()) {
            System.err.println(
                    "[문서 Retrieval 실패] documentIds="
                            + retrievalDocumentIds
                            + " / prompt="
                            + req.finalPrompt()
                            + " / error="
                            + e.getMessage());
            throw new ResponseStatusException(
                    HttpStatus.SERVICE_UNAVAILABLE,
                    "첨부 문서 내용을 불러오지 못했습니다. 문서 분석 상태를 확인해주세요.");
        }

        // 웹/일반 검색 실패는 검색 없이도 대화를 계속할 수 있으므로 fail-open 유지.
        retrieval = java.util.Map.of();
    }
    java.util.List<java.util.Map<String, Object>> documents =
            (java.util.List<java.util.Map<String, Object>>) retrieval.getOrDefault("documents", java.util.List.of());
    java.util.List<java.util.Map<String, Object>> webResults =
            (java.util.List<java.util.Map<String, Object>>) retrieval.getOrDefault("web_results", java.util.List.of());

    validateDocumentRetrievalInvariant(
            retrievalDocumentIds,
            documents,
            userId);

    System.out.println(
            "[ExecutionContext] chatSessionId=" + req.chatSessionId()
                    + " / currentDocumentIds=" + req.documentIds()
                    + " / activeDocumentIds=" + retrievalDocumentIds
                    + " / documentResolutionSource=" + documentResolutionSource
                    + " / route=" + retrieval.get("route")
                    + " / retrievedDocumentIds="
                    + documents.stream()
                            .map(doc -> doc.get("document_id"))
                            .distinct()
                            .toList());

    if (documentAction.isPresent()) {
        return executeGroundedDocumentAction(
                req,
                userId,
                documentAction.get(),
                session,
                retrievalDocumentIds,
                documents);
    }

    // user_context이면 실제 Microsoft Graph 프로필을 생성 컨텍스트로 전달.
    // Microsoft 미연동/연동 실패 시에도 채팅 자체는 계속 진행돼야 하므로
    // (다른 보조 조회들과 동일하게) 실패는 조용히 무시하고 컨텍스트 없이 진행한다.
    // (안 그러면 user_context 라우트로 분류된 모든 메시지가 Microsoft 미연동
    // 사용자에게는 통째로 실패해버림 - 2026-08-24 채팅 전체 실패 이슈)
    // routingUserContext는 retrieval에서 "현재 사용자 본인" 여부를
    // 판별하기 위한 정보다. 일반 CHAT 생성 프롬프트에는 절대 주입하지 않는다.
    Map<String, String> userContext =
            new java.util.HashMap<>();

    if ("user_context".equals(retrieval.get("route"))) {
        // 실제로 사용자 자신의 정보를 묻는 경우에만 생성 컨텍스트로 전달한다.
        userContext.putAll(routingUserContext);
        try {
            com.fasterxml.jackson.databind.JsonNode profile =
                    microsoftGraphService.getProfile(userId);

            String displayName = profile.path("displayName").asText("");
            String companyName = profile.path("companyName").asText("");
            String department = profile.path("department").asText("");
            String jobTitle = profile.path("jobTitle").asText("");
            String mail = profile.path("mail").asText("");

            if (!displayName.isBlank()) userContext.put("displayName", displayName);
            if (!companyName.isBlank()) userContext.put("companyName", companyName);
            if (!department.isBlank()) userContext.put("department", department);
            if (!jobTitle.isBlank()) userContext.put("jobTitle", jobTitle);
            if (!mail.isBlank()) userContext.put("mail", mail);
        } catch (Exception e) {
            // Microsoft 미연동(404) 등 - userContext 없이 계속 진행
        }
    }

    var preference = preferenceResolutionService.resolve(authentication);
    Map<String, String> preferenceMap = new java.util.HashMap<>();
    preferenceMap.put("speed", preference.speed());
    preferenceMap.put("detail", preference.detail());
    preferenceMap.put("preserve", preference.preserve());

    // 수신자가 지정된 경우, 그 사람 preferredTone을 생성 요청에 함께 전달
    // (본인 소유 프로필인지 확인 - 남의 receiverProfileId를 넣어도 무시되도록 방어)
    if (req.receiverProfileId() != null) {
        receiverProfileRepository.findById(req.receiverProfileId())
                .filter(rp -> rp.getUserId().equals(userId))
                .map(com.promptune.domain.ReceiverProfile::getPreferredTone)
                .filter(tone -> tone != null && !tone.isBlank())
                .ifPresent(tone -> preferenceMap.put("receiverTone", tone));
    }

    Map result = ai.generate(
            req.finalPrompt(),
            d.taskType(),
            documents,
            webResults,
            userContext,
            preferenceMap,
            conversationHistory);

    result = validateWithRetry(
              req.finalPrompt(),
              result,
              d.taskType(),
              documents,
              webResults,
              userContext,
              preferenceMap,
              conversationHistory);

    if (req.elementActions() != null && consentService.canUsePersonalization(userId)) {
        for (com.promptune.dto.PipelineDtos.ElementAction ea : req.elementActions()) {
            behaviorLog.recordAction(userId, ea.element(), ea.action(), req.chatSessionId());
        }
    }

    // AI 응답 원문도 같이 저장 (이제까지 저장 안 되고 있던 부분 — 메시지 목록에 필요해서 추가)
    Object aiText = result != null ? result.get("result") : null;

    if (aiText == null) {
        // 생성 실패(result가 비어있는 케이스) - 아래 catch(RuntimeException)가
        // 이 예외를 잡아서 session을 지운 뒤 다시 던진다.
        throw new ResponseStatusException(
                org.springframework.http.HttpStatus.INTERNAL_SERVER_ERROR,
                "응답 생성에 실패했습니다.");
    }

    session.setAiResponseText(aiText.toString());
    promptSessionRepository.save(session);

    // 첨부 관계는 documents.prompt_session_id 단일 컬럼이 아니라
    // prompt_session_documents 연결 테이블에 저장한다. 같은 파일을 여러 턴에서
    // 다시 사용해도 과거 대화의 첨부 이력이 사라지지 않는다.
    java.util.List<Long> persistedDocumentIds =
            retrievalDocumentIds != null && !retrievalDocumentIds.isEmpty()
                    ? retrievalDocumentIds
                    : (req.documentIds() == null
                            ? java.util.List.of()
                            : req.documentIds());

    linkCurrentAttachments(
            persistedDocumentIds,
            userId,
            session.getId());

    System.out.println(
            "[DocumentMemory] promptSessionId="
                    + session.getId()
                    + " / persistedDocumentIds="
                    + persistedDocumentIds);

    if (req.chatSessionId() != null) {
    chatSessionRepository.findById(req.chatSessionId()).ifPresent(chat -> {
        // 이 대화의 첫 프롬프트라면(title이 아직 없으면) 제목 자동 생성
        if (chat.getTitle() == null || chat.getTitle().isBlank()) {
            String raw = req.finalPrompt();
            String aiTitle = ai.summarizeTitle(raw);   // ai-service 호출 시도

            String title;
            if (aiTitle != null && !aiTitle.isBlank()) {
                title = aiTitle;   // AI 요약 성공
            } else {
                // ai-service 호출 실패 시 안전장치: 기존 방식(앞부분 자르기)으로 대체
                title = raw.length() > 20 ? raw.substring(0, 20) + "..." : raw;
            }
            chat.setTitle(title);
        }
        chat.touch();
        chatSessionRepository.save(chat);
    });
}

    // 2026-08-25: retrieval-execute가 실패해서(예: TAVILY_API_KEY 없음) 위에서
    // fail-open으로 retrieval = Map.of()(빈 맵)가 된 경우, retrieval.get("route")는
    // null이 됨. java.util.Map.of(...)는 값이 null이면 NullPointerException을
    // 던지기 때문에, ai-service 호출(diagnose/retrieval-execute/generate/validate/
    // summarize-title)이 전부 성공한 뒤에도 이 리턴문에서만 500이 나는 버그가 있었음
    // (chat session 44, 03:47:17 - retrieval-execute가 03:46:30에 실패한 직후 요청).
    // null을 허용하는 HashMap으로 바꿔서 해결.
    Map<String, Object> response = new java.util.HashMap<>();
    response.put("taskType", d.taskType());
    response.put("needsInternalDocs", "internal_rag".equals(retrieval.get("route")));
    response.put("retrievalRoute", retrieval.get("route"));
    response.put("usedInternalRag", retrieval.getOrDefault("used_internal_rag", false));
    response.put("usedWebSearch", retrieval.getOrDefault("used_web_search", false));
    response.put("result", result);
    response.put("promptSessionId", session.getId());
    response.put("activeDocumentIds", retrievalDocumentIds);
    response.put(
            "retrievedDocumentIds",
            documents.stream()
                    .map(doc -> doc.get("document_id"))
                    .filter(java.util.Objects::nonNull)
                    .distinct()
                    .toList());

    // Web 검색 결과의 실제 출처를 클라이언트에서도 확인할 수 있게 유지한다.
    response.put("sources", buildSources(webResults));
    return response;
    } catch (RuntimeException e) {
        // 2026-08-27 되돌림: 이전엔 실패하면 무조건 session을 지웠는데, 그러니
        // 응답을 못 받은 프롬프트가 새로고침 후 화면에서 아예 안 보이는 문제가
        // 생겼다(예진님 피드백) - "재전송을 여러 번 실패했을 때 중복으로 쌓이는
        // 것"만 막으면 되는 거였지, 실패 흔적 자체를 다 지우라는 게 아니었음.
        // 그래서 삭제는 하지 않고 session(prompt만 있고 응답 없음)을 그대로
        // 둔다 - 프론트(buildLoadedMessages)가 같은 prompt로 연속된 실패
        // 기록 중 마지막 하나만 남기고 접어서 보여주므로, 재시도해도 화면엔
        // 중복 없이 항상 최소 1개는 남는다.
        throw e;
    }
    }

    private Map<String, String> buildRoutingUserContext(
            org.springframework.security.core.Authentication authentication) {

        Map<String, String> context =
                new java.util.HashMap<>();

        if (authentication == null
                || authentication.getName() == null
                || authentication.getName().isBlank()) {
            return context;
        }

        userRepository.findByEmail(authentication.getName())
                .ifPresent(user -> {
                    if (user.getName() != null
                            && !user.getName().isBlank()) {
                        context.put("name", user.getName());
                    }

                    if (user.getEmail() != null
                            && !user.getEmail().isBlank()) {
                        context.put("email", user.getEmail());
                    }
                });

        return context;
    }

    private java.util.List<java.util.Map<String, String>> buildSources(
            java.util.List<java.util.Map<String, Object>> webResults) {
        if (webResults == null || webResults.isEmpty()) {
            return java.util.List.of();
        }

        java.util.LinkedHashMap<String, java.util.Map<String, String>> byUrl =
                new java.util.LinkedHashMap<>();

        for (java.util.Map<String, Object> item : webResults) {
            Object urlObj = item.get("url");
            String url = urlObj != null ? urlObj.toString().trim() : "";
            if (url.isEmpty() || byUrl.containsKey(url)) {
                continue;
            }
            Object titleObj = item.get("title");
            String title = titleObj != null ? titleObj.toString().trim() : "";
            java.util.Map<String, String> source = new java.util.HashMap<>();
            source.put("title", title.isEmpty() ? url : title);
            source.put("url", url);
            byUrl.put(url, source);
        }

        return new java.util.ArrayList<>(byUrl.values());
    }

    private java.util.List<java.util.Map<String, String>> buildConversationHistory(
            Long chatSessionId,
            Long userId) {

        if (chatSessionId == null) {
            return java.util.List.of();
        }

        com.promptune.domain.ChatSession chat =
                chatSessionRepository.findById(chatSessionId)
                        .orElseThrow(() -> new ResponseStatusException(
                                HttpStatus.NOT_FOUND,
                                "대화를 찾을 수 없습니다."));

        if (!userId.equals(chat.getUserId())) {
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN,
                    "본인 대화만 사용할 수 있습니다.");
        }

        java.util.List<com.promptune.domain.PromptSession> sessions =
                promptSessionRepository
                        .findByChatSessionIdOrderByCreatedAtAsc(chatSessionId);

        // 최근 6개 대화쌍만 전달하여 HCX context 크기를 제한
        int startIndex = Math.max(0, sessions.size() - 6);

        java.util.List<java.util.Map<String, String>> history =
                new java.util.ArrayList<>();

        for (int i = startIndex; i < sessions.size(); i++) {
            com.promptune.domain.PromptSession session = sessions.get(i);

            String userText = compactHistoryText(session.getOriginalText());

            if (userText != null && !userText.isBlank()) {
                history.add(java.util.Map.of(
                        "role", "user",
                        "content", userText));
            }

            String assistantText =
                    compactHistoryText(session.getAiResponseText());

            if (assistantText != null && !assistantText.isBlank()) {
                history.add(java.util.Map.of(
                        "role", "assistant",
                        "content", assistantText));
            }
        }

        return history;
    }

    private Map<String, Object> executeDocumentAction(
            ExecuteRequest req,
            Long userId,
            com.promptune.service.DocumentIntentResolver.DocumentAction action) {

        String assistantText =
                "요청하신 " + action.title() + " 문서를 생성합니다.";

        com.promptune.domain.PromptSession session =
                new com.promptune.domain.PromptSession(
                        userId,
                        req.finalPrompt(),
                        req.finalPrompt(),
                        "document_generation",
                        req.chatSessionId());

        session.setAiResponseText(assistantText);
        promptSessionRepository.save(session);

        linkCurrentAttachments(
                req.documentIds(),
                userId,
                session.getId());

        touchChatSession(
                req.chatSessionId(),
                req.finalPrompt());

        Map<String, Object> actionPayload = new java.util.HashMap<>();
        actionPayload.put("type", "GENERATE_DOCUMENT");
        actionPayload.put("title", action.title());
        actionPayload.put("content", action.content());
        actionPayload.put("format", action.format());
        actionPayload.put("useExistingTemplate", action.useExistingTemplate());

        Map<String, Object> resultPayload = new java.util.HashMap<>();
        resultPayload.put("result", assistantText);
        resultPayload.put("used_web_search", false);

        Map<String, Object> response = new java.util.HashMap<>();
        response.put("taskType", "document_generation");
        response.put("needsInternalDocs", false);
        response.put("retrievalRoute", "no_retrieval");
        response.put("usedInternalRag", false);
        response.put("usedWebSearch", false);
        response.put("result", resultPayload);
        response.put("promptSessionId", session.getId());
        response.put("documentAction", actionPayload);

        return response;
    }

    private Map<String, Object> executeGroundedDocumentAction(
            ExecuteRequest req,
            Long userId,
            com.promptune.service.DocumentIntentResolver.DocumentAction action,
            com.promptune.domain.PromptSession session,
            java.util.List<Long> activeDocumentIds,
            java.util.List<java.util.Map<String, Object>> retrievedDocuments) {

        String assistantText =
                "현재 첨부 문서를 바탕으로 " + action.title() + " 문서를 생성합니다.";

        session.setAiResponseText(assistantText);
        promptSessionRepository.save(session);

        touchChatSession(
                req.chatSessionId(),
                req.finalPrompt());

        String groundedContent =
                buildGroundedDocumentSource(
                        action.content(),
                        retrievedDocuments);

        Map<String, Object> actionPayload =
                new java.util.HashMap<>();

        actionPayload.put("type", "GENERATE_DOCUMENT");
        actionPayload.put("title", action.title());
        actionPayload.put("content", groundedContent);
        actionPayload.put("format", action.format());
        actionPayload.put(
                "useExistingTemplate",
                action.useExistingTemplate());

        Map<String, Object> resultPayload =
                new java.util.HashMap<>();

        resultPayload.put("result", assistantText);
        resultPayload.put("used_web_search", false);

        Map<String, Object> response =
                new java.util.HashMap<>();

        response.put(
                "taskType",
                "document_generation");

        response.put(
                "needsInternalDocs",
                true);

        response.put(
                "retrievalRoute",
                "internal_rag");

        response.put(
                "usedInternalRag",
                true);

        response.put(
                "usedWebSearch",
                false);

        response.put(
                "result",
                resultPayload);

        response.put(
                "promptSessionId",
                session.getId());

        response.put(
                "activeDocumentIds",
                activeDocumentIds);

        response.put(
                "retrievedDocumentIds",
                retrievedDocuments.stream()
                        .map(doc -> doc.get("document_id"))
                        .filter(java.util.Objects::nonNull)
                        .distinct()
                        .toList());

        response.put(
                "documentAction",
                actionPayload);

        return response;
    }

    private String buildGroundedDocumentSource(
            String instruction,
            java.util.List<java.util.Map<String, Object>> documents) {

        StringBuilder out =
                new StringBuilder();

        out.append(
                instruction == null
                        ? ""
                        : instruction.trim());

        out.append("\n\n[첨부 문서 원문]\n");

        Object previousId = null;
        int usedChars = 0;
        final int maxChars = 12000;

        for (java.util.Map<String, Object> doc : documents) {

            if (usedChars >= maxChars) {
                break;
            }

            Object documentId =
                    doc.get("document_id");

            if (!java.util.Objects.equals(
                    previousId,
                    documentId)) {

                if (previousId != null) {
                    out.append("\n");
                }

                out.append("[문서 id=")
                        .append(documentId)
                        .append("] ")
                        .append(
                                String.valueOf(
                                        doc.getOrDefault(
                                                "title",
                                                "")))
                        .append("\n");

                previousId = documentId;
            }

            String content =
                    String.valueOf(
                            doc.getOrDefault(
                                    "content",
                                    ""))
                            .trim();

            if (content.isBlank()) {
                continue;
            }

            int remaining =
                    maxChars - usedChars;

            String piece =
                    content.length() > remaining
                            ? content.substring(
                                    0,
                                    remaining)
                            : content;

            out.append(piece)
                    .append("\n");

            usedChars += piece.length();
        }

        return out.toString().trim();
    }

    private void linkCurrentAttachments(
            java.util.List<Long> documentIds,
            Long userId,
            Long promptSessionId) {

        if (documentIds == null || documentIds.isEmpty()) {
            return;
        }

        java.util.List<com.promptune.domain.Document> docs =
                documentRepository.findAllById(documentIds);

        java.util.List<com.promptune.domain.Document> ownedDocs =
                docs.stream()
                        .filter(doc -> userId.equals(doc.getOwnerUserId()))
                        .toList();

        for (com.promptune.domain.Document doc : ownedDocs) {
            documentRepository.linkPromptSessionDocument(
                    promptSessionId,
                    doc.getId());
        }
    }

    private void touchChatSession(
            Long chatSessionId,
            String prompt) {

        if (chatSessionId == null) {
            return;
        }

        chatSessionRepository.findById(chatSessionId).ifPresent(chat -> {
            if (chat.getTitle() == null || chat.getTitle().isBlank()) {
                String raw = prompt == null ? "" : prompt.trim();
                String title = raw.length() > 20
                        ? raw.substring(0, 20) + "..."
                        : raw;
                chat.setTitle(title.isBlank() ? "새 문서" : title);
            }

            chat.touch();
            chatSessionRepository.save(chat);
        });
    }

    private java.util.List<Long> resolveRetrievalDocumentIds(
            java.util.List<Long> currentDocumentIds,
            Long chatSessionId,
            Long userId,
            String prompt) {

        java.util.List<Long> ownedCurrent = filterOwnedDocumentIds(
                currentDocumentIds,
                userId);

        // 현재 턴 첨부는 ML Router보다 항상 우선한다.
        if (!ownedCurrent.isEmpty()) {
            return ownedCurrent;
        }

        if (chatSessionId == null || !looksLikeDocumentFollowup(prompt)) {
            return java.util.List.of();
        }

        java.util.List<com.promptune.domain.PromptSession> sessions =
                promptSessionRepository
                        .findByChatSessionIdOrderByCreatedAtAsc(chatSessionId);

        // "그거/이거"처럼 매우 모호한 지시대명사는 오래된 첨부파일까지
        // 거슬러 올라가면 오히려 틀린 문서를 활성화한다. 이런 표현은 직전 2턴에
        // 첨부가 있을 때만 문서 참조로 해석하고, 명시적 "그 파일/거기서/문서 요약"
        // 표현은 더 이전 첨부까지 찾는다.
        int maxLookback =
                isVerificationFollowup(prompt)
                        ? 1
                        : (isGenericDocumentReference(prompt)
                                ? 2
                                : sessions.size());

        int checked = 0;

        for (int i = sessions.size() - 1; i >= 0 && checked < maxLookback; i--, checked++) {
            com.promptune.domain.PromptSession session = sessions.get(i);

            java.util.List<Long> documentIds =
                    documentRepository.findByPromptSessionId(session.getId())
                            .stream()
                            .filter(doc -> userId.equals(doc.getOwnerUserId()))
                            .map(com.promptune.domain.Document::getId)
                            .toList();

            if (!documentIds.isEmpty()) {
                return documentIds;
            }
        }

        return java.util.List.of();
    }

    private boolean isVerificationFollowup(String prompt) {
        String text = prompt == null
                ? ""
                : prompt.trim().toLowerCase();

        return containsAnyText(
                text,
                "확실해",
                "확실한가",
                "맞아",
                "맞나요",
                "진짜야",
                "정말이야",
                "근거 있어",
                "근거있어",
                "출처 맞아",
                "출처가 맞아",
                "다시 확인",
                "재확인");
    }

    private boolean isGenericDocumentReference(String prompt) {
        String text = prompt == null ? "" : prompt.trim().toLowerCase();

        boolean hasGenericPronoun = containsAnyText(
                text,
                "이거", "이걸", "그거", "그걸", "그것", "저거");

        return hasGenericPronoun
                && !containsAnyText(
                        text,
                        "문서", "파일", "이력서", "보고서",
                        "거기서", "아까", "전에 올린",
                        "내용", "요약", "프로젝트", "경력");
    }

    private boolean containsAnyText(String text, String... markers) {
        for (String marker : markers) {
            if (text.contains(marker)) {
                return true;
            }
        }
        return false;
    }

    private void ensureActiveDocumentsReady(
            java.util.List<Long> activeDocumentIds,
            Long userId) {

        if (activeDocumentIds == null || activeDocumentIds.isEmpty()) {
            return;
        }

        java.util.List<com.promptune.domain.Document> docs =
                documentRepository.findAllById(activeDocumentIds)
                        .stream()
                        .filter(doc -> userId.equals(doc.getOwnerUserId()))
                        .toList();

        if (docs.size() != activeDocumentIds.stream().distinct().count()) {
            throw new ResponseStatusException(
                    HttpStatus.NOT_FOUND,
                    "첨부 문서를 찾을 수 없습니다.");
        }

        java.util.List<String> failedTitles = docs.stream()
                .filter(doc -> "FAILED".equalsIgnoreCase(doc.getIndexStatus()))
                .map(com.promptune.domain.Document::getTitle)
                .toList();

        if (!failedTitles.isEmpty()) {
            throw new ResponseStatusException(
                    HttpStatus.CONFLICT,
                    "문서 분석에 실패했습니다: " + String.join(", ", failedTitles));
        }

        java.util.List<String> waitingTitles = docs.stream()
                .filter(doc -> !"READY".equalsIgnoreCase(doc.getIndexStatus())
                        && !"TEXT_READY".equalsIgnoreCase(doc.getIndexStatus()))
                .map(com.promptune.domain.Document::getTitle)
                .toList();

        if (!waitingTitles.isEmpty()) {
            throw new ResponseStatusException(
                    HttpStatus.CONFLICT,
                    "문서 분석이 아직 완료되지 않았습니다: " + String.join(", ", waitingTitles));
        }
    }

    private void validateDocumentRetrievalInvariant(
            java.util.List<Long> activeDocumentIds,
            java.util.List<java.util.Map<String, Object>> retrievedDocuments,
            Long userId) {

        if (activeDocumentIds == null || activeDocumentIds.isEmpty()) {
            return;
        }

        java.util.Set<Long> expected = new java.util.HashSet<>(activeDocumentIds);
        java.util.Set<Long> actual = new java.util.HashSet<>();

        for (java.util.Map<String, Object> document : retrievedDocuments) {
            Object rawId = document.get("document_id");
            if (rawId instanceof Number number) {
                actual.add(number.longValue());
            }
        }

        if (!actual.isEmpty() && !expected.containsAll(actual)) {
            throw new ResponseStatusException(
                    HttpStatus.INTERNAL_SERVER_ERROR,
                    "첨부 문서 범위를 벗어난 검색 결과가 반환되었습니다.");
        }

        if (!retrievedDocuments.isEmpty()) {
            return;
        }

        java.util.List<com.promptune.domain.Document> docs =
                documentRepository.findAllById(activeDocumentIds)
                        .stream()
                        .filter(doc -> userId.equals(doc.getOwnerUserId()))
                        .toList();

        boolean failed = docs.stream()
                .anyMatch(doc -> "FAILED".equalsIgnoreCase(doc.getIndexStatus()));
        boolean notReady = docs.stream()
                .anyMatch(doc -> !"READY".equalsIgnoreCase(doc.getIndexStatus())
                        && !"TEXT_READY".equalsIgnoreCase(doc.getIndexStatus()));

        if (failed) {
            throw new ResponseStatusException(
                    HttpStatus.CONFLICT,
                    "첨부 문서 분석에 실패했습니다. 파일을 다시 업로드하거나 재인덱싱해주세요.");
        }

        if (notReady) {
            throw new ResponseStatusException(
                    HttpStatus.CONFLICT,
                    "첨부 문서가 아직 분석 준비 중입니다. 잠시 후 다시 시도해주세요.");
        }

        throw new ResponseStatusException(
                HttpStatus.SERVICE_UNAVAILABLE,
                "첨부 문서는 준비되어 있지만 검색 결과가 비어 있습니다. 문서 인덱스를 확인해주세요.");
    }

    private java.util.List<Long> filterOwnedDocumentIds(
            java.util.List<Long> documentIds,
            Long userId) {

        if (documentIds == null || documentIds.isEmpty()) {
            return java.util.List.of();
        }

        return documentRepository.findAllById(documentIds)
                .stream()
                .filter(doc -> userId.equals(doc.getOwnerUserId()))
                .map(com.promptune.domain.Document::getId)
                .distinct()
                .toList();
    }

    private boolean looksLikeDocumentFollowup(String prompt) {
        String text = prompt == null
                ? ""
                : prompt.trim().toLowerCase();

        if (text.isBlank()) {
            return false;
        }

        String[] markers = {
                "거기서",
                "그 문서",
                "그 파일",
                "그 이력서",
                "그 보고서",
                "해당 문서",
                "해당 파일",
                "아까 문서",
                "아까 파일",
                "아까 올린",
                "전에 올린",
                "이 문서",
                "이 파일",
                "이거",
                "이걸",
                "그거",
                "그걸",
                "그것",
                "저거",
                "방금",
                "무슨 내용",
                "각 항목",
                "각항목",
                "항목에",
                "항목은",
                "항목들",
                "어떤 항목",
                "구성은",
                "구성 항목",
                "목차",
                "더 자세히",
                "자세히 알려",
                "뭐 있는데",
                "뭐있는데",
                "내용이야",
                "내용 알려",
                "문서 요약",
                "파일 요약",
                "프로젝트만",
                "경력만",
                "확실해",
                "확실한가",
                "맞아",
                "맞나요",
                "진짜야",
                "정말이야",
                "근거 있어",
                "근거있어",
                "출처 맞아",
                "출처가 맞아",
                "다시 확인",
                "재확인"
        };

        for (String marker : markers) {
            if (text.contains(marker)) {
                return true;
            }
        }

        return false;
    }

    private String compactHistoryText(String text) {
        if (text == null || text.length() <= 1500) {
            return text;
        }

        return text.substring(0, 750)
                + "\n...[이전 대화 중략]...\n"
                + text.substring(text.length() - 750);
    }

    // generate() 결과를 검증하고, 실패 시 1회만 재생성 후 재검증.
    // 재생성 시에도 동일한 conversation history를 유지한다.
    private Map validateWithRetry(
            String originalPrompt,
            Map result,
            String taskType,
            java.util.List<java.util.Map<String, Object>> documents,
            java.util.List<java.util.Map<String, Object>> webResults,
            Map<String, String> userContext,
            Map<String, String> preferenceMap,
            java.util.List<java.util.Map<String, String>> conversationHistory) {

        Object generatedText =
                result != null
                        ? result.get("result")
                        : null;

        if (generatedText == null) {
            return result;
        }

        Map validation =
                ai.validate(
                        originalPrompt,
                        generatedText.toString(),
                        documents,
                        webResults);

        boolean passed =
                Boolean.TRUE.equals(
                        validation.get("passed"));

        if (passed) {
            return result;
        }

        Object issuesObject =
                validation.get("issues");

        String issues =
                issuesObject == null
                        ? "요청 형식 또는 근거 사실을 지키지 못했습니다."
                        : issuesObject.toString();

        String retryPrompt =
                originalPrompt
                        + "\n\n[재생성 검증 지시]"
                        + "\n이전 답변에 다음 문제가 있었습니다: "
                        + issues
                        + "\n제공된 내부 문서/웹 검색 근거에 있는 사실만 사용하세요."
                        + "\n특히 이름, 본명, 소속, 날짜, 수치 등을 추측하지 마세요."
                        + "\n이 지시문 자체는 최종 답변에서 언급하지 마세요.";

        Map retryResult =
                ai.generate(
                        retryPrompt,
                        taskType,
                        documents,
                        webResults,
                        userContext,
                        preferenceMap,
                        conversationHistory);

        Object retryText =
                retryResult != null
                        ? retryResult.get("result")
                        : null;

        if (retryText == null) {
            throw new ResponseStatusException(
                    HttpStatus.SERVICE_UNAVAILABLE,
                    "답변 생성에 실패했습니다.");
        }

        Map retryValidation =
                ai.validate(
                        originalPrompt,
                        retryText.toString(),
                        documents,
                        webResults);

        boolean retryPassed =
                Boolean.TRUE.equals(
                        retryValidation.get("passed"));

        if (!retryPassed) {
            throw new ResponseStatusException(
                    HttpStatus.SERVICE_UNAVAILABLE,
                    "검증을 통과하는 답변을 생성하지 못했습니다.");
        }

        return retryResult;
    }

    /** 0번: 사용자 맥락 (로그인 후 사전 조회) — /api/execute와 동일한 이유로 경로변수 대신 인증 기반으로 전환 */
    @GetMapping("/context")
    public Map<String, Object> context(org.springframework.security.core.Authentication authentication) {
        User currentUser = userRepository.findByEmail(authentication.getName())
                .orElseThrow(() -> new org.springframework.web.server.ResponseStatusException(
                        org.springframework.http.HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다."));
        return Map.of(
                "firstVisit", graph.isFirstVisit(currentUser.getId()),
                "workContext", graph.getUserContext(currentUser.getId()));
    }
}
