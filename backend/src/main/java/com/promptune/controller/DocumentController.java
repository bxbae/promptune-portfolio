package com.promptune.controller;

import com.promptune.domain.Document;
import com.promptune.domain.User;
import com.promptune.dto.DocumentDtos.UpdateDocumentRequest;
import com.promptune.repository.DocumentRepository;
import com.promptune.repository.UserRepository;
import com.promptune.service.AiServiceClient;
import com.promptune.service.S3StorageService;
import com.promptune.service.DocumentTemplateResolver;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaTypeFactory;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.ByteBuffer;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.nio.charset.CodingErrorAction;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.time.LocalDateTime;

@RestController
@RequestMapping("/api/documents")
public class DocumentController {

    private final DocumentRepository documentRepository;
    private final UserRepository userRepository;
    private final S3StorageService s3StorageService;
    private final AiServiceClient aiServiceClient;
    private final DocumentTemplateResolver templateResolver;

    public DocumentController(DocumentRepository documentRepository,
                               UserRepository userRepository,
                               S3StorageService s3StorageService,
                               AiServiceClient aiServiceClient,
                               DocumentTemplateResolver templateResolver) {
        this.documentRepository = documentRepository;
        this.userRepository = userRepository;
        this.s3StorageService = s3StorageService;
        this.aiServiceClient = aiServiceClient;
        this.templateResolver = templateResolver;
    }

    // 실제 파일을 받아 S3(promptune-document 버킷)에 업로드하고, 메타데이터를 DB에 저장한다.
    // 내용(텍스트) 추출·청크 분할·임베딩 생성은 아직 이 단계의 범위가 아니라서
    // document_chunks는 생성하지 않는다 (추후 파싱 파이프라인 연동 시 추가 예정).
    @PostMapping(consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Document upload(@RequestParam("file") MultipartFile file,
                            @RequestParam("title") String title,
                            @RequestParam(value = "description", required = false) String description,
                            @RequestParam(value = "documentType", required = false) String documentType,
                            Authentication authentication) {
        if (file == null || file.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "파일이 비어있습니다.");
        }
        if (documentType != null && !documentType.isBlank() && !com.promptune.domain.DocumentType.isValid(documentType)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "documentType은 POLICY/TEMPLATE/GUIDE/REPORT/OTHER 중 하나여야 합니다.");
        }

        User user = currentUser(authentication);
        String resolvedTitle = (title == null || title.isBlank())
                ? file.getOriginalFilename()
                : title;
        resolvedTitle = resolveUniqueTitle(user.getId(), resolvedTitle);
        String fileType = extractExtension(file.getOriginalFilename());
        byte[] uploadContent =
                normalizeUploadedContent(fileType, file);

