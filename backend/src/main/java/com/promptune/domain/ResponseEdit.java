package com.promptune.domain;

import jakarta.persistence.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "response_edits")
public class ResponseEdit {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "prompt_session_id", nullable = false)
    private Long promptSessionId;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "generated_result", columnDefinition = "CLOB", nullable = false)
    private String generatedResult;

    @Column(name = "user_final_result", columnDefinition = "CLOB", nullable = false)
    private String userFinalResult;

    @Column(name = "created_at")
    private LocalDateTime createdAt;

    protected ResponseEdit() {}

    public ResponseEdit(Long promptSessionId, Long userId, String generatedResult, String userFinalResult) {
        this.promptSessionId = promptSessionId;
        this.userId = userId;
        this.generatedResult = generatedResult;
        this.userFinalResult = userFinalResult;
        this.createdAt = LocalDateTime.now();
    }

    public Long getId() { return id; }
    public Long getPromptSessionId() { return promptSessionId; }
    public String getGeneratedResult() { return generatedResult; }
    public String getUserFinalResult() { return userFinalResult; }
    public LocalDateTime getCreatedAt() { return createdAt; }
}
