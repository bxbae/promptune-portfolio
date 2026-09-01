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
import java.util.UUID;

// 사용자 문서 파일을 promptune-document S3 버킷에 업로드/삭제하는 서비스.
@Service
public class S3StorageService {

    private final S3Client s3Client;
    private final String documentsBucket;

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

        return s3Client.getObjectAsBytes(
                GetObjectRequest.builder()
                        .bucket(documentsBucket)
                        .key(s3Key)
                        .build()
        ).asByteArray();
    }

    public void delete(String s3Key) {
        if (s3Key == null || s3Key.isBlank()) return;
        s3Client.deleteObject(DeleteObjectRequest.builder()
                .bucket(documentsBucket)
                .key(s3Key)
                .build());
    }
}
