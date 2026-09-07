// DocumentController(/api/documents) 전용 API 클라이언트.
// 실제 파일을 multipart/form-data로 업로드하면 백엔드가 S3(promptune-document 버킷)에 저장하고
// 메타데이터(title/documentType/s3Key/fileType)를 DB에 저장한다.

// documentType 표기 규칙: UI 상에서는 한글, 백엔드에서 받는 값은 영문 enum
import { getToken } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export type DocType = "규정" | "양식" | "가이드" | "보고서" | "기타";

const KO_TO_ENUM: Record<DocType, string> = {
  "규정": "POLICY",
  "양식": "TEMPLATE",
  "가이드": "GUIDE",
  "보고서": "REPORT",
  "기타": "OTHER",
};

const ENUM_TO_KO: Record<string, DocType> = {
  POLICY: "규정",
  TEMPLATE: "양식",
  GUIDE: "가이드",
  REPORT: "보고서",
  OTHER: "기타",
};

export function toEnum(k: DocType): string {
  return KO_TO_ENUM[k] ?? "OTHER";
}

export function toKorean(e: string | null | undefined): DocType {
  if (!e) return "기타";
  return ENUM_TO_KO[e] ?? "기타";
}

export interface DocumentItem {
  id: number;
  ownerUserId: number;
  title: string;
  description: string | null;
  documentType: DocType; // 항상 한글로 노출 (원본 응답은 영문 enum, 여기서 변환)
  s3Key: string | null;
  fileType: string | null;
  indexStatus?: "UPLOADED" | "INDEXING" | "TEXT_READY" | "READY" | "FAILED";
  indexError?: string | null;
  indexedAt?: string | null;
}

// 백엔드가 실제로 내려주는 원본 형태 (documentType이 영문 enum)
interface RawDocumentItem extends Omit<DocumentItem, "documentType"> {
  documentType: string;
}

function fromRaw(raw: RawDocumentItem): DocumentItem {
  return { ...raw, documentType: toKorean(raw.documentType) };
}

function authHeaders(): HeadersInit {
  const token = getToken();
  if (!token) throw new Error("로그인이 필요합니다.");
  return { Authorization: `Bearer ${token}` };
}

// Create - POST /api/documents (multipart/form-data)
// 주의: FormData를 쓸 때는 Content-Type 헤더를 직접 지정하면 안 됨
// (브라우저가 boundary를 포함해서 자동으로 설정해야 함)
export async function uploadDocument(
  file: File,
  title: string,
  documentType: DocType,
  description?: string
): Promise<DocumentItem> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("title", title);
  formData.append("documentType", toEnum(documentType));
  if (description) formData.append("description", description);

  const res = await fetch(`${API}/api/documents`, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.error || `업로드 실패: ${res.status}`);
  }
  const raw: RawDocumentItem = await res.json();
  return fromRaw(raw);
}

// Read - GET /api/documents
export async function listDocuments(): Promise<DocumentItem[]> {
  const res = await fetch(`${API}/api/documents`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`파일 목록 조회 실패: ${res.status}`);
  const raw: RawDocumentItem[] = await res.json();
  return raw.map(fromRaw);
}

// 원본 파일 조회
export async function fetchDocumentContent(id: number): Promise<Blob> {
  const res = await fetch(`${API}/api/documents/${id}/content`, {
    headers: authHeaders(),
  });

  if (!res.ok) {
    throw new Error(`파일 열기 실패: ${res.status}`);
  }

  return res.blob();
}

// Update - PATCH /api/documents/{id} - title, description, documentType 수정 가능
export async function updateDocument(
  id: number,
  patch: { title?: string; description?: string; documentType?: DocType }
): Promise<DocumentItem> {
  const body: Record<string, string> = {};
  if (patch.title !== undefined) body.title = patch.title;
  if (patch.description !== undefined) body.description = patch.description;
  if (patch.documentType !== undefined) body.documentType = toEnum(patch.documentType);

  const res = await fetch(`${API}/api/documents/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => null);
    throw new Error(errBody?.error || `수정 실패: ${res.status}`);
  }
  const raw: RawDocumentItem = await res.json();
  return fromRaw(raw);
}

export async function reindexDocument(id: number): Promise<DocumentItem> {
  const res = await fetch(`${API}/api/documents/${id}/reindex`, {
    method: "POST",
    headers: authHeaders(),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.error || body?.message || `재인덱싱 실패: ${res.status}`);
  }

  const raw: RawDocumentItem = await res.json();
  return fromRaw(raw);
}

// Delete - DELETE /api/documents/{id}
export async function deleteDocument(id: number): Promise<void> {
  const res = await fetch(`${API}/api/documents/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`삭제 실패: ${res.status}`);
}
export type DocumentFormat = "docx" | "pdf" | "pptx";

// 서버가 Content-Disposition으로 내려준 실제 파일명을 읽어온다. 데모 모드에서는
// 백엔드가 요청받은 format을 무시하고 실제 원본 서식 파일(예: 일일업무보고
// 원본 docx)로 바꿔치기하는 경우가 있어서(AiServiceClient.tryDemoTemplateOverride),
// 클라이언트가 title/format으로 지레짐작한 파일명을 그대로 쓰면 확장자가
// 실제 내용과 안 맞을 수 있다 - 항상 서버가 알려준 이름을 우선한다.
// (SecurityConfig에서 CORS exposedHeaders에 Content-Disposition을 추가해둬야
// 브라우저가 이 헤더를 fetch()로 읽을 수 있다.)
function parseContentDispositionFilename(header: string | null): string | null {
  if (!header) return null;

  const rfc5987 = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (rfc5987) {
    try {
      return decodeURIComponent(rfc5987[1]);
    } catch {
      // 디코딩 실패 시 아래 일반 filename="..." 폴백으로 넘어감
    }
  }

  const plain = header.match(/filename="([^"]+)"/i);
  return plain ? plain[1] : null;
}

export function guessDocumentFormat(
  fileName: string | null,
  fallback: DocumentFormat,
): DocumentFormat {
  if (!fileName) return fallback;
  const ext = fileName.split(".").pop()?.toLowerCase();
  return ext === "docx" || ext === "pdf" || ext === "pptx" ? ext : fallback;
}

export interface GeneratedDocumentFile {
  blob: Blob;
  // 서버가 실제로 내려준 파일명. Content-Disposition이 없거나 파싱 실패하면 null
  // (호출부가 title/format으로 폴백해야 함).
  fileName: string | null;
}

export async function generateDocumentFile(
  title: string,
  content: string,
  format: DocumentFormat,
  templateDocumentId?: number,
): Promise<GeneratedDocumentFile> {
  const res = await fetch(`${API}/api/documents/generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify({
      title,
      content,
      format,
      templateDocumentId: templateDocumentId ?? null,
    }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(
      body?.error || `문서 생성 실패: ${res.status}`
    );
  }

  const fileName = parseContentDispositionFilename(res.headers.get("Content-Disposition"));
  return { blob: await res.blob(), fileName };
}

// 데모 전용: AI가 새로 만든 문서가 아니라, 실제 회사 서식 원본을 그대로
// 받아온다 (백엔드 AiServiceClient.DEMO_TEMPLATE_FILES에 등록된 key만 유효).
export async function fetchDemoTemplateFile(key: string): Promise<Blob> {
  const res = await fetch(`${API}/api/documents/demo-template/${encodeURIComponent(key)}`, {
    headers: authHeaders(),
  });

  if (!res.ok) {
    throw new Error(`템플릿 파일 조회 실패: ${res.status}`);
  }

  return res.blob();
}
