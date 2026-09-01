package com.promptune.dto;

import java.time.LocalDateTime;
import java.util.List;

public class ChatSessionDtos {
    public record UpdateTitleRequest(String title) {}
    public record DocumentSummary(Long id, String title) {}
    public record MessageResponse(Long id, String prompt, String aiResponse, String taskType, LocalDateTime createdAt, String satisfaction, List<DocumentSummary> attachments) {}
}
