# Frontend (Next.js)

PrompTune 파이프라인의 **프론트 단계 1,2,9,10** 담당 (예진).
App Router 기반 SPA로, 로그인부터 채팅·파일관리·히스토리·대시보드·설정까지 전체 화면을 담당한다.

## 실행

```bash
npm install
npm run dev        # http://localhost:3000

# Docker
docker build -t promptune-frontend . && docker run -p 3000:3000 promptune-frontend
```

> 백엔드(8080)가 떠 있어야 로그인·분석·실행이 동작.  
> 루트의 `docker compose up --build`로 전체 스택 실행을 권장.  
> (`gradle bootRun`과 달리 `.env`를 읽어서 환경변수가 반영됨).  

API 베이스 URL은 docker-compose.yml의 `NEXT_PUBLIC_API_URL` 환경변수로 설정. (기본값 `http://localhost:8080`)

## 구현된 UX 패턴 (흐름도)

| 단계 | 패턴 | 구현 위치 |
|------|------|-----------|
| 1 | 프롬프트 입력 | `PromptEditor` textarea |
| 2-1 | 입력중단 감지 (debounce) | `scheduleAnalyze` + setTimeout |
| 2-2 | 이전 요청 취소 / 응답 생성 중단 | AbortController (`chat/[id]/page.tsx`의 `stopGenerating`) |
| 9-1 | 인라인 진단 (8요소 상태·밑줄) | `.diagnose`, `.el.target` |
| 9-2 | 밑줄 호버 시 말풍선 추천 | `PromptEditor` 팝업 UI |
| 10 | Tab 적용 / Esc 무시 / ↑↓ 대안 | `onKeyDown` |
| 11 | Enter 실행 | `onExecute` → `execute()` (`lib/api.ts`) |

## 구조

```
src/
├── app/
│   ├── icon.svg                # 사이트 파비콘
│   ├── page.tsx                # 로그인 진입 화면
│   ├── layout.tsx              # 루트 레이아웃 (ShellSwitch로 감쌈)
│   ├── globals.css             # 디자인 토큰 + 전체 페이지/컴포넌트 CSS
│   ├── onboarding/page.tsx     # 최초 로그인 시 선호도 3문항 (스토리보드 0)
│   ├── oauth/callback/page.tsx # 소셜 로그인 콜백 처리
│   ├── chat/
│   │   ├── page.tsx            # 새 채팅 — 빈 컴포저, 메인화면
│   │   └── [id]/page.tsx       # 채팅 스레드 — 실행/생성중단/재시도/인용/만족도 조사 등 핵심 로직
│   ├── chats/page.tsx          # 채팅 목록 — 제목 수정/삭제
│   ├── files/page.tsx          # 파일관리 — 업로드/썸네일/인라인 수정
│   ├── history/                # 히스토리 — 개인화 설정 · 수신자별 스타일 · 수정 이력 탭
│   │   ├── personalization     # 개인화 설정
│   │   │   ├── page.tsx
│   │   │   └── PersonalizationDataActions.tsx
│   │   ├── styles/page.tsx     # 수신자별 스타일
│   │   ├── logs/page.tsx       # 수정 이력
│   │   ├── page.tsx
│   │   └── layout.tsx
│   ├── dashboard/page.tsx      # 대시보드 — 습관 확인
│   └── settings/               # 계정/MS 연동 설정
│       ├── components
│       │   ├── MicrosoftMembersView.tsx
│       │   └── MicrosoftProfileView.tsx
│       └── page.tsx
│
├── components/
│   ├── AppShell.tsx            # 사이드바 + 전체 레이아웃 뼈대
│   ├── ShellSwitch.tsx         # 라우트별 AppShell 표시여부, 페이지 폭(.page vs .page-fixed)을 결정
│   ├── PromptEditor.tsx        # 프롬프트 입력창 (컴포저 핵심) — 입력·진단·추천·직접수정·파일첨부 전부
│   ├── ConfirmDialog.tsx       # 공용 확인 모달 — window.confirm() 대체, 삭제/연결해제/로그아웃에서 사용
│   └── AuthForm.tsx            # 로그인/회원가입 폼
│
├── lib/
│   ├── api.ts                  # execute() 등 파이프라인 실행 관련 호출 (AbortSignal 지원)
│   ├── auth.ts                 # 토큰 저장/로그아웃
│   ├── microsoft.ts            # MS 연동 관련 유틸
│   ├── toneMapping.ts          # 어조 프리셋 매핑
│   └── preferenceQuestions.ts  # 온보딩 3문항 공용 상수 — onboarding/history-personalization/dashboard에서 사용
│
└── api/                        # 백엔드 REST 엔드포인트별 클라이언트
    ├── acitivityLogs.ts        # AcitivityLogsController
    ├── chatSessions.ts         # ChatSessionsController
    ├── consents.ts             # ConsentsController
    ├── dashboard.ts            # DashboardController
    ├── documents.ts            # DocumentsController
    ├── personalization.ts      # PersonalizationController
    ├── promptSessions.ts       # PromptSessionsController
    ├── receiverProfiles.ts     # ReceiverProfilesController
    ├── userPreferences.ts      # UserPreferencesController
    └── users.ts                # UsersController
```

