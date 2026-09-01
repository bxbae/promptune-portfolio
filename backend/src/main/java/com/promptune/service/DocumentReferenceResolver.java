package com.promptune.service;

import com.promptune.domain.Document;

import java.text.Normalizer;
import java.util.*;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * 파일관리 내부문서 locator.
 *
 * 책임:
 * 1. 사용자의 자연어에서 기존 내부문서를 찾으려는 의도를 판별한다.
 * 2. title / description / document_type을 deterministic하게 점수화한다.
 * 3. metadata만으로 애매하면 BGE-M3 검색 결과를 받아 document_id 단위로 재랭킹한다.
 *
 * 이 클래스는 문서 본문 답변을 생성하지 않는다.
 * document_id만 확정한 뒤 기존 document-scoped RAG에 넘기는 것이 핵심이다.
 */
public final class DocumentReferenceResolver {

    private DocumentReferenceResolver() {}

    private static final Pattern CREATE_PATTERN =
            Pattern.compile("(만들어|생성해|작성해|작성해줘|만들어줘|생성해줘)");

    private static final Pattern DOCUMENT_PATTERN =
            Pattern.compile(
                    "(문서|파일|양식|서식|템플릿|규정|정책|가이드|지침|보고서|회의록|계획서|제안서)");

    private static final Pattern LOOKUP_PATTERN =
            Pattern.compile(
                    "(찾아|알려|뭐|무슨|어떤|내용|요약|보여|읽어|확인|어디|있어|불러)");

    private static final Pattern EXPLICIT_CATALOG_PATTERN =
            Pattern.compile(
                    "(파일\\s*관리|파일관리|내부\\s*문서|내부문서|사내\\s*문서|사내문서|"
                            + "업로드한|업로드해둔|올려둔|올린\\s*파일|저장한\\s*문서|등록한\\s*문서)");

    private static final Pattern EXISTING_TEMPLATE_PATTERN =
            Pattern.compile(
                    "((회사|사내|기존).*(양식|서식|템플릿)|(양식|서식|템플릿).*(회사|사내|기존))");

    private static final Pattern PLURAL_PATTERN =
            Pattern.compile("(문서들|파일들|관련\\s*문서|관련\\s*파일|모두|전부|전체)");

    private static final Set<String> STOP_WORDS = Set.of(
            "이거", "이걸", "그거", "그걸", "그것", "저거",
            "문서", "파일", "내용", "알려줘", "알려", "해줘",
            "무슨", "어떤", "관련", "대한", "에서", "으로",
            "파일관리", "업로드한", "올려둔", "올린", "저장한",
            "회사", "사내", "내부", "기존"
    );

    public record Candidate(
            Long documentId,
            String title,
            String documentType,
            double score) {}

    public record Resolution(
            List<Long> documentIds,
            String source,
            double confidence,
            List<Candidate> candidates) {

        public boolean found() {
            return documentIds != null && !documentIds.isEmpty();
        }

        public static Resolution none() {
            return new Resolution(
                    List.of(),
                    "NONE",
                    0.0,
                    List.of());
        }
    }

    public static boolean shouldSearchCatalog(String prompt) {
        String text = normalize(prompt);

        if (text.isBlank()) {
            return false;
        }

        boolean explicitCatalog =
                EXPLICIT_CATALOG_PATTERN.matcher(text).find();

        boolean existingTemplate =
                EXISTING_TEMPLATE_PATTERN.matcher(text).find();

        boolean create =
                CREATE_PATTERN.matcher(text).find();

        /*
         * "보고서 만들어줘"는 Smart Document 생성이어야 한다.
         * 회사/사내/기존 양식 또는 파일관리 문서를 명시했을 때만
         * 기존 내부문서 locator가 개입한다.
         */
        if (create && !explicitCatalog && !existingTemplate) {
            return false;
        }

        if (explicitCatalog || existingTemplate) {
            return true;
        }

        return DOCUMENT_PATTERN.matcher(text).find()
                && LOOKUP_PATTERN.matcher(text).find();
    }

