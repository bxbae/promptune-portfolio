package com.promptune.domain;

import jakarta.persistence.*;

import java.time.Instant;

@Entity
@Table(name = "microsoft_connections")
public class MicrosoftConnection {

    @Id
    @Column(name = "user_id")
    private Long userId;

    @Column(name = "microsoft_user_id")
    private String microsoftUserId;

    @Column(name = "microsoft_email")
    private String microsoftEmail;

    @Column(name = "display_name")
    private String displayName;

    @Column(name = "department")
    private String department;

    @Column(name = "job_title")
    private String jobTitle;

    @Column(name = "company_name")
    private String companyName;

    @Column(
        name = "token_cache_encrypted",
        nullable = false,
        columnDefinition = "CLOB"
    )
    private String tokenCacheEncrypted;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected MicrosoftConnection() {
    }

    public MicrosoftConnection(Long userId) {
        this.userId = userId;
    }

    @PrePersist
    void onCreate() {
        Instant now = Instant.now();

        if (createdAt == null) {
            createdAt = now;
        }

        updatedAt = now;
    }

    public String getDepartment() {
        return department;
    }

    public void setDepartment(String department) {
        this.department = department;
    }

    public String getCompanyName() { return companyName; }
    public void setCompanyName(String companyName) { this.companyName = companyName; }

    public String getJobTitle() {
        return jobTitle;
    }

    public void setJobTitle(String jobTitle) {
        this.jobTitle = jobTitle;
    }

    @PreUpdate
    void onUpdate() {
        updatedAt = Instant.now();
    }

    public Long getUserId() {
        return userId;
    }

    public void setUserId(Long userId) {
        this.userId = userId;
    }

    public String getMicrosoftUserId() {
        return microsoftUserId;
    }

    public void setMicrosoftUserId(String microsoftUserId) {
        this.microsoftUserId = microsoftUserId;
    }

    public String getMicrosoftEmail() {
        return microsoftEmail;
    }

    public void setMicrosoftEmail(String microsoftEmail) {
        this.microsoftEmail = microsoftEmail;
    }

    public String getDisplayName() {
        return displayName;
    }

    public void setDisplayName(String displayName) {
        this.displayName = displayName;
    }

    public String getTokenCacheEncrypted() {
        return tokenCacheEncrypted;
    }

    public void setTokenCacheEncrypted(String tokenCacheEncrypted) {
        this.tokenCacheEncrypted = tokenCacheEncrypted;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }
}
