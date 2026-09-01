package com.promptune.domain;

import jakarta.persistence.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "documents")
public class Document {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "owner_user_id", nullable = false)
    private Long ownerUserId;

    private String title;

    @Column(name = "s3_key")
    private String s3Key;

    @Column(name = "file_type")
    private String fileType;

    @Column(columnDefinition = "CLOB")
    private String description;

    @Column(name = "document_type")
    private String documentType;   // DocumentType enum 값 중 하나 (POLICY/TEMPLATE/GUIDE/REPORT/OTHER)

    @Column(name = "prompt_session_id")
    private Long promptSessionId;  // 이 문서가 첨부된 채팅 메시지. 파일관리 탭 업로드는 null.

    @Column(name = "index_status", nullable = false)
    private String indexStatus = "UPLOADED";

    @Column(name = "index_error", columnDefinition = "CLOB")
    private String indexError;

    @Column(name = "indexed_at")
    private LocalDateTime indexedAt;

    protected Document() {}

    public Document(Long ownerUserId, String title, String s3Key, String fileType) {
        this.ownerUserId = ownerUserId;
        this.title = title;
        this.s3Key = s3Key;
        this.fileType = fileType;
        this.documentType = "OTHER";
    }

    public Long getId() { return id; }
    public Long getOwnerUserId() { return ownerUserId; }
    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }
    public String getS3Key() { return s3Key; }
    public String getFileType() { return fileType; }
    public String getDescription() { return description; }
    public void setDescription(String description) { this.description = description; }
    public String getDocumentType() { return documentType; }
    public void setDocumentType(String documentType) { this.documentType = documentType; }
    public Long getPromptSessionId() { return promptSessionId; }
    public void setPromptSessionId(Long promptSessionId) { this.promptSessionId = promptSessionId; }
    public String getIndexStatus() { return indexStatus; }
    public void setIndexStatus(String indexStatus) { this.indexStatus = indexStatus; }
    public String getIndexError() { return indexError; }
    public void setIndexError(String indexError) { this.indexError = indexError; }
    public LocalDateTime getIndexedAt() { return indexedAt; }
    public void setIndexedAt(LocalDateTime indexedAt) { this.indexedAt = indexedAt; }
}