        if (fileType == null
                || !List.of("pdf", "docx", "txt", "md", "xlsx", "pptx").contains(fileType)) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "현재 AI 문서 분석은 PDF, DOCX, TXT, MD, XLSX, PPTX 형식만 지원합니다.");
        }

        String originalFilename =
                file.getOriginalFilename() == null
                        ? "file"
                        : file.getOriginalFilename();

        String uploadContentType =
                List.of("md", "txt").contains(
                        fileType.toLowerCase(Locale.ROOT))
                        ? "text/plain;charset=UTF-8"
                        : file.getContentType();

        String s3Key = s3StorageService.uploadDocument(
                user.getId(),
                originalFilename,
                uploadContentType,
                uploadContent);

        Document document = new Document(user.getId(), resolvedTitle, s3Key, fileType);
        document.setDescription(description);
        if (documentType != null && !documentType.isBlank()) {
            document.setDocumentType(documentType.toUpperCase());
        }
        document.setIndexStatus("INDEXING");
        document.setIndexError(null);
        document = documentRepository.save(document);

        // 업로드와 "AI가 읽을 수 있음"은 다른 상태다. 인덱싱 결과를 반드시 DB에 남긴다.
        try {
            java.util.Map<String, Object> indexResult =
                    aiServiceClient.indexDocument(
                            document.getId(),
                            user.getId(),
                            fileType,
                            uploadContent,
                            originalFilename);

            applyIndexResult(document, indexResult);
        } catch (Exception e) {
            document.setIndexStatus("FAILED");
            document.setIndexError(compactIndexError(e));
            System.err.println("[문서 인덱싱 실패] documentId=" + document.getId() + " / " + e.getMessage());
        }

        return documentRepository.save(document);
    }

    public record GenerateDocumentRequest(
            String title,
            String content,
            String format,
            Long templateDocumentId) {
    }

    @PostMapping(
            value = "/generate",
            consumes = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<byte[]> generateDocument(
            @RequestBody GenerateDocumentRequest req,
            Authentication authentication) {

        // 다운로드도 로그인 사용자 기능으로 유지
        User user = currentUser(authentication);

        if (req.title() == null || req.title().isBlank()) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "title은 비어 있을 수 없습니다.");
        }

        if (req.content() == null || req.content().isBlank()) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "content는 비어 있을 수 없습니다.");
        }

        if (req.format() == null || req.format().isBlank()) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "format은 비어 있을 수 없습니다.");
        }

        String format = req.format()
                .trim()
                .toLowerCase(Locale.ROOT);

        Document template = null;

        if (req.templateDocumentId() != null) {
            template = documentRepository
                    .findById(req.templateDocumentId())
                    .orElseThrow(() -> new ResponseStatusException(
                            HttpStatus.NOT_FOUND,
                            "템플릿 문서를 찾을 수 없습니다."));

            if (!template.getOwnerUserId().equals(user.getId())) {
                throw new ResponseStatusException(
                        HttpStatus.FORBIDDEN,
                        "본인 템플릿 문서만 사용할 수 있습니다.");
            }

            if (!"TEMPLATE".equalsIgnoreCase(template.getDocumentType())) {
                throw new ResponseStatusException(
                        HttpStatus.BAD_REQUEST,
                        "templateDocumentId는 TEMPLATE 문서여야 합니다.");
            }
        }

        if (!List.of("docx", "pdf", "xlsx", "txt", "md").contains(format)) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "지원 형식은 docx, pdf, xlsx, txt, md입니다.");
        }

        if (template == null) {
            String templateIntent =
                    (req.title() + " " + req.content())
                            .toLowerCase(Locale.ROOT);

            boolean wantsExistingTemplate =
                    templateIntent.contains("회사 양식")
                    || templateIntent.contains("사내 양식")
                    || templateIntent.contains("기존 양식")
                    || templateIntent.contains("내부 양식")
                    || templateIntent.contains("업로드한 양식")
                    || templateIntent.contains("회사 템플릿")
                    || templateIntent.contains("사내 템플릿")
                    || templateIntent.contains("기존 템플릿");

            if (wantsExistingTemplate) {
                template = templateResolver.resolve(
                        user.getId(),
                        req.title(),
                        req.content(),
                        format);
            }
        }

        if (template == null) {
            return aiServiceClient.generateDocument(
                    req.title().trim(),
                    req.content(),
                    format);
        }

        byte[] templateBytes =
                s3StorageService.download(template.getS3Key());

        String templateFilename = template.getTitle();

        if (template.getFileType() != null
                && !template.getFileType().isBlank()
                && !templateFilename.toLowerCase(Locale.ROOT)
                        .endsWith("." + template.getFileType()
                                .toLowerCase(Locale.ROOT))) {
            templateFilename =
                    templateFilename + "." + template.getFileType();
        }

        return aiServiceClient.generateDocument(
                req.title().trim(),
                req.content(),
                format,
                templateBytes,
                templateFilename);
    }


    @PostMapping("/{id}/reindex")
    public Document reindex(
            @PathVariable Long id,
            Authentication authentication) {

        User user = currentUser(authentication);
        Document document = documentRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(
                        HttpStatus.NOT_FOUND,
                        "문서를 찾을 수 없습니다."));

        if (!document.getOwnerUserId().equals(user.getId())) {
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN,
                    "본인 문서만 재인덱싱할 수 있습니다.");
        }

        document.setIndexStatus("INDEXING");
        document.setIndexError(null);
        documentRepository.save(document);

        try {
            byte[] bytes = s3StorageService.download(document.getS3Key());
            java.util.Map<String, Object> indexResult =
                    aiServiceClient.indexDocument(
                            document.getId(),
                            user.getId(),
                            document.getFileType(),
                            bytes,
                            document.getTitle());

            applyIndexResult(document, indexResult);
        } catch (Exception e) {
            document.setIndexStatus("FAILED");
            document.setIndexError(compactIndexError(e));
        }

        return documentRepository.save(document);
    }

    @GetMapping("/{id}/content")
    public ResponseEntity<byte[]> getDocumentContent(
            @PathVariable Long id,
            Authentication authentication) {

        User user = currentUser(authentication);

        Document document = documentRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(
                        HttpStatus.NOT_FOUND,
                        "문서를 찾을 수 없습니다."));

        if (!document.getOwnerUserId().equals(user.getId())) {
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN,
                    "본인 문서만 열람할 수 있습니다.");
        }

        byte[] content =
                s3StorageService.download(document.getS3Key());

        String extension = document.getFileType() == null
                ? ""
                : document.getFileType().toLowerCase(Locale.ROOT);

        String filename = document.getTitle();

        if (filename == null || filename.isBlank()) {
            filename = "document";
        }

        if (!extension.isBlank()
                && !filename.toLowerCase(Locale.ROOT)
                        .endsWith("." + extension)) {
            filename += "." + extension;
        }

        boolean officeFile = List.of(
                "doc", "docx",
                "xls", "xlsx",
                "ppt", "pptx"
        ).contains(extension);

        if (officeFile) {
            ResponseEntity<byte[]> preview =
                    aiServiceClient.previewDocument(
                            content,
                            filename);

            byte[] pdf = preview.getBody();

            if (pdf == null || pdf.length == 0) {
                throw new ResponseStatusException(
                        HttpStatus.INTERNAL_SERVER_ERROR,
                        "문서 미리보기 변환 결과가 비어 있습니다.");
            }

            int dot = filename.lastIndexOf(".");
            String previewFilename = dot > 0
                    ? filename.substring(0, dot) + ".pdf"
                    : filename + ".pdf";

            return ResponseEntity.ok()
                    .contentType(MediaType.APPLICATION_PDF)
                    .header(
                            HttpHeaders.CONTENT_DISPOSITION,
                            ContentDisposition.inline()
                                    .filename(
                                            previewFilename,
                                            StandardCharsets.UTF_8)
                                    .build()
                                    .toString())
                    .body(pdf);
        }

        MediaType contentType;

        if ("md".equals(extension) || "txt".equals(extension)) {
            content = normalizeTextToUtf8(content);
            contentType = MediaType.parseMediaType(
                    "text/plain;charset=UTF-8");
        } else {
            contentType = MediaTypeFactory
                    .getMediaType(filename)
                    .orElse(MediaType.APPLICATION_OCTET_STREAM);
        }

        return ResponseEntity.ok()
                .contentType(contentType)
                .header(
                        HttpHeaders.CONTENT_DISPOSITION,
                        ContentDisposition.inline()
                                .filename(
                                        filename,
                                        StandardCharsets.UTF_8)
                                .build()
                                .toString())
                .body(content);
    }

    @GetMapping
    public List<Document> myDocuments(Authentication authentication) {
        User user = currentUser(authentication);
        return documentRepository.findByOwnerUserId(user.getId());
    }

    @PatchMapping("/{id}")
    public Document update(@PathVariable Long id, @RequestBody UpdateDocumentRequest req, Authentication authentication) {
        User user = currentUser(authentication);
        Document document = documentRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "문서를 찾을 수 없습니다."));

        if (!document.getOwnerUserId().equals(user.getId())) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "본인 문서만 수정할 수 있습니다.");
        }

        // 제목·설명·문서유형은 Document 자체를 그냥 고침 (조각 재분할 대상 아님)
        if (req.title() != null) document.setTitle(req.title());
        if (req.description() != null) document.setDescription(req.description());
        if (req.documentType() != null) {
            if (!com.promptune.domain.DocumentType.isValid(req.documentType())) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                        "documentType은 POLICY/TEMPLATE/GUIDE/REPORT/OTHER 중 하나여야 합니다.");
            }
            document.setDocumentType(req.documentType().toUpperCase());
        }

        return documentRepository.save(document);
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<?> delete(@PathVariable Long id, Authentication authentication) {
        User user = currentUser(authentication);
        Document document = documentRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "문서를 찾을 수 없습니다."));

        if (!document.getOwnerUserId().equals(user.getId())) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "본인 문서만 삭제할 수 있습니다.");
        }

        documentRepository.deleteById(id);  // document_chunks는 ON DELETE CASCADE로 자동 같이 삭제됨
        s3StorageService.delete(document.getS3Key());  // S3 객체도 같이 정리
        return ResponseEntity.ok().build();
    }

    private byte[] normalizeUploadedContent(
            String fileType,
            MultipartFile file) {

        try {
            byte[] content = file.getBytes();
            String extension = fileType == null
                    ? ""
                    : fileType.toLowerCase(Locale.ROOT);

            if (List.of("md", "txt").contains(extension)) {
                return normalizeTextToUtf8(content);
            }

            return content;

        } catch (IOException e) {
            throw new UncheckedIOException(
                    "업로드 파일 읽기 실패: " + e.getMessage(),
                    e);
        }
    }

    private byte[] normalizeTextToUtf8(byte[] content) {
        if (content.length >= 3
                && content[0] == (byte) 0xEF
                && content[1] == (byte) 0xBB
                && content[2] == (byte) 0xBF) {
            return Arrays.copyOfRange(
                    content,
                    3,
                    content.length);
        }

        boolean utf16Bom =
                content.length >= 2
                && (
                    (
                        content[0] == (byte) 0xFF
                        && content[1] == (byte) 0xFE
                    )
                    || (
                        content[0] == (byte) 0xFE
                        && content[1] == (byte) 0xFF
                    )
                );

        if (utf16Bom) {
            String text = new String(
                    content,
                    StandardCharsets.UTF_16);
            return text.getBytes(StandardCharsets.UTF_8);
        }

        if (isValidUtf8(content)) {
            return content;
        }

        String text = new String(
                content,
                Charset.forName("MS949"));

        return text.getBytes(StandardCharsets.UTF_8);
    }

    private boolean isValidUtf8(byte[] content) {
        try {
            StandardCharsets.UTF_8
                    .newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(content));

            return true;

        } catch (Exception e) {
            return false;
        }
    }

    private User currentUser(Authentication authentication) {
        if (authentication == null || !authentication.isAuthenticated()) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "로그인이 필요합니다.");
        }
        return userRepository.findByEmail(authentication.getName())
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다."));
    }

    private void applyIndexResult(
            Document document,
            java.util.Map<String, Object> indexResult) {

        String status = indexResult == null
                ? ""
                : String.valueOf(indexResult.getOrDefault("status", ""));

        if ("ready".equalsIgnoreCase(status)
                || "indexed".equalsIgnoreCase(status)) {
            document.setIndexStatus("READY");
            document.setIndexError(null);
            document.setIndexedAt(LocalDateTime.now());
            return;
        }

        if ("text_ready".equalsIgnoreCase(status)) {
            document.setIndexStatus("TEXT_READY");
            Object error = indexResult.get("embedding_error");
            document.setIndexError(error == null ? null : error.toString());
            document.setIndexedAt(LocalDateTime.now());
            return;
        }

        document.setIndexStatus("FAILED");
        document.setIndexError("알 수 없는 문서 인덱싱 상태: " + status);
    }

    private String compactIndexError(Exception e) {
        String message = e == null || e.getMessage() == null
                ? "문서 인덱싱에 실패했습니다."
                : e.getMessage().trim();

        if (message.length() > 1000) {
            return message.substring(0, 1000);
        }

        return message;
    }

    // 같은 사용자가 같은 제목의 문서를 이미 갖고 있으면 "제목 (2)", "제목 (3)"처럼
    // 번호를 붙여서 구분한다. 덮어쓰기는 다른 대화가 참조 중인 파일 내용이
    // 조용히 바뀔 위험이 있어 채택하지 않음 (팀 결정).
    private String resolveUniqueTitle(Long ownerUserId, String desiredTitle) {
        List<Document> existing = documentRepository.findByOwnerUserId(ownerUserId);
        java.util.Set<String> existingTitles = new java.util.HashSet<>();
        for (Document d : existing) {
            existingTitles.add(d.getTitle());
        }

        if (!existingTitles.contains(desiredTitle)) {
            return desiredTitle;
        }

        int counter = 2;
        String candidate;
        do {
            candidate = desiredTitle + " (" + counter + ")";
            counter++;
        } while (existingTitles.contains(candidate));

        return candidate;
    }

    private String extractExtension(String filename) {
        if (filename == null) return null;
        int dot = filename.lastIndexOf('.');
        if (dot < 0 || dot == filename.length() - 1) return null;
        return filename.substring(dot + 1).toLowerCase(Locale.ROOT);
    }
}
