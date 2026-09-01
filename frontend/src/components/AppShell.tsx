"use client";
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { listChatSessions, updateChatTitle, deleteChatSession, ChatSession } from "@/api/chatSessions";
import { getCurrentUser, logout, CurrentUser } from "@/lib/auth";
import ConfirmDialog from "@/components/ConfirmDialog";

export type NavKey = "newChat" | "chat" | "files" | "history" | "dashboard" | "settings";

const NAV_ITEMS: { key: NavKey; label: string, icon: string }[] = [
  { key: "files", label: "파일관리", icon: "files" },
  { key: "history", label: "히스토리", icon: "history" },
  { key: "dashboard", label: "대시보드", icon: "dashboard" },
  { key: "settings", label: "설정", icon: "settings" },
]

// 모바일 상단바 제목 - files/history/dashboard/settings는 NAV_ITEMS 라벨을 그대로 쓰고,
// 채팅목록(chat)은 NAV_ITEMS에 없어서 별도로 지정. 새 채팅(newChat)은 컴포저 자체
// 안내문이 이미 있어서 상단바 제목 없이 기본값("PrompTune")으로 둔다.
const MOBILE_TITLE_OVERRIDES: Partial<Record<NavKey, string>> = {
  chat: "채팅목록",
};

function mobileTitleFor(active: NavKey): string {
  return NAV_ITEMS.find((item) => item.key === active)?.label
    ?? MOBILE_TITLE_OVERRIDES[active]
    ?? "PrompTune";
}

interface AppShellProps {
  active: NavKey;
  onNavigate: (key: NavKey) => void;
  onNewChat?: () => void;
  userEmail?: string;
  onLogout?: () => void;
  children: React.ReactNode;
}

