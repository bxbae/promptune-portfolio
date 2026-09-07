package com.promptune.service;

import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.regex.Pattern;

/**
 * 현재 발화와 직전 대화 문맥을 함께 보고 문서 생성 실행 여부를 결정한다.
 *
 * 핵심 원칙
 * - 문서 생성 의도가 명확하면 추가 질문보다 실행을 우선한다.
 * - 일반 문서 생성 / 빈 양식 생성 / 사내 기존 양식 사용을 구분한다.
 * - "업무보고서", "ㅇㅇ", "파일로 만들어줘" 같은 후속 발화는 직전 턴을 이어받는다.
 */
@Service
public class DocumentIntentResolver {

    public record DocumentAction(
            String title,
            String content,
            String format,
            boolean useExistingTemplate) {
    }

    // 2026-09-07: "이 양식대로 나오게 해줘", "이 양식대로 나오게 고쳐줘", "양식도
    // 받을 수 있도록 해줘"처럼 "만들어줘/작성해줘"류의 정형화된 동사 없이도
    // 실제로는 같은 "파일로 달라"는 요청인 자연스러운 말투가 있어서 추가했다.
    // (원래는 "나오게"/"고쳐 줘"/"받을 수 있"만으로 판단하면 문서와 무관한
    // 요청까지 오작동할 수 있지만, 이 패턴은 항상 DOCUMENT_NOUN/FILE_NOUN이
    // 같이 있어야만 실제로 매칭에 쓰인다 - directDocumentRequest 참고)
    private static final Pattern CREATE_VERB = Pattern.compile(
            "(만들어(?:줘)?|생성해(?:줘)?|작성해(?:줘)?|써줘|제작해(?:줘)?"
                    + "|나오게|고쳐\\s*줘|받을?\\s*수\\s*있(?:게|도록))");

    private static final Pattern DOCUMENT_NOUN = Pattern.compile(
            "(업무\\s*보고서|주간\\s*보고서|월간\\s*보고서|보고서|실적\\s*보고|성과\\s*관리|회의록|계획서|제안서|시말서|경위서|사유서|소명서|공지문|안내문|문서|양식|템플릿)");

    private static final Pattern FILE_NOUN = Pattern.compile(
            "(파일|pdf|워드|word|docx|엑셀|excel|xlsx|마크다운|markdown|텍스트파일|txt|ppt|파워포인트|슬라이드|프레젠테이션)",
            Pattern.CASE_INSENSITIVE);

    private static final Pattern AFFIRMATIVE = Pattern.compile(
            "^(응|ㅇㅇ+|네|예|그래|좋아|맞아|그렇게\\s*해줘|해줘|그걸로\\s*해줘|이걸로\\s*해줘)[.!?~\\s]*$",
            Pattern.CASE_INSENSITIVE);

    // detectTitle()이 어떤 구체적인 보고서 종류도 못 찾았을 때 쓰는 폴백 제목.
    // resolve()에서 "현재 발화에 구체적인 문서 종류가 있는지" 판단할 때도
    // 재사용한다(중복 문자열 방지).
    private static final String FALLBACK_TITLE = "PrompTune 생성 문서";

