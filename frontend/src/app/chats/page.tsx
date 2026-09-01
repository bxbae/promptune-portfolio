"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { listChatSessions, updateChatTitle, deleteChatSession, ChatSession } from "@/api/chatSessions";
import ConfirmDialog from "@/components/ConfirmDialog";

function timeAgo(iso: string) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const min = Math.floor(diffMs / 60000);
  if (min < 1) return "방금 전";
  if (min < 60) return `${min}분 전`;
  const hour = Math.floor(min / 60);
  if (hour < 24) return `${hour}시간 전`;
  const day = Math.floor(hour / 24);
  if (day === 1) return "어제";
  if (day < 7) return `${day}일 전`;
  return `${Math.floor(day / 7)}주 전`;
}

const PAGE_SIZE = 10;

export default function ChatsPage() {
  const router = useRouter();
  const [chats, setChats] = useState<ChatSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);

  const [openMenuId, setOpenMenuId] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<ChatSession | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    listChatSessions()
      .then(setChats)
      .catch((e) => setError(e.message || "채팅 목록을 불러오지 못했습니다."))
      .finally(() => setLoading(false));
  }, []);

  // AppShell(사이드바)에서 채팅 삭제 시, 이 페이지가 열려있으면 목록에서 실시간으로 제거
  useEffect(() => {
    function handleDeleted(e: Event) {
      const { chatSessionId } = (e as CustomEvent).detail || {};
      if (chatSessionId == null) return;
      setChats((prev) => prev.filter((c) => c.id !== chatSessionId));
    }

    window.addEventListener("chat-session-deleted", handleDeleted);
    return () => window.removeEventListener("chat-session-deleted", handleDeleted);
  }, []);

  // 삭제로 인해 현재 페이지에 항목이 없어지면 이전 페이지로 자동 이동
  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(chats.length / PAGE_SIZE));
    if (page > maxPage) setPage(maxPage);
  }, [chats, page]);

  // 메뉴 바깥 클릭 시 수정/삭제 닫기
  useEffect(() => {
    if (openMenuId === null) return;
    function handleClickOutside(e: MouseEvent) {
      if (!(e.target as HTMLElement).closest(".chat-list-item-row")) {
        setOpenMenuId(null);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [openMenuId]);

  // 제목 수정
  function startEditTitle(c: ChatSession) {
    setOpenMenuId(null);
    setEditingId(c.id);
    setEditTitle(c.title || `대화 #${c.id}`);
  }

  // 제목 수정 저장
  async function saveEditTitle(id: number) {
    const trimmed = editTitle.trim();
    if (!trimmed) {
      setEditingId(null);
      return;
    }
    try {
      const updated = await updateChatTitle(id, trimmed);
      setChats((prev) => prev.map((c) => (c.id === id ? updated : c)));
      // 사이드바(AppShell)는 "chat-session-updated"를 이미 듣고 있어서, 쏘기만 하면 목록이 같이 갱신됨
      window.dispatchEvent(new CustomEvent("chat-session-updated"));
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
      setChats((prev) => prev.filter((x) => x.id !== deleteTarget.id));
      // AppShell 사이드바가 이미 듣고 있는 이벤트 재사용 - 이 페이지에서 지워도 사이드바 목록에서 같이 빠짐
      window.dispatchEvent(
        new CustomEvent("chat-session-deleted", { detail: { chatSessionId: deleteTarget.id } })
      );
      setDeleteTarget(null);
    } catch (e: any) {
      alert(e.message || "삭제에 실패했습니다.");
    } finally {
      setDeleting(false);
    }
  }


  return (
    <div className="chat-list-page">
      <h1>채팅</h1>

      {loading && <div style={{ color: "var(--muted)" }}>불러오는 중...</div>}
      {!loading && error && <div style={{ color: "var(--block)" }}>{error}</div>}

      {!loading && !error && chats.length === 0 && (
        <div style={{ padding: "60px 0", textAlign: "center", color: "var(--muted)" }}>
          아직 대화 기록이 없어요. <span style={{ color: "var(--accent)", fontWeight: 600 }}>+ 새 채팅</span>으로 시작해보세요.
        </div>
      )}

      {!loading && !error && chats.length > 0 && (
        <>
          <div className="chat-list">
            {chats.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE).map((c) => (
              <div className="chat-list-item-row" key={c.id}>
                {editingId === c.id ? (
                  <input
                    className="chat-list-edit-input"
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
                      className="chat-list-item"
                      onClick={() => router.push(`/chat/${c.id}`)}
                    >
                      <span className="chat-list-title">{c.title || `대화 #${c.id}`}</span>
                      <span className="chat-list-meta">
                        <span className="chat-list-time">{timeAgo(c.updatedAt)}</span>
                      </span>

                      <button
                        type="button"
                        className="chat-list-menu-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          setOpenMenuId(openMenuId === c.id ? null : c.id);
                        }}
                        aria-label="채팅 옵션"
                      >
                        <img src="/icons/dots.png" alt="" />
                      </button>
                    </button>

                    {openMenuId === c.id && (
                      <div className="chat-list-menu">
                        <button onClick={() => startEditTitle(c)}>수정</button>
                        <button className="danger" onClick={() => handleDeleteChat(c)}>삭제</button>
                      </div>
                    )}
                  </>
                )}
              </div>
            ))}
          </div>

          {chats.length > PAGE_SIZE && (
            <div className="chat-list-pager">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
              >
                이전
              </button>
              <span className="chat-list-pager-status">
                {page} / {Math.ceil(chats.length / PAGE_SIZE)}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(Math.ceil(chats.length / PAGE_SIZE), p + 1))}
                disabled={page === Math.ceil(chats.length / PAGE_SIZE)}
              >
                다음
              </button>
            </div>
          )}
        </>
      )}

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
  );
}