export default function AppShell({
  active,
  onNavigate,
  onNewChat,
  userEmail,
  onLogout,
  children,
}: AppShellProps) {
  const [dark, setDark] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [recentChats, setRecentChats] = useState<ChatSession[]>([]);
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [openMenuId, setOpenMenuId] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<ChatSession | null>(null);
  const [deleting, setDeleting] = useState(false);
  // 모바일 사이드바 - 기본 숨김, 햄버거로 오버레이 열기
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  // 데스크톱의 "접기(collapsed, 아이콘만)" 상태를 모바일에서까지 들고 오면
  // 모바일 오버레이가 아이콘 레일로 뜨는 이상한 조합이 생겨서, 뷰포트로 직접 판별해
  // 모바일일 땐 collapsed 클래스를 아예 안 붙이도록 한다.
  const [isMobile, setIsMobile] = useState(false);

  const router = useRouter();
  const pathname = usePathname();
  const accountMenuRef = useRef<HTMLDivElement>(null);

  // 실제 백엔드에서 채팅 목록을 다시 조회
  async function refreshChatSessions() {
    try {
      const chats = await listChatSessions();
      setRecentChats(chats);
    } catch {
      setRecentChats([]);
    }
  }

  // 페이지 이동 시 채팅 목록 갱신 + 열려있던 메뉴/수정상태 닫기 (+ 모바일 사이드바도 같이 닫기)
  useEffect(() => {
    refreshChatSessions();
    setOpenMenuId(null);
    setEditingId(null);
    setMobileMenuOpen(false);
  }, [pathname]);

  // 모바일 뷰포트(≤768px) 여부를 실시간으로 추적 - .sidebar.collapsed 클래스 적용 여부에 씀
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 768px)");
    const update = () => setIsMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  // 채팅 옵션(⋮) 메뉴 바깥 클릭 시 닫기
  useEffect(() => {
    if (openMenuId === null) return;
    function handleClickOutside(e: MouseEvent) {
      if (!(e.target as HTMLElement).closest(".recent-chat-row")) {
        setOpenMenuId(null);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [openMenuId]);

  // 제목 수정 시작
  function startEditTitle(c: ChatSession) {
    setOpenMenuId(null);
    setEditingId(c.id);
    setEditTitle(c.title || `대화 #${c.id}`);
  }

  // 제목 수정 저장 (Enter)
  async function saveEditTitle(id: number) {
    const trimmed = editTitle.trim();
    if (!trimmed) {
      setEditingId(null);
      return;
    }
    try {
      const updated = await updateChatTitle(id, trimmed);
      setRecentChats((prev) => prev.map((c) => (c.id === id ? updated : c)));
    } catch (e: any) {
      alert(e.message || "제목 수정에 실패했습니다.");
    } finally {
      setEditingId(null);
    }
  }

  // 채팅 삭제 - 모달 띄움
  function handleDeleteChat(c: ChatSession) {
    setOpenMenuId(null);
    setDeleteTarget(c);
  }
    
  async function confirmDeleteChat() { 
    if (!deleteTarget) return;
    setDeleting(true);

    try {
      await deleteChatSession(deleteTarget.id);
      setRecentChats((prev) => prev.filter((x) => x.id !== deleteTarget.id));

      // /chats 목록 페이지가 열려있는 경우 그쪽 목록도 실시간으로 갱신되도록 알림
      window.dispatchEvent(
        new CustomEvent("chat-session-deleted", {
          detail: { chatSessionId: deleteTarget.id },
        })
      );
      
      // 지금 보고 있는 대화를 삭제한 경우 채팅 목록으로 이동
      if (pathname === `/chat/${deleteTarget.id}`) {
        router.push("/chats");
      }
      setDeleteTarget(null);
    } catch (e: any) {
      alert(e.message || "삭제에 실패했습니다.");
    } finally {
      setDeleting(false);
    }
  }

  // 첫 프롬프트 실행 후 ChatSesion.title이 백엔드에서 생성됐을 때 채팅 목록 갱신
  useEffect(() => {
    function handleChatSessionUpdated() {
      refreshChatSessions();
    }

    window.addEventListener(
      "chat-session-updated",
      handleChatSessionUpdated
    );

    return () => {
      window.removeEventListener(
        "chat-session-updated",
        handleChatSessionUpdated
      );
    };
  }, []);

  // 저장된 다크모드 · 사이드바 접힘 상태 복원
  useEffect(() => {
    if (localStorage.getItem("pt_theme") === "dark") setDark(true);
    if (localStorage.getItem("pt_sidebar_collapsed") === "1") setCollapsed(true);
  }, []);

  // 로그인 사용자 정보는 localStorage(토큰) 기반이라 서버에서는 알 수 없음.
  // 렌더링 중에 바로 읽으면 SSR 결과(null)와 클라이언트 첫 렌더 결과(실제 값)가
  // 달라져 하이드레이션 에러(#418/#423/#425)가 발생하므로, 마운트 후 useEffect에서 설정한다.
  useEffect(() => {
    setCurrentUser(getCurrentUser());
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
    localStorage.setItem("pt_theme", dark ? "dark" : "light");
  }, [dark]);

  useEffect(() => {
    localStorage.setItem("pt_sidebar_collapsed", collapsed ? "1" : "0");
  }, [collapsed]);

  // 프로필 사진 대신 이메일 첫 글자와 이름 표시
  const displayEmail = currentUser?.email || userEmail || "guest@promptune.dev";
  const initial = displayEmail.slice(0, 1).toUpperCase();
  const name = displayEmail.split("@")[0].toUpperCase();

  return (
    <div className="shell">
      {/* 모바일 전용 - 상단 고정 바 (햄버거 버튼 + 현재 페이지 제목).
          사이드바가 기본 숨김이라 햄버거는 항상 눌러서 열 수 있어야 하고,
          제목은 각 페이지 자체의 <h1>을 모바일에서 숨기는 대신 여기서 보여준다
          (AppShell이 active로 이미 페이지를 알고 있어서 페이지 파일은 안 건드려도 됨). */}
      <div className="mobile-topbar">
      <button
        type="button"
        className="mobile-menu-btn"
        onClick={() => setMobileMenuOpen(true)}
        aria-label="메뉴 열기"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <line x1="3" y1="6" x2="21" y2="6" />
          <line x1="3" y1="12" x2="21" y2="12" />
          <line x1="3" y1="18" x2="21" y2="18" />
        </svg>
      </button>
        {mobileTitleFor(active) && (
          <h2 className="mobile-topbar-title">{mobileTitleFor(active)}</h2>
        )}
      </div>

      {/* 모바일 전용 - 사이드바 열렸을 때 바깥 어둡게 + 탭하면 닫힘 */}
      {mobileMenuOpen && (
        <div className="mobile-sidebar-backdrop" onClick={() => setMobileMenuOpen(false)} />
      )}

      {/* 사이드바 */}
      <aside className={`sidebar ${collapsed && !isMobile ? "collapsed" : ""} ${mobileMenuOpen ? "mobile-open" : ""}`}>
        {/* 로고: 클릭 시 홈으로 이동 + 사이드바 토글*/}
        <div className="sidebar-header">
          <button type="button" className="sidebar-logo"
            onClick={() => {
              onNavigate("newChat");
              onNewChat?.();
            }}
            style={{ width: "fit-content", background: "none", border: "none", cursor: "pointer" }}>
            <span className="logo-icon">
              <img src="/icons/icon.svg" />
            </span>
            <span>PrompTune</span>
          </button>
          <button
            className="collapse-btn"
            onClick={() => setCollapsed((c) => !c)}
            title={collapsed ? "펼치기" : "접기"}
          >
            <img src="/icons/collapse.png" alt="" />
          </button>
          {/* 모바일 전용 닫기(X) - collapse-btn은 데스크톱 접기용이라 의미가 달라서 따로 둠 */}
          <button
            type="button"
            className="mobile-close-btn"
            onClick={() => setMobileMenuOpen(false)}
            aria-label="메뉴 닫기"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="5" y1="5" x2="19" y2="19" />
              <line x1="19" y1="5" x2="5" y2="19" />
            </svg>
          </button>
        </div>

        {/* 새 채팅 버튼 */}
        <button
          className={`new-chat-btn ${active === "newChat" ? "active" : ""}`}
          onClick={() => {
            onNavigate("newChat");
            onNewChat?.();
          }}
        >
          <span className="label-icon"><img src="/icons/plus-muted.png" alt="" /></span>
          <span className="label-icon-active"><img src="/icons/plus-active.png" alt="" /></span>
          <span className="label">새 채팅</span>
        </button>

        {/* 네비게이션 메뉴 */}
        <nav className="nav-list">
          <button
            className={`nav-item ${active === "chat" ? "active" : ""}`}
            onClick={() => onNavigate("chat")}
          >
            <span className="label-icon"><img src="/icons/chats-muted.png" alt="" /></span>
            <span className="label-icon-active"><img src="/icons/chats-active.png" alt="" /></span>
            <span className="label">채팅</span>
          </button>

          <div className="sidebar-spacer" style={{ borderTop: "1px solid var(--line)" }} />

          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              className={`nav-item ${active === item.key ? "active" : ""}`}
              onClick={() => onNavigate(item.key)}
              title={item.label}
            >
              <span className="label-icon">
                <img src={`/icons/${item.icon}-muted.png`} alt="" />
              </span>
              <span className="label-icon-active">
                <img src={`/icons/${item.icon}-active.png`} alt="" />
              </span>
              <span className="label">{item.label}</span>
            </button>
          ))}
        </nav>

        {/* 최근 채팅 - 이 목록만 별도로 스크롤됨 */}

        <div className="sidebar-spacer" style={{ borderTop: "1px solid var(--line)", margin: "3px 0" }} />
        <div className="recent-chats">
          {recentChats.map((c) => (
            <div className="recent-chat-row" key={c.id}>
              {editingId === c.id ? (
                <input
                  className="recent-chat-edit-input"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") saveEditTitle(c.id);
                    if (e.key === "Escape") setEditingId(null);
                  }}
                  onBlur={() => saveEditTitle(c.id)}
                  autoFocus
                />
              ) : (
                <>
            <button
              className={`recent-chat-item ${pathname === `/chat/${c.id}` ? "active" : ""}`}
              onClick={() => router.push(`/chat/${c.id}`)}
              title={c.title || `대화 #${c.id}`}
            >
              {c.title || `대화 #${c.id}`}
            </button>

                  <button
                    type="button"
                    className="recent-chat-menu-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpenMenuId(openMenuId === c.id ? null : c.id);
                    }}
                    aria-label="채팅 옵션"
                  >
                    <img src="/icons/dots.png" alt="" />
                  </button>

                  {openMenuId === c.id && (
                    <div className="recent-chat-menu">
                      <button onClick={() => startEditTitle(c)}>수정</button>
                      <button className="danger" onClick={() => handleDeleteChat(c)}>삭제</button>
                    </div>
                  )}
                </>
              )}
            </div>
          ))}
        </div>

        {collapsed ? <div className="sidebar-spacer" style={{ flexGrow: 1 }} /> : <></>}

        {/* 하단: 다크모드 토글, 계정 정보, 로그아웃 */}
        <div className="sidebar-bottom">
          {/* 다크모드 토글 */}
          <div className="theme-row">
            <span className="label">다크 모드</span>
            <label className="switch">
              <input
                type="checkbox"
                checked={dark}
                onChange={(e) => setDark(e.target.checked)}
              />
              <span className="switch-track" />
              <span className="switch-thumb" />
            </label>
          </div>

          {/* 사용자 정보 */}
          <div className="user-row-wrap" ref={accountMenuRef}>
            <button
              type="button"
              className="user-row"
              aria-haspopup="menu"
              title={displayEmail}
            >
              <span className="avatar">{initial}</span>
              <span className="user-meta label">
                <span className="user-name">{name}</span>
                <span className="user-email">{displayEmail}</span>
              </span>
            </button>
          </div>

          {/* 로그아웃 버튼 */}
          <button className="logout-link label" onClick={() => { if (onLogout) onLogout(); else { logout(); window.location.href = "/"; } }}>
            <span className="label-icon"><img src="/icons/logout.png" /></span>
            로그아웃
          </button>
        </div>

      </aside>

      {/* 메인 컨텐츠 */}
      <main className="content">{children}</main>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="채팅 삭제"
        message={`"${deleteTarget?.title || `대화 #${deleteTarget?.id}`}" 대화를 삭제할까요?`}
        confirmLabel="삭제"
        danger
        loading={deleting}
        onConfirm={confirmDeleteChat}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
