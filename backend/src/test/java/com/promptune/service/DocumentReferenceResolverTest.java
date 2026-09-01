package com.promptune.service;

import com.promptune.domain.Document;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class DocumentReferenceResolverTest {

    private Document resume() throws Exception {
        Document document = new Document(
                4L,
                "차승연_프로젝트_이력서_초안.pdf",
                "users/4/resume.pdf",
                "pdf");

        document.setIndexStatus("READY");
        document.setDocumentType("OTHER");
        document.setDescription(
                "차승연의 프로젝트 및 AI 엔지니어 경력을 정리한 이력서 초안");

        Field id = Document.class.getDeclaredField("id");
        id.setAccessible(true);
        id.set(document, 20L);

        return document;
    }

    @Test
    void exactFilenameWorksWithoutDocumentKeywordDictionary() throws Exception {
        var result = DocumentReferenceResolver.resolveMetadata(
                "차승연_프로젝트_이력서_초안.pdf 불러와줘",
                List.of(resume()));

        assertTrue(result.found());
        assertEquals(List.of(20L), result.documentIds());
    }

    @Test
    void naturalTitleReferenceWorksWithoutAddingResumeKeyword() throws Exception {
        var result = DocumentReferenceResolver.resolveMetadata(
                "차승연 이력서에 무슨내용있어?",
                List.of(resume()));

        assertTrue(result.found());
        assertEquals(List.of(20L), result.documentIds());
    }

    @Test
    void ordinaryReportGenerationDoesNotAutoSelectLibraryDocument() throws Exception {
        var result = DocumentReferenceResolver.resolveMetadata(
                "보고서 만들어줘",
                List.of(resume()));

        assertFalse(result.found());
    }
}