    public static Resolution resolveMetadata(
            String prompt,
            List<Document> documents) {

        if (documents == null || documents.isEmpty()) {
            return Resolution.none();
        }

        List<Candidate> ranked = documents.stream()
                .filter(Objects::nonNull)
                .filter(DocumentReferenceResolver::isReadable)
                .map(doc -> new Candidate(
                        doc.getId(),
                        safe(doc.getTitle()),
                        safe(doc.getDocumentType()),
                        metadataScore(prompt, doc)))
                .filter(candidate -> candidate.score() > 0.0)
                .sorted(Comparator.comparingDouble(Candidate::score).reversed())
                .toList();

        if (ranked.isEmpty()) {
            return Resolution.none();
        }

        // 문서 종류 keyword보다 실제 보유 파일의 title identity가 더 강한 신호다.
        // 따라서 "이력서", "계약서", "발표자료"...를 Router에 끝없이 추가하지 않는다.
        Document strongTitleDocument = documents.stream()
                .filter(Objects::nonNull)
                .filter(DocumentReferenceResolver::isReadable)
                .max(Comparator.comparingDouble(
                        doc -> titleReferenceScore(prompt, doc.getTitle())))
                .orElse(null);

        double strongTitleScore =
                strongTitleDocument == null
                        ? 0.0
                        : titleReferenceScore(
                                prompt,
                                strongTitleDocument.getTitle());

        if (strongTitleDocument != null && strongTitleScore >= 0.84) {
            Candidate titleCandidate = new Candidate(
                    strongTitleDocument.getId(),
                    safe(strongTitleDocument.getTitle()),
                    safe(strongTitleDocument.getDocumentType()),
                    strongTitleScore);

            java.util.List<Candidate> candidates =
                    new java.util.ArrayList<>();

            candidates.add(titleCandidate);

            ranked.stream()
                    .filter(candidate ->
                            !Objects.equals(
                                    candidate.documentId(),
                                    strongTitleDocument.getId()))
                    .limit(4)
                    .forEach(candidates::add);

            return new Resolution(
                    List.of(strongTitleDocument.getId()),
                    strongTitleScore >= 0.98
                            ? "CATALOG_TITLE_EXACT"
                            : "CATALOG_TITLE_REFERENCE",
                    strongTitleScore,
                    candidates);
        }

        // title로 특정 파일을 가리키지 않는 일반 요청에 대해서만
        // 기존 catalog-intent gate를 적용한다.
        // 따라서 "보고서 만들어줘"가 사내 파일을 멋대로 선택하는 회귀는 막는다.
        if (!shouldSearchCatalog(prompt)) {
            return Resolution.none();
        }

        Candidate top = ranked.get(0);

        String queryCompact = compact(prompt);
        String titleCompact = compact(stripExtension(top.title()));

        boolean exactTitle =
                titleCompact.length() >= 3
                        && queryCompact.contains(titleCompact);

        if (exactTitle) {
            return new Resolution(
                    List.of(top.documentId()),
                    "CATALOG_METADATA_EXACT",
                    Math.max(0.98, top.score()),
                    ranked.subList(0, Math.min(5, ranked.size())));
        }

        if (PLURAL_PATTERN.matcher(normalize(prompt)).find()) {
            double floor = Math.max(0.55, top.score() - 0.15);

            List<Long> ids = ranked.stream()
                    .filter(candidate -> candidate.score() >= floor)
                    .limit(3)
                    .map(Candidate::documentId)
                    .toList();

            if (!ids.isEmpty() && top.score() >= 0.58) {
                return new Resolution(
                        ids,
                        "CATALOG_METADATA_MULTI",
                        top.score(),
                        ranked.subList(0, Math.min(5, ranked.size())));
            }
        }

        if (top.score() < 0.58) {
            return Resolution.none();
        }

        if (ranked.size() > 1) {
            double margin = top.score() - ranked.get(1).score();

            /*
             * metadata만으로 두 파일이 거의 같은 점수라면 억지로 하나를 고르지 않는다.
             * 이 경우 BGE semantic fallback으로 넘긴다.
             */
            if (margin < 0.08 && top.score() < 0.84) {
                return Resolution.none();
            }
        }

        return new Resolution(
                List.of(top.documentId()),
                "CATALOG_METADATA",
                top.score(),
                ranked.subList(0, Math.min(5, ranked.size())));
    }

