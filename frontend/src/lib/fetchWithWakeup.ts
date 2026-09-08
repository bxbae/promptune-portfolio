// 2026-09-08: Render 무료 플랜은 15분간 요청이 없으면 백엔드가 슬립 상태로
// 들어가고, 다음 요청이 와야 다시 깨어나는데 콜드스타트(Oracle DB 연결 +
// Flyway + Hibernate 초기화 포함)에 최대 2분 가까이 걸릴 수 있다. 그 사이
// Render 프록시가 502/503/504를 돌려주거나, 아예 커넥션 자체가 실패
// (TypeError: Failed to fetch)하기도 한다.
//
// lib/auth.ts의 postWithWakeup()이 로그인/회원가입에서는 이미 이 문제를
// 재시도로 흡수하고 있는데, 파일 첨부(uploadDocument)나 실행(execute) 같은
// 다른 API 호출에는 이 재시도가 전혀 없었다 - 그래서 대화 중간에 서버가
// 잠들면 로그인은 (사용자 입장에서 눈치 못 채게) 재시도되며 성공하는데,
// 바로 이어지는 파일 첨부/실행은 502/503으로 즉시 실패해버리는 비대칭이
// 있었다. 이 헬퍼는 그 재시도 로직을 auth.ts와 동일한 지연 간격으로
// 일반화해서, JSON이든 FormData(멀티파트)든 임의의 fetch 호출에 씌울 수
// 있게 한다.
const WAKEUP_RETRY_DELAYS_MS = [3000, 6000, 10000, 15000, 20000, 25000, 30000, 30000];

function isWakingUp(res: Response): boolean {
  return res.status === 502 || res.status === 503 || res.status === 504;
}

// doFetch는 매 시도마다 새로 호출된다 - FormData/File을 담은 요청도 File
// 자체는 재사용 가능한 Blob이라 안전하게 다시 보낼 수 있다.
export async function fetchWithWakeupRetry(
  doFetch: () => Promise<Response>,
  onWaking?: (attempt: number, maxAttempts: number) => void,
): Promise<Response> {
  const maxAttempts = WAKEUP_RETRY_DELAYS_MS.length + 1;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const res = await doFetch();

      if (isWakingUp(res) && attempt < maxAttempts) {
        onWaking?.(attempt, maxAttempts);
        await new Promise((r) => setTimeout(r, WAKEUP_RETRY_DELAYS_MS[attempt - 1]));
        continue;
      }

      // 마지막 시도까지 502/503/504면 그대로 반환 - 호출부가 기존처럼
      // res.ok 체크를 통해 에러 메시지를 만들도록 둔다.
      return res;
    } catch (e) {
      // AbortController로 의도적으로 취소한 요청(예: 타이핑 중 이전 analyze/execute
      // 요청을 취소)까지 재시도하면 안 된다 - 사용자가 취소한 요청이 재시도로
      // 되살아나는 건 명백한 버그이므로 즉시 그대로 던진다.
      if (e instanceof DOMException && e.name === "AbortError") {
        throw e;
      }

      // 네트워크 자체가 끊긴 경우(TypeError: Failed to fetch)도 콜드스타트
      // 초반에는 흔히 발생하므로 같은 재시도 경로를 탄다.
      if (attempt < maxAttempts) {
        onWaking?.(attempt, maxAttempts);
        await new Promise((r) => setTimeout(r, WAKEUP_RETRY_DELAYS_MS[attempt - 1]));
        continue;
      }
      throw e;
    }
  }

  throw new Error("서버로부터 응답을 받지 못했습니다.");
}
