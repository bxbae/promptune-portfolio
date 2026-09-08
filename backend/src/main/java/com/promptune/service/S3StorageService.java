package com.promptune.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.DeleteObjectRequest;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;

// 사용자 문서 파일을 promptune-document S3 버킷에 업로드/삭제하는 서비스.
@Service
public class S3StorageService {

    private final S3Client s3Client;
    private final String documentsBucket;

    // 2026-09-08: promptune-portfolio(데모 배포)는 diagnose/suggest/retrievalExecute/
    // generate/indexDocument처럼 실제 외부 인프라 없이 동작해야 하는데, S3만 여기 빠져
    // 있었다. 이 Render 서비스에는 실제 AWS 자격 증명이 없어서(발급/비용이 드는 진짜
    // 인프라라 데모용으로 두지 않음) 파일 첨부 때마다
    // "Unable to load credentials from any of the providers in the chain" 로
    // 즉시 실패하는 걸 로그로 확인함. 데모 모드일 땐 S3 대신 컨테이너 로컬 디스크에
    // 저장/조회하도록 우회한다 - 재배포되면 사라지지만(임시 파일이라 원래 그런 성격),
    // 데모 시연 중에는 업로드/다운로드가 정상 동작한다.
    @Value("${ai.demo.enabled:false}")
    private boolean demoEnabled;

    private static final Path DEMO_STORAGE_ROOT =
            Path.of(System.getProperty("java.io.tmpdir"), "promptune-demo-documents");

    public S3StorageService(S3Client s3Client,
                             @Value("${app.aws.s3.documents-bucket}") String documentsBucket) {
        this.s3Client = s3Client;
        this.documentsBucket = documentsBucket;
    }

    // documents/{userId}/{uuid}-{원본파일명} 형태의 key로 업로드하고, 그 key를 반환한다.
    // (원본 파일명은 그대로 두면 경로에 못 쓰는 문자가 섞일 수 있어 영숫자/일부 기호 외엔 _로 치환)
    public String uploadDocument(
            Long userId,
            MultipartFile file) {

        String original = file.getOriginalFilename() == null
                ? "file"
                : file.getOriginalFilename();

        try {
            return uploadDocument(
                    userId,
                    original,
                    file.getContentType(),
                    file.getBytes());
        } catch (IOException e) {
            throw new UncheckedIOException(
                    "업로드 파일 읽기 실패: " + e.getMessage(),
                    e);
        }
    }

    public String uploadDocument(
            Long userId,
            String originalFilename,
            String contentType,
            byte[] content) {

        String original =
                originalFilename == null ? "file" : originalFilename;

        String safeName =
                original.replaceAll("[^a-zA-Z0-9._-]", "_");

        String key = "documents/"
                + userId
                + "/"
                + UUID.randomUUID()
                + "-"
                + safeName;

        if (demoEnabled) {
            writeDemoFile(key, content);
            return key;
        }

        s3Client.putObject(
                PutObjectRequest.builder()
                        .bucket(documentsBucket)
                        .key(key)
                        .contentType(contentType)
                        .build(),
                RequestBody.fromBytes(content));

        return key;
    }

    public byte[] download(String s3Key) {
        if (s3Key == null || s3Key.isBlank()) {
            throw new IllegalArgumentException("S3 key가 비어 있습니다.");
        }

        if (demoEnabled) {
            return readDemoFile(s3Key);
        }

        return s3Client.getObjectAsBytes(
                GetObjectRequest.builder()
                        .bucket(documentsBucket)
                        .key(s3Key)
                        .build()
        ).asByteArray();
    }

    public void delete(String s3Key) {
        if (s3Key == null || s3Key.isBlank()) return;

        if (demoEnabled) {
            try {
                Files.deleteIfExists(resolveDemoPath(s3Key));
            } catch (IOException e) {
                // 데모 로컬 파일 정리 실패는 조용히 무시 - 임시 파일이라 치명적이지 않음.
            }
            return;
        }

        s3Client.deleteObject(DeleteObjectRequest.builder()
                .bucket(documentsBucket)
                .key(s3Key)
                .build());
    }

    private Path resolveDemoPath(String s3Key) {
        return DEMO_STORAGE_ROOT.resolve(s3Key);
    }

    private void writeDemoFile(String s3Key, byte[] content) {
        try {
            Path path = resolveDemoPath(s3Key);
            Files.createDirectories(path.getParent());
            Files.write(path, content);
        } catch (IOException e) {
            throw new UncheckedIOException(
                    "데모 로컬 저장 실패: " + e.getMessage(),
                    e);
        }
    }

    private byte[] readDemoFile(String s3Key) {
        try {
            return Files.readAllBytes(resolveDemoPath(s3Key));
        } catch (IOException e) {
            throw new UncheckedIOException(
                    "데모 로컬 파일 읽기 실패: " + e.getMessage(),
                    e);
        }
    }
}
