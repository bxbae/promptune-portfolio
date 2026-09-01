package com.promptune.domain;

import jakarta.persistence.*;

@Entity
@Table(name = "document_chunks")
public class DocumentChunk {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "document_id", nullable = false)
    private Long documentId;

    @Column(name = "chunk_index")
    private Integer chunkIndex;

    @Column(columnDefinition = "CLOB")
    private String content;

    protected DocumentChunk() {}

    public DocumentChunk(Long documentId, Integer chunkIndex, String content) {
        this.documentId = documentId;
        this.chunkIndex = chunkIndex;
        this.content = content;
    }

    public Long getId() { return id; }
    public Long getDocumentId() { return documentId; }
    public Integer getChunkIndex() { return chunkIndex; }
    public String getContent() { return content; }
}