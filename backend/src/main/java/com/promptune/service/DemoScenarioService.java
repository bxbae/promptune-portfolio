package com.promptune.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PostConstruct;
import java.io.IOException;
import java.io.InputStream;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.Set;
import org.springframework.core.io.Resource;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * 데모 모드(ai.demo.enabled=true, promptune-portfolio 전용)에서, 사용자가
 * 입력한 문장과 가장 비슷한 시나리오를 resources/demo-scenarios.json에서
 * 찾아주는 서비스.
 *
 * 매칭 방식: 별도 형태소 분석기 없이 한국어에도 그럭저럭 잘 동작하도록,
 * 공백을 제거한 뒤 문자 2-그램(bigram) 집합끼리 자카드 유사도(Jaccard
 * similarity)를 계산한다. "정확히 같은 문장"일 필요는 없고, 한 시나리오에
 * 여러 matchQuestions를 등록해두면 그중 가장 점수가 높은 것을 기준으로 삼는다.
 *
 * 새 시나리오를 추가하려면 demo-scenarios.json에 항목을 하나 더 넣기만 하면
 * 되고, 이 파일은 수정할 필요 없다. (docs/데모_시나리오_가이드.md 참고)
 */
@Service
public class DemoScenarioService {

    // 이 값 미만이면 "매칭되는 시나리오 없음" 취급 → 호출한 쪽에서 일반적인
    // fallback 응답을 사용한다. 낮추면 엉뚱한 시나리오가 걸리기 쉽고, 높이면
    // 표현만 살짝 달라도 못 찾게 되니 임의로 올리지 말 것.
    private static final double MATCH_THRESHOLD = 0.28;

    @Value("classpath:demo-scenarios.json")
    private Resource scenariosResource;

    private List<DemoScenario> scenarios = List.of();

    @PostConstruct
    void load() {
        try (InputStream in = scenariosResource.getInputStream()) {
            ObjectMapper mapper = new ObjectMapper();
            DemoScenario[] parsed = mapper.readValue(in, DemoScenario[].class);
            this.scenarios = List.of(parsed);
        } catch (IOException e) {
            // 데모 배포인데 파일이 없거나 JSON이 깨졌다고 서버 자체가 죽으면 안
            // 되므로, 빈 시나리오 목록으로 두고 로그만 남긴다(모든 질문이
            // fallback 응답을 받게 됨).
            this.scenarios = List.of();
            System.err.println(
                    "[DemoScenarioService] demo-scenarios.json 로드 실패 - 데모 응답이 전부 fallback으로 동작합니다: "
                            + e.getMessage());
        }
    }

    public Optional<DemoScenario> findBestMatch(String query) {
        if (query == null || query.isBlank() || scenarios.isEmpty()) {
            return Optional.empty();
        }

        Set<String> queryBigrams = bigrams(query);
        if (queryBigrams.isEmpty()) {
            return Optional.empty();
        }

        DemoScenario best = null;
        double bestScore = 0.0;

        for (DemoScenario scenario : scenarios) {
            if (scenario.matchQuestions == null) {
                continue;
            }
            for (String candidate : scenario.matchQuestions) {
                double score = jaccard(queryBigrams, bigrams(candidate));
                if (score > bestScore) {
                    bestScore = score;
                    best = scenario;
                }
            }
        }

        if (best == null || bestScore < MATCH_THRESHOLD) {
            return Optional.empty();
        }
        return Optional.of(best);
    }

    private Set<String> bigrams(String text) {
        String normalized = text.toLowerCase(Locale.ROOT).replaceAll("\\s+", "");
        Set<String> result = new HashSet<>();
        if (normalized.length() < 2) {
            if (!normalized.isEmpty()) {
                result.add(normalized);
            }
            return result;
        }
        for (int i = 0; i < normalized.length() - 1; i++) {
            result.add(normalized.substring(i, i + 2));
        }
        return result;
    }

    private double jaccard(Set<String> a, Set<String> b) {
        if (a.isEmpty() || b.isEmpty()) {
            return 0.0;
        }
        Set<String> intersection = new HashSet<>(a);
        intersection.retainAll(b);
        Set<String> union = new HashSet<>(a);
        union.addAll(b);
        return (double) intersection.size() / union.size();
    }
}
