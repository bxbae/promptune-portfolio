package com.promptune.service;

import com.promptune.dto.PipelineDtos.GateResult;
import org.springframework.stereotype.Service;
import java.util.regex.Pattern;

/**
 * 3번 실시간 게이트 검사 (금칙어·개인정보).
 * 규칙 기반이라 목업도 실제로 동작한다. (형기 담당 - 백엔드/Rule Engine)
 */
@Service
public class GateService {

    // 주민번호·전화번호 등 PII 패턴 (예시)
    private static final Pattern PII = Pattern.compile(
            "\\d{6}[- ]?\\d{7}|01[0-9][- ]?\\d{3,4}[- ]?\\d{4}");
    private static final String[] BANNED = {
            "시발", "씨발", "개새끼",           // 비속어 예시
            "내부 매출", "미공개 실적", "인수합병" // 회사 기밀 관련 예시
    };

    public GateResult check(String text) {
        if (PII.matcher(text).find()) {
            return new GateResult(false, "개인정보(PII) 포함 감지");
        }
        for (String w : BANNED) {
            if (text.contains(w)) {
                return new GateResult(false, "금칙어 포함: " + w);
            }
        }
        return new GateResult(true, "");
    }
}
