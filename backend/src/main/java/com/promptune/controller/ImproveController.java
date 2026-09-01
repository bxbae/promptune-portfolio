package com.promptune.controller;

import com.promptune.dto.PipelineDtos.DiagnoseResult;
import com.promptune.dto.PipelineDtos.ImproveRequest;
import com.promptune.dto.PipelineDtos.ImproveResponse;
import com.promptune.dto.PipelineDtos.ImprovePromptResult;
import com.promptune.dto.PipelineDtos.PreferenceResult;
import com.promptune.dto.PipelineDtos.PromptRuleResult;
import com.promptune.dto.PipelineDtos.SuggestResult;
import com.promptune.dto.PipelineDtos.SuggestionItem;
import com.promptune.dto.PipelineDtos.PlaceholderSuggestion;
import com.promptune.service.AiServiceClient;
import com.promptune.service.PreferenceResolutionService;

import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Phase 2-B 프롬프트 개선 준비 API.
 *
 * 흐름:
 * Authentication
 * → 사용자 Preference 조회
 * → V6 프롬프트 진단
 * → Prompt Rule 적용
 *
 * HyperCLOVA 기반 실제 개선 프롬프트 생성은 다음 Phase에서 연결한다.
 */
@RestController
@RequestMapping("/api")
public class ImproveController {

  private final AiServiceClient ai;
  private final PreferenceResolutionService preferenceResolutionService;

  public ImproveController(
      AiServiceClient ai,
      PreferenceResolutionService preferenceResolutionService) {
    this.ai = ai;
    this.preferenceResolutionService = preferenceResolutionService;
  }

  // improve_hcx.py의 _PLACEHOLDERS와 정확히 동일한 매핑 (문자 그대로 일치해야 검색됨)
  private static final java.util.Map<String, String> ELEMENT_PLACEHOLDERS = java.util.Map.of(
      "TASK", "[해야 할 작업]",
      "AUDIENCE", "[대상/수신자]",
      "CONTEXT", "[배경/상황 정보]",
      "FORMAT", "[원하는 출력 형식]",
      "TONE", "[원하는 어조]",
      "LENGTH", "[원하는 길이]",
      "CONSTRAINT", "[제약 조건]",
      "EXAMPLE", "[참고 예시]"
  );

  @PostMapping("/improve")
  public ImproveResponse improve(
      @RequestBody ImproveRequest req,
      Authentication authentication) {

    var preference = preferenceResolutionService.resolve(authentication);

    DiagnoseResult diagnose = ai.diagnose(req.text());

    PromptRuleResult promptRule = ai.promptRule(
        req.text(),
        diagnose.missing(),
        diagnose.taskType(),
        preference.speed(),
        preference.detail(),
        preference.preserve());

    ImprovePromptResult improveResult = ai.improvePrompt(
        req.text(),
        diagnose.taskType(),
        preference.speed(),
        preference.detail(),
        preference.preserve(),
        promptRule);

    // 재작성된 문장 안에 실제로 남아있는 placeholder를 찾아서, 그 자리에 채울 실제 후보를 준비
    java.util.List<String> foundElements = new java.util.ArrayList<>();
    for (String element : promptRule.missingElements()) {
        String placeholder = ELEMENT_PLACEHOLDERS.get(element);
        if (placeholder != null && improveResult.improvedPrompt().contains(placeholder)) {
            foundElements.add(element);
        }
    }

    java.util.List<PlaceholderSuggestion> placeholders = new java.util.ArrayList<>();
    if (!foundElements.isEmpty()) {
        SuggestResult suggestResult = ai.suggest(improveResult.improvedPrompt(), foundElements);
        for (SuggestionItem item : suggestResult.suggestions()) {
            String placeholderText = ELEMENT_PLACEHOLDERS.get(item.element());
            if (placeholderText != null) {
                placeholders.add(new PlaceholderSuggestion(
                        item.element(), placeholderText, item.primary(), item.alternatives()));
            }
        }
    }

    PreferenceResult preferenceResult = new PreferenceResult(
        preference.speed(),
        preference.detail(),
        preference.preserve(),
        preference.fromLoggedInUser());

    return new ImproveResponse(
        preferenceResult,
        diagnose,
        promptRule,
        improveResult.improvedPrompt(),
        improveResult.usedFallback(),
        placeholders);
  }
}
