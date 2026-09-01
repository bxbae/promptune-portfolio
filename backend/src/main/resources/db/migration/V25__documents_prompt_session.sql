ALTER TABLE documents
  ADD prompt_session_id NUMBER(19)
  REFERENCES prompt_sessions(id) ON DELETE SET NULL;

CREATE INDEX idx_documents_prompt_session_id ON documents(prompt_session_id);
