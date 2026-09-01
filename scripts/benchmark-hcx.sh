#!/bin/bash
# CPU(t3.large) vs GPU(g4dn.xlarge 등) 인스턴스에서 HyperCLOVA X 생성 속도를
# 같은 방식으로 측정하기 위한 스크립트. 양쪽 인스턴스에서 각각 실행하고
# 출력된 표를 그대로 비교하면 된다.
#
# 측정 항목: 모델 로딩 시간 / 첫 요청 시간 / 워밍업 후 3회 평균 / 각 응답 텍스트
# (응답 텍스트는 CPU/GPU 결과 품질을 눈으로 비교할 수 있게 파일로 저장)
#
# 주의: 컨테이너를 재시작해서 모델을 "콜드 스타트"시키므로, prod(CPU)
# 인스턴스에서 돌리면 그동안 실제 사용자 요청이 잠깐 끊긴다. 트래픽 적은
# 시간에 실행하거나, 이미 서비스 중인 CPU 인스턴스는 재시작 없이(이미
# 로드된 상태로) 3~4회 요청만 재서 "모델 로딩 시간"만 생략하고 비교해도 된다.
#
# 사용법:
#   ./scripts/benchmark-hcx.sh <compose파일> [ai-service 서비스명]
#   예) ./scripts/benchmark-hcx.sh docker-compose.prod.yml ai-service   # CPU
#       ./scripts/benchmark-hcx.sh docker-compose.gpu.yml ai-service    # GPU

set -euo pipefail

COMPOSE_FILE="${1:?사용법: $0 <compose파일> [서비스명]}"
SERVICE="${2:-ai-service}"
ENV_FILE=".env.production"
PORT="8000"
OUT_DIR="benchmark-results/$(date +%Y%m%d-%H%M%S 2>/dev/null || echo run)"

mkdir -p "$OUT_DIR"

# 실제 프로덕션에서 반복 재현됐던 것과 동일한 형태의 요청(웹검색 결과 포함,
# 동일 프롬프트, 동일 생성 토큰 상한 750 — generate_hcx.py의 max_new_tokens와 일치)
REQUEST_BODY='{
  "prompt": "오늘 환율 알려주고 실시간 주가 요약확인해줘. 또한 담당자에게. 이번 분기 상황에서. 3문단으로. 정중한 어조로. 숫자는 꼭 포함해서",
  "task_type": "email",
  "documents": [],
  "web_results": [
    {"title": "원달러 환율 동향", "url": "https://example.com/fx", "content": "오늘 원/달러 환율은 1,320원대에서 등락을 반복했다. 전일 대비 소폭 상승 마감했으며, 미국 금리 발표를 앞두고 관망세가 이어지고 있다."},
    {"title": "국내 증시 요약", "url": "https://example.com/stock", "content": "코스피는 2,650선에서 강보합 마감했다. 반도체 업종이 강세를 보였고, 외국인 순매수가 이어졌다."}
  ],
  "user_context": {},
  "preference": {"speed": "normal", "detail": "normal", "preserve": "normal"},
  "history": []
}'

echo "=== [1/4] 컨테이너 재시작 (모델 콜드 스타트) ==="
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --force-recreate "$SERVICE"

echo "=== [2/4] 서버 기동 대기 ==="
for i in $(seq 1 30); do
  if curl -s -o /dev/null -w '' "http://localhost:${PORT}/docs" 2>/dev/null; then
    break
  fi
  sleep 1
done

run_request() {
  local label="$1"
  local out_file="$OUT_DIR/${label}.json"
  local start end
  start=$(date +%s.%N)
  curl -s -X POST "http://localhost:${PORT}/api/ai/generate" \
    -H "Content-Type: application/json" \
    -d "$REQUEST_BODY" -o "$out_file"
  end=$(date +%s.%N)
  # bc가 없는 환경(Amazon Linux 등)도 있어 awk로 계산 (bc 의존성 제거)
  awk -v s="$start" -v e="$end" 'BEGIN { printf "%.2f", e - s }'
}

echo "=== [3/4] 첫 요청 (모델 로딩 + 첫 생성 포함) ==="
FIRST_TOTAL=$(run_request "request-1-first")
echo "첫 요청 총 소요시간: ${FIRST_TOTAL}s"

LOAD_SECONDS=$(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" logs "$SERVICE" 2>&1 \
  | grep -oP 'load_seconds=\K[0-9.]+' | tail -1 || echo "")

echo "모델 로딩 시간(로그에서 추출): ${LOAD_SECONDS:-확인불가}s"

echo "=== [4/4] 워밍업 후 3회 요청 ==="
TOTAL=0
for i in 1 2 3; do
  T=$(run_request "request-warm-$i")
  echo "  요청 $i: ${T}s"
  # bc가 없는 환경(Amazon Linux 등)도 있어 awk로 계산 (bc 의존성 제거)
  TOTAL=$(awk -v a="$TOTAL" -v b="$T" 'BEGIN { printf "%.2f", a + b }')
done
AVG=$(awk -v t="$TOTAL" 'BEGIN { printf "%.2f", t / 3 }')

echo ""
echo "================= 결과 요약 ================="
echo "compose 파일        : $COMPOSE_FILE"
echo "모델 로딩 시간        : ${LOAD_SECONDS:-확인불가}s"
if [ -n "$LOAD_SECONDS" ]; then
  # bc가 없는 환경(Amazon Linux 등)도 있어 awk로 계산 (bc 의존성 제거)
  FIRST_GEN_ONLY=$(awk -v f="$FIRST_TOTAL" -v l="$LOAD_SECONDS" 'BEGIN { printf "%.2f", f - l }')
  echo "첫 요청(생성만, 로딩 제외): ${FIRST_GEN_ONLY}s"
fi
echo "첫 요청(총, 로딩 포함)  : ${FIRST_TOTAL}s"
echo "워밍업 후 3회 평균     : ${AVG}s"
echo "응답 텍스트 저장 위치   : $OUT_DIR/"
echo "==============================================="
echo ""
echo "결과 텍스트 비교는:"
echo "  cat $OUT_DIR/request-1-first.json | python3 -m json.tool"
