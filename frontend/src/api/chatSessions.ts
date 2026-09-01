// ChatSesionController(/api/chat-sessions) 전용 API 클라이언트.
// 이 엔드포인트들은 Authentication이 필요함
// >> analyze/execute(lib/api.ts, permitAll)와 달리 토큰을 반드시 헤더에 실어보냄.
import { getToken } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export interface ChatSession {
  id: number;
  userId: number;
  title: string | null;
  updatedAt: string;
}

function authHeaders(): HeadersInit {
  const token = getToken();
  if (!token) throw new Error("로그인이 필요합니다.");
  return { Authorization: `Bearer ${token}` };
}

// POST /api/chat-sessions - "+ 새 채팅" 시 빈 대화 세션 생성
export async function createChatSession(): Promise<ChatSession> {
  const res = await fetch(`${API}/api/chat-sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
  });
  if (!res.ok) throw new Error(`대화 생성 실패: ${res.status}`);
  return res.json();
}

// GET /api/chat-sessions - 로그인한 사용자의 대화 목록 (최신순)
export async function listChatSessions(): Promise<ChatSession[]> {
  const res = await fetch(`${API}/api/chat-sessions`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`대화 목록 조회 실패: ${res.status}`);
  return res.json();
}

// PATCH /api/chat-sessions/{id} - 채팅 제목 수정
export async function updateChatTitle(id: number, title: string): Promise<ChatSession> {
  const res = await fetch(`${API}/api/chat-sessions/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`제목 수정 실패: ${res.status}`);
  return res.json();
}

// DELETE /api/chat-sessions/{id} - 채팅 삭제 (메시지도 CASCADE로 함께 삭제됨)
export async function deleteChatSession(id: number): Promise<void> {
  const res = await fetch(`${API}/api/chat-sessions/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`채팅 삭제 실패: ${res.status}`);
}

export interface MessageAttachment {
  id: number;
  title: string;
}

export interface ChatMessage {
  id: number;
  prompt: string;
  aiResponse: string;
  taskType: string | null;
  createdAt: string;
  satisfaction: "good" | "bad" | null;
  attachments?: MessageAttachment[];
}

// GET /api/chat-sessions/{id}/messages - 세션 하나의 지난 메시지 목록 (시간순)
export async function getChatMessages(id: number): Promise<ChatMessage[]> {
  const res = await fetch(`${API}/api/chat-sessions/${id}/messages`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`대화 기록 조회 실패: ${res.status}`);
  return res.json();
}