## 레이아웃 규칙

- 어떤 라우트가 어느 클래스를 쓸지는 `ShellSwitch.tsx`의 `FIXED_WIDTH_PAGES` 배열이 결정한다.
- `.page` — 채팅류 페이지(좁은 폭, 최대 720px, `margin: 0 auto`로 중앙 정렬)
- `.page-fixed` — 파일관리·히스토리·대시보드·설정 전용. 
  + 가로 중앙 정렬은 `margin` 대신 `position`(`left` + `calc`)만으로 처리하고, 최소 폭 733px 보장. 
  + 세로는 `min-height: 100vh`
  + `padding: 48px 0 20px`
    + 스크롤 끝까지 내려도 마지막 박스 아래 20px 여백 유지,
    + `height`를 쓰면 콘텐츠가 100vh보다 길 때 padding-bottom이 안 먹으니 반드시 `min-height` 유지.
- 반응형 레이아웃 추가.
  + BreakPoint: 768px

## 공용 UI 패턴

- **확인 모달**
  - 삭제·연결해제·로그아웃처럼 되돌릴 수 없는 액션은 `window.confirm()` 대신 `components/ConfirmDialog.tsx`를 쓴다. 
  - 버튼 클릭 시 바로 실행하지 않고 대상(예: `deleteTarget`)을 state에 담아 모달을 열고, 모달의 확인 버튼에서 실제 API를 호출하는 패턴
  - `history/styles`, `history/personalization/PersonalizationDataActions`, `chats`, `files`, `settings`, `AppShell`에 적용. 
  - 새로 파괴적 액션을 추가할 땐 `confirm()`을 다시 쓰지 말고 이 컴포넌트를 재사용할 것.
- **온보딩 선호도 3문항**
  - `onboarding`(최초 입력, 자세한 설명 포함) / `history/personalization` (요약 편집) / `dashboard`(현재 값 pill 표시) 에서 같은 값을 공유.
  - 따라서 `lib/preferenceQuestions.ts`라는 상수 파일에서 가져다 쓴다.
  - `key`/`value`/`desc`는 두 화면 다 동일해야 함(같은 `user_preferences` 컬럼 값으로 저장되므로)
  - 새 문항을 추가/수정할 땐 반드시 이 파일 하나만 고치면 된다.
    - 예전엔 페이지마다 따로 복붙되어 있어서 라벨 문구가 드리프트(온보딩 "적극적으로 보완" vs 요약 "적극적 보완"이 우연히 갈라짐)된 적 있음.

## 교체/확장 (예진)

- mock이 아니라 실제 UI로 동작.
- 백엔드/AI 서비스가 실제 모델로 교체되어도 프론트는 응답 형식만 같으면 수정 없이 그대로 동작한다.
- 새 페이지 추가 시 `ShellSwitch.tsx`의 `KEY_TO_PATH`/`FIXED_WIDTH_PAGES`에 등록 필요.

## 접근성

키보드 포커스 표시, `prefers-reduced-motion` 존중, 모바일 반응형. (예정)
