package com.promptune.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;
import java.util.Map;

/**
 * 백엔드 파이프라인 DTO 모음.
 * 프론트 ↔ 백엔드 ↔ ai-service 간 데이터 형식(계약서).
 * ai-service는 snake_case, 백엔드/프론트는 camelCase → @JsonProperty로 매핑.
 */
public class PipelineDtos {

        public record AnalyzeRequest(String text, Long userId) {
        }

        public record GateResult(boolean passed, String reason) {
        }

        // 5번 ai-service /diagnose 응답. snake_case JSON을 camelCase로 매핑.
        public record DiagnoseResult(
                        Map<String, Integer> missing,
                        @JsonProperty("task_type") String taskType,
                        List<Map<String, String>> typos,
                        @JsonProperty("needs_internal_docs") boolean needsInternalDocs) {
        }

        public record RecommendResult(List<String> targetElements) {
        }

        // 7번 ai-service /suggest 응답
        public record SuggestionAnchor(
                        @JsonAlias("sentence_index") int sentenceIndex,
                        @JsonAlias("char_offset") int charOffset) {
        }

        public record SuggestionItem(
                        String element,
                        String primary,
                        List<String> alternatives,
                        SuggestionAnchor anchor) {
        }

        public record SuggestResult(
                        List<SuggestionItem> suggestions) {
        }

        public record AnalyzeResponse(
                        GateResult gate,
                        DiagnoseResult diagnose,
                        RecommendResult recommend,
                        SuggestResult suggest) {
        }

        public record ElementAction(String element, String action) {
                // action: "tab"(적용) 또는 "esc"(거절). 방향키(단순 탐색)는 기록 안 함.
        }

        public record ExecuteRequest(String finalPrompt, Long userId, Long chatSessionId,
                        List<ElementAction> elementActions, Boolean useWebSearch, Long receiverProfileId,
                        List<Long> documentIds) {
                // useWebSearch: 사용자가 "웹에서 확인" 버튼을 눌렀을 때만 true. 안 보내면(null) false로 처리.
                // receiverProfileId: 이 프롬프트가 특정 수신자 앞으로 가는 경우, 그 사람의
                // receiver_profile.id. 안 보내면(null) 수신자 톤 반영 없이 기존과 동일하게 동작.
                // documentIds: 이 메시지에 첨부된 문서 id 목록. 안 보내면(null) 첨부 없음.
        }

        public record ClassifyResult(
                        @JsonProperty("task_type") String taskType,
                        @JsonProperty("needs_internal_docs") boolean needsInternalDocs) {
        }

        public record BehaviorLog(Long userId, String action, String element) {
        }

        // Phase 2-B: Preference + V6 진단 + Prompt Rule 통합
        public record ImproveRequest(String text) {
        }

        public record PreferenceResult(
                        String speed,
                        String detail,
                        String preserve,
                        boolean fromLoggedInUser) {
        }

        // ai-service /prompt-rule 응답
        public record PromptRuleResult(
                        @JsonProperty("missing_elements") List<String> missingElements,
                        @JsonProperty("use_role") boolean useRole,
                        @JsonProperty("role_hint") String roleHint,
                        @JsonProperty("decompose_task") boolean decomposeTask,
                        @JsonProperty("use_positive_instruction") boolean usePositiveInstruction,
                        @JsonProperty("use_few_shot") boolean useFewShot) {
        }

        // ai-service /api/ai/improve-prompt 응답
        public record ImprovePromptResult(
                        @JsonProperty("improved_prompt") String improvedPrompt,
                        @JsonProperty("used_fallback") boolean usedFallback) {
        }

        public record ImproveResponse(
                        PreferenceResult preference,
                        DiagnoseResult diagnose,
                        PromptRuleResult promptRule,
                        String improvedPrompt,
                        boolean usedFallback,
                        List<PlaceholderSuggestion> placeholders) {
        }

        // improvedPrompt 안에 실제로 남아있는 placeholder마다, 그 자리를 채울 실제 후보 문구.
        // placeholderText는 improvedPrompt 안에서 이 문구를 찾아 밑줄 긋는 용도(프론트에서 문자열 검색).
        public record PlaceholderSuggestion(
                        String element,
                        String placeholderText,
                        String primary,
                        List<String> alternatives) {
        }
}
