#!/bin/bash
# .env.production 안의 진짜 민감한 값(DB 비밀번호, JWT 시크릿, 소셜 로그인 클라이언트 시크릿 등)을
# 더 이상 평문 파일로 직접 관리하지 않고, AWS SSM Parameter Store(/promptune/prod/*)에서 매 배포마다
# 새로 받아와 .env.production에 채워 넣는다.
#
# 사전 조건:
#   1. EC2 인스턴스에 SSM 파라미터 읽기 권한이 있는 IAM 역할(promptune-ec2-s3-role)이 붙어있어야 함
#      (ssm:GetParameter, ssm:GetParametersByPath, kms:Decrypt — via kms:ViaService=ssm.<region>.amazonaws.com)
#   2. 아래 SECRET_KEYS 각각에 대해 /promptune/prod/<KEY> 이름으로 SecureString 파라미터가 이미 등록돼 있어야 함
#   3. .env.production에 나머지 비-시크릿 설정(URL, 클라이언트 ID, USE_REAL_* 플래그 등)은 그대로 남아있어야 함
#      — 이 스크립트는 시크릿 7개 라인만 지우고 새로 채워 넣고, 나머지 라인은 건드리지 않음
#
# 사용법:
#   ./scripts/fetch-secrets.sh              # ~/promptune-mockup/.env.production 대상
#   ./scripts/fetch-secrets.sh <파일경로>     # 다른 경로 지정 시

set -euo pipefail

ENV_FILE="${1:-.env.production}"
REGION="${AWS_REGION:-ap-northeast-2}"
SSM_PATH="/promptune/prod"

SECRET_KEYS=(
  SPRING_DATASOURCE_PASSWORD
  JWT_SECRET
  GOOGLE_CLIENT_SECRET
  KAKAO_CLIENT_SECRET
  NAVER_CLIENT_SECRET
  MICROSOFT_CLIENT_SECRET
  MICROSOFT_TOKEN_KEY
  HF_TOKEN
  # 2026-08-25: 웹검색(retrieval-execute의 external_or_realtime 라우트)에 필요.
  # 이게 없으면 ai-service가 [Retrieval] execute failed: TAVILY_API_KEY가 없습니다
  # 로 실패하고(backend는 fail-open으로 흡수하지만 웹검색 없이 진행됨), 특히
  # "오늘 환율"/"실시간 주가" 같은 요청은 실제 데이터를 못 가져와 답변 품질이 떨어짐.
  TAVILY_API_KEY
)

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI가 설치돼 있지 않습니다. (EC2 Amazon Linux 2023엔 기본 설치돼 있어야 함)" >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "$ENV_FILE 파일이 없습니다. 먼저 비-시크릿 설정값이 담긴 $ENV_FILE(.env.production.example 참고)을 준비해주세요." >&2
  exit 1
fi

echo "SSM Parameter Store(${SSM_PATH})에서 시크릿 ${#SECRET_KEYS[@]}개를 가져오는 중... (region: ${REGION})"

TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

# 1) 기존 파일에서 시크릿 키 라인만 제거 (재실행해도 중복 안 쌓이도록). 나머지 라인은 그대로 보존.
PATTERN="^($(IFS='|'; echo "${SECRET_KEYS[*]}"))="
grep -vE "$PATTERN" "$ENV_FILE" > "$TMP_FILE" || true

# 2) SSM에서 최신 값을 가져와 새로 추가
for KEY in "${SECRET_KEYS[@]}"; do
  VALUE="$(aws ssm get-parameter \
    --name "${SSM_PATH}/${KEY}" \
    --with-decryption \
    --region "$REGION" \
    --query 'Parameter.Value' \
    --output text)"
  echo "${KEY}=${VALUE}" >> "$TMP_FILE"
done

mv "$TMP_FILE" "$ENV_FILE"
trap - EXIT
chmod 600 "$ENV_FILE"

echo "완료: ${ENV_FILE}에 시크릿 ${#SECRET_KEYS[@]}개를 SSM에서 최신값으로 갱신했습니다."