    public static Resolution resolveSemantic(
            String prompt,
            List<Map<String, Object>> retrievedChunks,
            List<Document> ownedDocuments) {

        if (!shouldSearchCatalog(prompt)
                || retrievedChunks == null
                || retrievedChunks.isEmpty()
                || ownedDocuments == null
                || ownedDocuments.isEmpty()) {
            return Resolution.none();
        }

        Map<Long, Document> owned = ownedDocuments.stream()
                .filter(Objects::nonNull)
                .filter(DocumentReferenceResolver::isReadable)
                .collect(Collectors.toMap(
                        Document::getId,
                        document -> document,
                        (a, b) -> a));

        Map<Long, Double> semanticScores = new HashMap<>();

        for (Map<String, Object> chunk : retrievedChunks) {
            if (chunk == null) {
                continue;
            }

            Long documentId = asLong(chunk.get("document_id"));

            if (documentId == null || !owned.containsKey(documentId)) {
                continue;
            }

            double score = asDouble(chunk.get("score"));

            semanticScores.merge(
                    documentId,
                    score,
                    Math::max);
        }

        if (semanticScores.isEmpty()) {
            return Resolution.none();
        }

        List<Candidate> ranked = semanticScores.entrySet().stream()
                .map(entry -> {
                    Document document = owned.get(entry.getKey());

                    double metadata =
                            metadataScore(prompt, document);

                    /*
                     * BGE가 본문 의미를 잡고,
                     * metadata(title/description/type)가 tie-breaker 역할을 한다.
                     */
                    double combined =
                            (entry.getValue() * 0.75)
                                    + (metadata * 0.25);

                    return new Candidate(
                            document.getId(),
                            safe(document.getTitle()),
                            safe(document.getDocumentType()),
                            Math.min(1.0, combined));
                })
                .sorted(Comparator.comparingDouble(Candidate::score).reversed())
                .toList();

        if (ranked.isEmpty()) {
            return Resolution.none();
        }

        Candidate top = ranked.get(0);

        if (top.score() < 0.50) {
            return Resolution.none();
        }

        if (PLURAL_PATTERN.matcher(normalize(prompt)).find()) {
            double floor = Math.max(0.50, top.score() - 0.12);

            List<Long> ids = ranked.stream()
                    .filter(candidate -> candidate.score() >= floor)
                    .limit(3)
                    .map(Candidate::documentId)
                    .toList();

            return new Resolution(
                    ids,
                    "CATALOG_SEMANTIC_MULTI",
                    top.score(),
                    ranked.subList(0, Math.min(5, ranked.size())));
        }

        if (ranked.size() > 1) {
            double margin =
                    top.score() - ranked.get(1).score();

            if (margin < 0.04 && top.score() < 0.72) {
                return Resolution.none();
            }
        }

        return new Resolution(
                List.of(top.documentId()),
                "CATALOG_SEMANTIC",
                top.score(),
                ranked.subList(0, Math.min(5, ranked.size())));
    }

    private static double titleReferenceScore(
            String prompt,
            String rawTitle) {

        String queryCompact = compact(prompt);
        String title = stripExtension(rawTitle);
        String titleCompact = compact(title);

        if (queryCompact.isBlank()
                || titleCompact.isBlank()
                || titleCompact.length() < 3) {
            return 0.0;
        }

        // 파일명을 거의 그대로 말한 경우.
        if (queryCompact.contains(titleCompact)) {
            return 1.0;
        }

        Set<String> titleTokens = tokens(title);

        if (titleTokens.isEmpty()) {
            return 0.0;
        }

        java.util.List<String> matched =
                titleTokens.stream()
                        .filter(token ->
                                token.length() >= 2
                                        && queryCompact.contains(compact(token)))
                        .toList();

        // 예: title="차승연 프로젝트 이력서 초안"
        // query="차승연 이력서에 무슨 내용 있어?"
        // -> 차승연 + 이력서 두 identity token이 겹치므로 강한 파일 참조.
        if (matched.size() >= 3) {
            return 0.95;
        }

        if (matched.size() >= 2) {
            return 0.88;
        }

        // Spectrum, SeungyeonCha처럼 충분히 긴 고유 토큰 하나도
        // 파일 identity로 사용할 수 있다.
        if (matched.size() == 1
                && matched.get(0).length() >= 6) {
            return 0.84;
        }

        return 0.0;
    }

