"use client";
import { useRouter } from "next/navigation";
import PromptEditor, { DirectEdit } from "@/components/PromptEditor";
import { createChatSession } from "@/api/chatSessions";
import type { DocumentItem } from "@/api/documents";

export default function ChatPage() {
  const router = useRouter();

  async function handleFirstSubmit(
    displayText: string,
    directEdits: DirectEdit[],
    attachments: DocumentItem[],
    sendText?: string,
  ) {
    try {
      const session = await createChatSession();
      // /chat/[id] 페이지가 세션 조회 API 없이도 첫 메시지를 바로 실행할 수 있게 잠깐 들고 넘어감
      // displayText: 화면에 보여줄 텍스트, sendText: 실제 AI에 보내는 텍스트(둘이 다를 수 있음 - 파일만 첨부/인용 시)
      sessionStorage.setItem(
        `chat-first-${session.id}`,
        JSON.stringify({ text: displayText, sendText, directEdits, attachments }),
      );
      router.push(`/chat/${session.id}?run=1`);
    } catch (e) {
      console.error("새 대화 시작 실패", e);
      alert("새 대화를 시작하지 못했습니다. 로그인 상태를 확인해주세요.");
    }
  }

  return <PromptEditor onSubmit={handleFirstSubmit}/>;
}