    public Optional<DocumentAction> resolve(
            String currentPrompt,
            List<Map<String, String>> history) {

        String current = safe(currentPrompt).trim();

        if (current.isBlank()) {
            return Optional.empty();
        }

        String previousUser = previous(history, "user");
        String previousAssistant = previous(history, "assistant");

        boolean hasCreateVerb = CREATE_VERB.matcher(current).find();
        boolean hasDocumentNoun = DOCUMENT_NOUN.matcher(current).find();
        boolean hasFileNoun = FILE_NOUN.matcher(current).find();

        boolean directDocumentRequest =
                hasCreateVerb && (hasDocumentNoun || hasFileNoun);

        // 2026-09-07: "이 문서 파일로 만들어줘", "위 내용 문서로 만들어줘"처럼
        // DOCUMENT_NOUN이 있어도 "문서/양식/템플릿" 같은 범용 단어뿐이고 실제
        // 보고서 종류(업무보고서/성과관리 실적보고서 등)를 이번 발화에서 다시
        // 언급하지 않는 경우가 있다. 예전에는 hasDocumentNoun이 true라는
        // 이유만으로 directDocumentRequest의 "현재 발화만 보는" 분기로 빠져서
        // 직전 대화 맥락을 완전히 무시했고, 그 결과 제목/서식을 못 찾아 제목
        // 없는 "PrompTune 생성 문서" 목업이 나갔다. 현재 발화 자체에 구체적인
        // 문서 종류가 없으면(=detectTitle이 폴백 제목을 줄 것이면) FILE_NOUN만
        // 있을 때와 마찬가지로 직전 대화 맥락(contextualFileRequest)을 쓴다.
        boolean currentHasSpecificTitleHint =
                !FALLBACK_TITLE.equals(detectTitle(current, ""));

        boolean contextualFileRequest =
                hasCreateVerb
                        && (hasFileNoun || hasDocumentNoun)
                        && !currentHasSpecificTitleHint
                        && !previousAssistant.isBlank();

        boolean typeOnlyFollowup =
                hasDocumentNoun
                        && !hasCreateVerb
                        && previousTurnWasDocumentClarification(
                                previousUser,
                                previousAssistant);

        boolean affirmativeFollowup =
                AFFIRMATIVE.matcher(current).matches()
                        && previousTurnWasDocumentConfirmation(
                                previousUser,
                                previousAssistant);

        if (!directDocumentRequest
                && !contextualFileRequest
                && !typeOnlyFollowup
                && !affirmativeFollowup) {
            return Optional.empty();
        }

        String intentContext;
        String source;

        if (contextualFileRequest) {
            intentContext = previousUser + "\n" + previousAssistant + "\n" + current;
            // 2026-09-08: 예전에는 source = previousAssistant만 썼는데,
            // previousAssistant가 실제 보고서 내용이 아니라 "미리 준비된
            // 질문에 대해서만 답변할 수 있어요" 같은 일반 안내문일 수도
            // 있다. 그 경우 이번 발화(current)에 있는 진짜 키워드("성과관리
            // 실적보고 파일로 만들어줘"의 "성과관리 실적보고")가 content에서
            // 통째로 빠져버려서, 서식 매칭(resolveDemoTemplateKey)이 참고할
            // 텍스트가 하나도 안 남았다. current를 항상 같이 포함해서 이런
            // 경우에도 매칭 키워드가 유지되게 한다 - previousAssistant가
            // 실제 내용을 담고 있는 정상 케이스에서는 그냥 문장 하나가 더
            // 붙는 것뿐이라 해가 되지 않는다.
            source = (previousAssistant + "\n" + current).trim();
        } else if (typeOnlyFollowup) {
            intentContext = previousUser + "\n" + current;
            source = previousUser
                    + "\n\n사용자가 선택한 문서 유형: "
                    + current;
        } else if (affirmativeFollowup) {
            intentContext = previousUser + "\n" + previousAssistant;
            source = previousUser.isBlank()
                    ? previousAssistant
                    : previousUser;
        } else {
            intentContext = current;
            source = current;
        }

        String title = detectTitle(current, intentContext);
        boolean templateRequest = containsTemplateRequest(intentContext);
        boolean useExistingTemplate = wantsExistingTemplate(intentContext);
        String format = detectFormat(current, intentContext, templateRequest);

        String content = enrichDocumentRequest(
                source,
                title,
                templateRequest);

        return Optional.of(
                new DocumentAction(
                        title,
                        content,
                        format,
                        useExistingTemplate));
    }

    private boolean previousTurnWasDocumentClarification(
            String previousUser,
            String previousAssistant) {

        boolean previousCreateRequest =
                CREATE_VERB.matcher(previousUser).find()
                        && (DOCUMENT_NOUN.matcher(previousUser).find()
                        || FILE_NOUN.matcher(previousUser).find());

        boolean assistantAskedType = containsAny(
                previousAssistant,
                "어떤 종류",
                "무슨 보고서",
                "어떤 보고서",
                "종류를",
                "구체적으로 말씀",
                "업무보고서로");

        return previousCreateRequest && assistantAskedType;
    }

    private boolean previousTurnWasDocumentConfirmation(
            String previousUser,
            String previousAssistant) {

        boolean documentContext =
                DOCUMENT_NOUN.matcher(previousUser + " " + previousAssistant).find()
                        || FILE_NOUN.matcher(previousUser + " " + previousAssistant).find();

        boolean assistantAskedConfirmation = containsAny(
                previousAssistant,
                "만들어드릴까요",
                "만들까요",
                "생성해드릴까요",
                "작성해드릴까요",
                "파일로 만들어",
                "제공해 드릴까요",
                "제공해드릴까요");

        return documentContext && assistantAskedConfirmation;
    }

