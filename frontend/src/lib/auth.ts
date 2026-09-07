// 인증 API 호출 + 토큰 관리
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export interface AuthResponse { token: string; email: string; name: string; }

// Render 무료 플랜은 15분간 요청이 없으면 백엔드가 슬립 상태로 들어가고,
// 다음 요청이 와야 다시 깨어나는데 콜드스타트(Oracle DB 연결 + Flyway +
// Hibernate 초기화 포함)에 2분 넘게 걸릴 수 있다. 그 사이 Render 프록시가
// 먼저 502/503/504를 (JSON이 아닌 HTML로) 돌려주는 경우가 많아서, 그대로
// res.json()을 호출하면 파싱 에러로 죽어버리고 사용자에게는 알 수 없는
// 에러만 보인다. 아래 두 헬퍼는 그 상황을 "서버가 깨어나는 중"으로 인식해
// 자동으로 재시도하고, 진행 상황을 onWaking 콜백으로 알려준다.
const WAKEUP_RETRY_DELAYS_MS = [3000, 6000, 10000, 15000, 20000, 25000, 30000, 30000];

async function parseErrorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.clone().json();
    if (data && typeof data.error === "string") return data.error;
  } catch {
    // JSON이 아님 (Render의 502/503 HTML 페이지 등) — 아래 fallback 사용
  }
  return fallback;
}

function isWakingUp(res: Response): boolean {
  return res.status === 502 || res.status === 503 || res.status === 504;
}

// 실제 API가 응답한 "진짜" 에러(예: 비밀번호 불일치, 이메일 중복 등).
// 재시도해도 결과가 바뀌지 않으므로 즉시 사용자에게 보여준다.
class TerminalAuthError extends Error {}

async function postWithWakeup(
  path: string,
  body: unknown,
  fallbackErrorMessage: string,
  onWaking?: (attempt: number, maxAttempts: number) => void
): Promise<AuthResponse> {
  const maxAttempts = WAKEUP_RETRY_DELAYS_MS.length + 1;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const res = await fetch(`${API}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (isWakingUp(res)) {
        if (attempt < maxAttempts) {
          onWaking?.(attempt, maxAttempts);
          await new Promise((r) => setTimeout(r, WAKEUP_RETRY_DELAYS_MS[attempt - 1]));
          continue;
        }
        throw new Error(
          "서버가 아직 깨어나는 중입니다. 잠시 후 다시 시도해 주세요 (첫 접속 시 최대 2분 정도 걸릴 수 있어요)."
        );
      }

      if (!res.ok) throw new TerminalAuthError(await parseErrorMessage(res, fallbackErrorMessage));
      return await res.json();
    } catch (e) {
      if (e instanceof TerminalAuthError) throw e;
      // 네트워크 자체가 끊긴 경우(TypeError: Failed to fetch)도 콜드스타트
      // 초반에는 흔히 발생하므로 같은 재시도 경로를 탄다.
      if (attempt < maxAttempts) {
        onWaking?.(attempt, maxAttempts);
        await new Promise((r) => setTimeout(r, WAKEUP_RETRY_DELAYS_MS[attempt - 1]));
        continue;
      }
      throw e instanceof Error ? e : new Error(fallbackErrorMessage);
    }
  }
  throw new Error(fallbackErrorMessage);
}

export async function signup(
  email: string,
  password: string,
  name: string,
  onWaking?: (attempt: number, maxAttempts: number) => void
): Promise<AuthResponse> {
  return postWithWakeup("/api/auth/signup", { email, password, name }, "회원가입 실패", onWaking);
}

export async function login(
  email: string,
  password: string,
  onWaking?: (attempt: number, maxAttempts: number) => void
): Promise<AuthResponse> {
  return postWithWakeup("/api/auth/login", { email, password }, "로그인 실패", onWaking);
}

// 토큰은 메모리+localStorage (목업). 실서비스는 httpOnly 쿠키 권장.
export function saveToken(token: string) {
  if (typeof window !== "undefined") localStorage.setItem("pt_token", token);
}
export function getToken(): string | null {
  if (typeof window !== "undefined") return localStorage.getItem("pt_token");
  return null;
}
export function logout() {
  if (typeof window !== "undefined") localStorage.removeItem("pt_token");
}
export interface CurrentUser {
  email: string;
  name: string;
}
export function getCurrentUser(): CurrentUser | null {
  const token = getToken();
  if (!token) return null;
  try {
    const payload = JSON.parse(
      atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))
    );
    const email = payload.sub || payload.email;
    if (!email) return null;
    return { email, name: payload.name || email.split("@")[0] };
  } catch {
    return null;
  }
}
