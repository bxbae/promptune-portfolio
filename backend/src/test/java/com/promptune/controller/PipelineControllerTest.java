package com.promptune.controller;

import com.promptune.repository.ChatSessionRepository;
import com.promptune.repository.DocumentRepository;
import com.promptune.repository.PromptSessionRepository;
import com.promptune.repository.ReceiverProfileRepository;
import com.promptune.repository.UserRepository;
import com.promptune.service.AiServiceClient;
import com.promptune.service.BehaviorLogService;
import com.promptune.service.ConsentService;
import com.promptune.service.DocumentIntentResolver;
import com.promptune.service.GateService;
import com.promptune.service.GraphMockService;
import com.promptune.service.MicrosoftGraphService;
import com.promptune.service.PreferenceResolutionService;
import com.promptune.service.RecommendService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class PipelineControllerTest {

    private AiServiceClient ai;
    private PipelineController controller;

    @BeforeEach
    void setUp() {
        GateService gate = mock(GateService.class);
        ai = mock(AiServiceClient.class);
        RecommendService recommend = mock(RecommendService.class);
        GraphMockService graph = mock(GraphMockService.class);
        UserRepository userRepository = mock(UserRepository.class);
        BehaviorLogService behaviorLog = mock(BehaviorLogService.class);
        PromptSessionRepository promptSessionRepository = mock(PromptSessionRepository.class);
        ChatSessionRepository chatSessionRepository = mock(ChatSessionRepository.class);
        ConsentService consentService = mock(ConsentService.class);
        MicrosoftGraphService microsoftGraphService = mock(MicrosoftGraphService.class);
        PreferenceResolutionService preferenceResolutionService =
                mock(PreferenceResolutionService.class);
        ReceiverProfileRepository receiverProfileRepository =
                mock(ReceiverProfileRepository.class);
        DocumentRepository documentRepository = mock(DocumentRepository.class);
        DocumentIntentResolver documentIntentResolver =
                mock(DocumentIntentResolver.class);

        controller = new PipelineController(
                gate,
                ai,
                recommend,
                graph,
                userRepository,
                behaviorLog,
                promptSessionRepository,
                chatSessionRepository,
                consentService,
                microsoftGraphService,
                preferenceResolutionService,
                receiverProfileRepository,
                documentRepository,
                documentIntentResolver);
    }

    @Test
    void validationFailure_retryPromptIncludesValidationIssues() throws Exception {
        String originalPrompt = "ORIGINAL_PROMPT_WITH_FACTS_3_8_28";

        Map<String, Object> firstResult = Map.of(
                "result",
                "FIRST_GENERATION_MISSING_FACTS");

        Map<String, Object> retryResult = Map.of(
                "result",
                "RETRY_GENERATION_WITH_FACTS_3_8_28");

        String validationIssue = "missing fact numbers: 28, 3, 8";

        Map<String, Object> failedValidation = Map.of(
                "passed", false,
                "facts_preserved", false,
                "issues", List.of(validationIssue));

        Map<String, Object> passedValidation = Map.of(
                "passed", true,
                "facts_preserved", true,
                "issues", List.of());

        when(ai.validate(eq(originalPrompt), anyString()))
                .thenReturn(failedValidation, passedValidation);

        when(ai.generate(
                anyString(),
                eq("email"),
                anyList(),
                anyList(),
                anyMap(),
                anyMap(),
                anyList()))
                .thenReturn(retryResult);

        Method method = PipelineController.class.getDeclaredMethod(
                "validateWithRetry",
                String.class,
                Map.class,
                String.class,
                List.class,
                List.class,
                Map.class,
                Map.class,
                List.class);

        method.setAccessible(true);

        method.invoke(
                controller,
                originalPrompt,
                firstResult,
                "email",
                List.of(),
                List.of(),
                Map.of(),
                Map.of(),
                List.of());

        ArgumentCaptor<String> retryPromptCaptor =
                ArgumentCaptor.forClass(String.class);

        verify(ai).generate(
                retryPromptCaptor.capture(),
                eq("email"),
                anyList(),
                anyList(),
                anyMap(),
                anyMap(),
                anyList());

        String retryPrompt = retryPromptCaptor.getValue();

        assertNotEquals(
                originalPrompt,
                retryPrompt,
                "Retry must not reuse the unchanged original prompt.");

        assertTrue(
                retryPrompt.contains(validationIssue),
                "Retry prompt must include the first validation issues.");
    }
}