    private String detectTitle(
            String current,
            String context) {

        String text = (current + "\n" + context).replaceAll("\\s+", " ");

        if (containsAny(text, "회의록")) return "회의록";
        // 2026-09-08: "성과관리 실적보고 파일로 만들어줘"처럼 "실적보고서"가
        // 아니라 "실적보고"(끝에 "서"가 없는 형태)나 "성과관리"만 언급하는
        // 경우가 있다. AiServiceClient.resolveDemoTemplateKey()는 이미
        // "성과관리"/"성과 관리"/"실적보고"/"실적 보고"를 최우선으로 찾는데,
        // 정작 여기 detectTitle()에는 이 키워드가 전혀 없어서 제목을 못 찾고
        // "PrompTune 생성 문서" 폴백으로 빠진 뒤, 그 폴백 제목만으로는 어떤
        // 서식인지 다시 못 찾는 악순환이 있었다("PrompTune 생성 문서.pdf"
        // 버그의 또 다른 재발 경로). resolveDemoTemplateKey와 동일한 키워드로
        // 맞춘다.
        if (containsAny(text, "성과관리", "성과 관리", "실적보고", "실적 보고")) {
            return "성과관리 실적보고서";
        }
        if (containsAny(text, "주간 업무보고", "주간 보고")) return "주간 업무보고서";
        if (containsAny(text, "월간 업무보고", "월간 보고")) return "월간 업무보고서";
        if (containsAny(text, "업무보고")) return "업무보고서";
        if (containsAny(text, "보고서 양식", "보고서 템플릿")) return "보고서 양식";
        if (containsAny(text, "보고서")) return "업무보고서";
        if (containsAny(text, "계획서")) return "계획서";
        if (containsAny(text, "제안서")) return "제안서";
        if (containsAny(text, "시말서")) return "시말서";
        if (containsAny(text, "경위서")) return "경위서";
        if (containsAny(text, "사유서")) return "사유서";
        if (containsAny(text, "소명서")) return "소명서";
        if (containsAny(text, "공지문")) return "공지문";
        if (containsAny(text, "안내문")) return "안내문";

        return FALLBACK_TITLE;
    }

    private String detectFormat(
            String current,
            String context,
            boolean templateRequest) {

        String text = (current + "\n" + context).toLowerCase();

        if (containsAny(text, "워드", "word", "docx")) {
            return "docx";
        }

        if (containsAny(text, "ppt", "파워포인트", "슬라이드", "프레젠테이션")) {
            return "pptx";
        }

        if (containsAny(text, "ppt", "파워포인트", "슬라이드", "프레젠테이션")) {
            return "pptx";
        }

        if (containsAny(text, "엑셀", "excel", "xlsx", "스프레드시트")) {
            return "xlsx";
        }

        if (containsAny(text, "마크다운", "markdown", ".md")) {
            return "md";
        }

        if (containsAny(text, "텍스트파일", "txt", "메모장")) {
            return "txt";
        }

        if (containsAny(text, "pdf")) {
            return "pdf";
        }

        if (templateRequest) {
            return "docx";
        }

        // 문서 생성의 기본값은 사용자가 바로 확인 가능한 PDF.
        return "pdf";
    }

    private boolean containsTemplateRequest(String text) {
        return containsAny(text, "양식", "템플릿", "작성용");
    }

    private boolean wantsExistingTemplate(String text) {
        String normalized = safe(text).toLowerCase();

        return containsAny(
                normalized,
                "회사 양식",
                "사내 양식",
                "기존 양식",
                "내부 양식",
                "업로드한 양식",
                "회사 템플릿",
                "사내 템플릿",
                "기존 템플릿");
    }

    private String enrichDocumentRequest(
            String source,
            String title,
            boolean templateRequest) {

        String base = safe(source).trim();

        if (templateRequest) {
            return base + "\n\n"
                    + "[문서 생성 규칙]\n"
                    + "추가 질문하지 말고 바로 편집 가능한 빈 양식을 생성하세요.\n"
                    + "제공되지 않은 사실은 만들지 말고 빈칸 또는 작성용 placeholder로 두세요.\n"
                    + "제목, 기본정보, 핵심 섹션, 표/목록, 작성란을 포함해 실제 업무에서 바로 사용할 수 있게 구성하세요.";
        }

        StringBuilder rule = new StringBuilder();
        rule.append(base).append("\n\n")
                .append("[문서 생성 규칙]\n")
                .append("정보가 부족해도 추가 질문하지 말고 합리적인 기본 업무 문서를 먼저 생성하세요.\n")
                .append("제공되지 않은 사람, 날짜, 수치, 회사 정보는 만들지 말고 빈칸 또는 작성용 placeholder로 두세요.\n");

        if (title.contains("보고서")) {
            rule.append("보고서에는 작성일, 작성부서, 작성자, 주요 업무, 진행 현황, 성과, 이슈/리스크, 향후 계획을 목적에 맞게 포함하세요.\n");
        }

        return rule.toString().trim();
    }

    private String previous(
            List<Map<String, String>> history,
            String role) {

        if (history == null || history.isEmpty()) {
            return "";
        }

        for (int i = history.size() - 1; i >= 0; i--) {
            Map<String, String> message = history.get(i);

            if (role.equals(message.get("role"))) {
                String content = safe(message.get("content")).trim();

                if (!content.isBlank()) {
                    return content;
                }
            }
        }

        return "";
    }

    private boolean containsAny(String text, String... keywords) {
        String value = safe(text).toLowerCase();

        for (String keyword : keywords) {
            if (value.contains(keyword.toLowerCase())) {
                return true;
            }
        }

        return false;
    }

    private String safe(String value) {
        return value == null ? "" : value;
    }
}
