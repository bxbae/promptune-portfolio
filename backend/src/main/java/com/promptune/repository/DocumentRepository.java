package com.promptune.repository;

import com.promptune.domain.Document;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

public interface DocumentRepository extends JpaRepository<Document, Long> {
    List<Document> findByOwnerUserId(Long ownerUserId);

    // 파일관리 화면 전용: 채팅으로 한 번이라도 실제 전송에 쓰인(prompt_session_documents에
    // 연결된) 문서는 제외하고 보여준다. 첨부만 하고 아직 전송 전인 문서는
    // 아직 이 테이블에 연결이 안 됐을 수 있어 잠깐 보일 수 있음(알려진 한계).
    @Query(value = """
            SELECT d.*
            FROM documents d
            WHERE d.owner_user_id = :ownerUserId
              AND NOT EXISTS (
                  SELECT 1 FROM prompt_session_documents psd
                  WHERE psd.document_id = d.id
              )
            ORDER BY d.id DESC
            """, nativeQuery = true)
    List<Document> findLibraryDocumentsByOwnerUserId(
            @Param("ownerUserId") Long ownerUserId);

    // 메서드 이름은 기존 호출부 호환을 유지하되 실제 관계는
    // prompt_session_documents(N:M) 연결 테이블에서 읽는다.
    @Query(value = """
            SELECT d.*
            FROM documents d
            JOIN prompt_session_documents psd
              ON psd.document_id = d.id
            WHERE psd.prompt_session_id = :promptSessionId
            ORDER BY psd.id ASC
            """, nativeQuery = true)
    List<Document> findByPromptSessionId(
            @Param("promptSessionId") Long promptSessionId);

    // Oracle Cloud Free 마이그레이션: ON CONFLICT (...) DO NOTHING은 PostgreSQL 전용 문법이라
    // Oracle에서 동일하게 "이미 있으면 건너뛰기"를 하는 MERGE로 옮김.
    @Modifying
    @Transactional
    @Query(value = """
            MERGE INTO prompt_session_documents tgt
            USING (SELECT :promptSessionId AS prompt_session_id, :documentId AS document_id FROM dual) src
            ON (tgt.prompt_session_id = src.prompt_session_id AND tgt.document_id = src.document_id)
            WHEN NOT MATCHED THEN
                INSERT (prompt_session_id, document_id)
                VALUES (src.prompt_session_id, src.document_id)
            """, nativeQuery = true)
    void linkPromptSessionDocument(
            @Param("promptSessionId") Long promptSessionId,
            @Param("documentId") Long documentId);
}
