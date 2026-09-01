package com.promptune.service;

import com.promptune.domain.Document;
import com.promptune.repository.DocumentRepository;
import org.springframework.stereotype.Service;

import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.Set;

@Service
public class DocumentTemplateResolver {

    private static final Set<String> STOP_WORDS = Set.of(
            "작성", "생성", "만들어", "만들어줘",
            "문서", "양식", "템플릿",
            "회사", "사내", "표준",
            "내용", "관련", "대한", "부탁", "해줘"
    );

    private final DocumentRepository documentRepository;

    public DocumentTemplateResolver(
            DocumentRepository documentRepository) {
        this.documentRepository = documentRepository;
    }

    public Document resolve(
            Long ownerUserId,
            String requestTitle,
            String requestContent,
            String outputFormat) {

        String requestText = normalize(
                safe(requestTitle) + " " + safe(requestContent));

        String requestKind = detectKind(requestText);

        List<Document> candidates =
                documentRepository.findByOwnerUserId(ownerUserId)
                        .stream()
                        .filter(d -> "TEMPLATE".equalsIgnoreCase(
                                d.getDocumentType()))
                        .filter(d -> isCompatible(
                                d.getFileType(),
                                outputFormat))
                        .toList();

        Document best = candidates.stream()
                .map(d -> new ScoredDocument(
                        d,
                        score(requestText, requestKind, d)))
                .filter(x -> x.score() >= 4)
                .max(Comparator
                        .comparingInt(ScoredDocument::score)
                        .thenComparingLong(
                                x -> x.document().getId()))
                .map(ScoredDocument::document)
                .orElse(null);

        if (best != null) {
            System.out.println(
                    "[템플릿 자동 선택] documentId="
                            + best.getId()
                            + " / title="
                            + best.getTitle());
        }

        return best;
    }

    private int score(
            String requestText,
            String requestKind,
            Document template) {

        String templateText = normalize(
                safe(template.getTitle())
                        + " "
                        + safe(template.getDescription()));

        String templateKind = detectKind(templateText);

        if (requestKind != null
                && templateKind != null
                && !requestKind.equals(templateKind)) {
            return -1000;
        }

        int score = 0;

        if (requestKind != null
                && requestKind.equals(templateKind)) {
            score += 10;
        }

        for (String token :
                templateText.split("[^가-힣a-z0-9]+")) {

            if (token.length() < 2
                    || STOP_WORDS.contains(token)) {
                continue;
            }

            if (requestText.contains(token)) {
                score += 2;
            }
        }

        return score;
    }

    private boolean isCompatible(
            String fileType,
            String outputFormat) {

        if (fileType == null || outputFormat == null) {
            return false;
        }

        return fileType.trim()
                .equalsIgnoreCase(outputFormat.trim());
    }

    private String detectKind(String text) {
        if (containsAny(
                text,
                "시말서", "경위서", "사유서", "소명서")) {
            return "FORMAL_STATEMENT";
        }

        if (containsAny(
                text,
                "장애보고", "사고보고",
                "장애 보고", "사고 보고",
                "장애", "사고 발생")) {
            return "INCIDENT";
        }

        if (containsAny(
                text,
                "회의록", "회의", "미팅")) {
            return "MEETING";
        }

        if (containsAny(
                text,
                "제안서", "제안")) {
            return "PROPOSAL";
        }

        if (containsAny(
                text,
                "인수인계")) {
            return "HANDOVER";
        }

        if (containsAny(
                text,
                "공지사항", "공지", "안내문")) {
            return "NOTICE";
        }

        if (containsAny(
                text,
                "계획서", "실행계획", "추진계획")) {
            return "PLAN";
        }

        if (containsAny(
                text,
                "요약", "요약문")) {
            return "SUMMARY";
        }

        if (containsAny(
                text,
                "업무보고", "주간보고",
                "월간보고", "보고서")) {
            return "REPORT";
        }

        return null;
    }

    private boolean containsAny(
            String text,
            String... keywords) {

        for (String keyword : keywords) {
            if (text.contains(keyword)) {
                return true;
            }
        }

        return false;
    }

    private String normalize(String value) {
        return safe(value)
                .toLowerCase(Locale.ROOT)
                .replaceAll("\\s+", " ")
                .trim();
    }

    private String safe(String value) {
        return value == null ? "" : value;
    }

    private record ScoredDocument(
            Document document,
            int score) {
    }
}
