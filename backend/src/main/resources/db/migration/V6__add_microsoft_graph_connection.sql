-- Microsoft Graph 외부 업무 계정 연결
-- Oracle 기준으로 변환 (TIMESTAMPTZ → TIMESTAMP WITH TIME ZONE)

CREATE TABLE microsoft_connections (
    user_id NUMBER(19) PRIMARY KEY,
    microsoft_user_id VARCHAR2(255),
    microsoft_email VARCHAR2(255),
    display_name VARCHAR2(255),
    token_cache_encrypted CLOB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,

    CONSTRAINT fk_microsoft_connections_user
        FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
);

CREATE TABLE microsoft_oauth_states (
    state VARCHAR2(36) PRIMARY KEY,
    user_id NUMBER(19) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,

    CONSTRAINT fk_microsoft_oauth_states_user
        FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
);

CREATE INDEX idx_es_expires_at
    ON microsoft_oauth_states(expires_at);

CREATE INDEX idx_microsoft_connections_microsoft_user
    ON microsoft_connections(microsoft_user_id);
