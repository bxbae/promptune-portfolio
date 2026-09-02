"use client";
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import AppShell, { NavKey } from "./AppShell";
import { getToken, logout } from "@/lib/auth";

// URL ↔ 사이드바 탭 매핑. 새 페이지가 생기면 이 두 곳에 추가
// "새 채팅"(newChat)과 "채팅"(chat, 목록)은 서로 다른 화면이라 경로도 분리함.
const PATH_TO_KEY: Record<string, NavKey> = {
  "/chat": "newChat",
  "/chats": "chat",
  "/files": "files",
  "/history": "history",
  "/dashboard": "dashboard",
  "/settings": "settings",
}
const KEY_TO_PATH: Record<NavKey, string> = {
  newChat: "/chat",
  chat: "/chats",
  files: "/files",
  history: "/history",
  dashboard: "/dashboard",
  settings: "/settings",
}

// 로그인 화면(/) - 사이드바 X
// 나머지 화면 - 사이드바(AppShell) O
// 이 레이아웃은 고정 (수정 시 레이아웃 대규모 수정 필요)
export default function ShellSwitch({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  // 2026-09-02: "/chat"(및 /files, /history, /dashboard, /settings)에 토큰 없이
  // 직접 접속하면 - 예: 북마크/공유된 링크, 새로고침 등 "/" 로그인 게이트를 거치지
  // 않은 진입 - 이 컴포넌트가 pathname만 보고 무조건 AppShell(사이드바 포함 전체 UI)을
  // 렌더링해서, 로그인 없이도 정상 작동하는 것처럼 보이는 화면이 뜬다. 실제로는
  // 백엔드가 모든 /api/**를 인증 필수로 막아놔서 메시지를 보내도 응답이 전혀 없다
  // (채팅 생성 API가 토큰 없으면 fetch도 하기 전에 "로그인이 필요합니다"로 즉시
  // 실패하기 때문). "/" 페이지는 반대로 토큰이 있으면 /chat|/onboarding으로
  // 보내주는데, 나머지 페이지들은 그 반대(토큰 없으면 "/"로 보내기)가 없었다 -
  // 여기서 그 누락된 인증 게이트를 추가한다.
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    if (pathname === "/") return;
    if (!getToken()) {
      router.replace("/");
      return;
    }
    setAuthChecked(true);
  }, [pathname, router]);

  if (pathname === "/") return <>{children}</>;

  // 토큰 확인(및 필요 시 "/"로의 리다이렉트)이 끝나기 전에는 AppShell을 그리지 않는다 -
  // 안 그러면 리다이렉트되기 직전에 로그인 안 된 상태의 AppShell이 한 프레임 보이거나,
  // 그 안의 페이지가 인증이 필요한 API를 먼저 호출해버릴 수 있다.
  if (!authChecked) return null;

  const topSegment = "/" + (pathname.split("/")[1] ?? "");
  // 채팅 스레드는 "채팅"으로 별도 매핑
  const active: NavKey =
    pathname === "/chat"
      ? "newChat"
      : pathname.startsWith("/chat/")
        ? "chat"
        : PATH_TO_KEY[topSegment] ?? "newChat";

  // 파일관리/히스토리/대시보드/설정 - 표·카드가 많아 최소 폭(733px)이 필요한 페이지들.
  // 이 페이지들은 좌우 padding 없이, position(가로 중앙)만으로 배치하는 .page-fixed를 사용.
  const FIXED_WIDTH_PAGES = ["/files", "/history", "/dashboard", "/settings"];
  const isFixedWidth = FIXED_WIDTH_PAGES.some((p) => pathname === p || pathname.startsWith(p + "/"));

  return (
    <AppShell
      active={active}
      onNavigate={(key) => router.push(KEY_TO_PATH[key])}
      onNewChat={() => router.push("/chat")}
      onLogout={() => {
        logout();
        router.push("/");
      }}
    >
      <div className={isFixedWidth ? "page-fixed" : "page"}>{children}</div>
    </AppShell>
  );
}