    private static double metadataScore(
            String prompt,
            Document document) {

        String query = normalize(prompt);
        String queryCompact = compact(prompt);

        String title = normalize(stripExtension(document.getTitle()));
        String titleCompact = compact(stripExtension(document.getTitle()));

        String description = normalize(document.getDescription());

        Set<String> queryTokens = tokens(query);
        Set<String> titleTokens = tokens(title);
        Set<String> descriptionTokens = tokens(description);

        double score = 0.0;

        if (!titleCompact.isBlank()
                && titleCompact.length() >= 3
                && queryCompact.contains(titleCompact)) {
            score = Math.max(score, 1.0);
        }

        double titleOverlap =
                coverage(titleTokens, queryTokens);

        double descriptionOverlap =
                coverage(queryTokens, descriptionTokens);

        score = Math.max(
                score,
                (titleOverlap * 0.68)
                        + (descriptionOverlap * 0.22)
                        + typeBoost(prompt, document.getDocumentType()));

        /*
         * 긴 설명 문장 전체가 query에 들어오지는 않더라도
         * 핵심 단어가 여러 개 겹치면 description을 강하게 반영한다.
         */
        if (descriptionOverlap >= 0.50) {
            score += 0.08;
        }

        return Math.min(1.0, score);
    }

    private static double typeBoost(
            String prompt,
            String documentType) {

        String text = normalize(prompt);
        String type = safe(documentType).toUpperCase(Locale.ROOT);

        boolean matches =
                ("TEMPLATE".equals(type)
                        && containsAny(text, "양식", "서식", "템플릿"))
                || ("POLICY".equals(type)
                        && containsAny(text, "규정", "정책", "원칙"))
                || ("GUIDE".equals(type)
                        && containsAny(text, "가이드", "지침", "방법", "작성법"))
                || ("REPORT".equals(type)
                        && containsAny(text, "보고서", "결과보고", "업무보고"));

        return matches ? 0.16 : 0.0;
    }

    private static boolean isReadable(Document document) {
        String status = safe(document.getIndexStatus());

        if (status.isBlank()) {
            return true;
        }

        return "READY".equalsIgnoreCase(status)
                || "TEXT_READY".equalsIgnoreCase(status);
    }

    private static Set<String> tokens(String value) {
        String normalized = normalize(value);

        if (normalized.isBlank()) {
            return Set.of();
        }

        Set<String> out = new LinkedHashSet<>();

        for (String token : normalized.split("\\s+")) {
            String cleaned =
                    token.replaceAll("[^가-힣a-z0-9]", "");

            if (cleaned.length() < 2
                    || STOP_WORDS.contains(cleaned)) {
                continue;
            }

            out.add(cleaned);
        }

        return out;
    }

    private static double coverage(
            Set<String> target,
            Set<String> source) {

        if (target == null
                || source == null
                || target.isEmpty()
                || source.isEmpty()) {
            return 0.0;
        }

        long matched = target.stream()
                .filter(source::contains)
                .count();

        return (double) matched / target.size();
    }

    private static String normalize(String value) {
        String text = safe(value);

        text = Normalizer.normalize(
                text,
                Normalizer.Form.NFC);

        text = text.toLowerCase(Locale.ROOT);

        text = text.replaceAll(
                "\\.(pdf|docx?|xlsx?|pptx?|txt|md)$",
                "");

        text = text.replace('_', ' ')
                .replace('-', ' ')
                .replace('.', ' ');

        text = text.replaceAll(
                "[^가-힣a-z0-9\\s]",
                " ");

        return text.replaceAll("\\s+", " ").trim();
    }

    private static String compact(String value) {
        return normalize(value)
                .replace(" ", "");
    }

    private static String stripExtension(String value) {
        return safe(value).replaceFirst(
                "(?i)\\.(pdf|docx?|xlsx?|pptx?|txt|md)$",
                "");
    }

    private static boolean containsAny(
            String value,
            String... needles) {

        for (String needle : needles) {
            if (value.contains(needle)) {
                return true;
            }
        }

        return false;
    }

    private static String safe(String value) {
        return value == null ? "" : value.trim();
    }

    private static Long asLong(Object value) {
        if (value instanceof Number number) {
            return number.longValue();
        }

        if (value == null) {
            return null;
        }

        try {
            return Long.parseLong(value.toString());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static double asDouble(Object value) {
        if (value instanceof Number number) {
            return number.doubleValue();
        }

        if (value == null) {
            return 0.0;
        }

        try {
            return Double.parseDouble(value.toString());
        } catch (NumberFormatException e) {
            return 0.0;
        }
    }
}
