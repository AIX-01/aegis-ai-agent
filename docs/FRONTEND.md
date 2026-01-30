# 프론트엔드

> AEGIS - CCTV 실시간 AI 안전 모니터링 시스템

---

## 페이지 구조

| 경로 | 컴포넌트 | 설명 | 권한 |
|------|----------|------|------|
| `/` | DashboardContent | 메인 대시보드 (CCTV 그리드, 이벤트 로그) | 인증 |
| `/auth` | AuthForm | 로그인/회원가입 | 미인증 |
| `/events` | EventsPageContent | 이벤트 목록 및 상세 | 인증 |
| `/members` | MembersPageContent | 멤버 관리 | Admin |
| `/settings` | SettingsPageContent | 설정 (프로필, 비밀번호) | 인증 |
| `/statistics` | StatisticsPageContent | 통계 대시보드 | 인증 |

---

## AuthContext

### 상태

| 필드 | 타입 | 설명 |
|------|------|------|
| user | User \| null | 현재 사용자 |
| isLoading | boolean | 로딩 상태 |
| isAdmin | boolean | user?.role === 'admin' |

### 메서드

| 메서드 | 설명 |
|--------|------|
| login(email, password) | 로그인 → 성공 시 user 설정 |
| signup(email, password, name) | 회원가입 |
| logout() | 로그아웃 → user 초기화, /auth 리다이렉트 |

### 초기화

1. 앱 로드 시 `POST /api/auth/refresh` 시도
2. 성공 → `GET /api/auth/me` → user 설정
3. 실패 → user = null

---

## Axios 인터셉터

### 요청 인터셉터

- Access Token이 있으면 `Authorization: Bearer {token}` 헤더 추가

### 응답 인터셉터 (401 처리)

1. 401 응답 && 재시도 아님 && 인증 엔드포인트 아님
2. `POST /api/auth/refresh` 시도
3. 성공 → Access Token 갱신 → 원래 요청 재시도
4. 실패 → Access Token 초기화 → `/auth` 리다이렉트

---

## React Query 키

| 키 | 용도 |
|-----|------|
| `['streams']` | 카메라 목록 |
| `['streams', id]` | 카메라 상세 |
| `['eventLogs']` | 이벤트 목록 |
| `['eventLogs', id]` | 이벤트 상세 |
| `['eventLogs', filter]` | 필터링된 이벤트 |
| `['stats']` | 전체 통계 |
| `['stats', 'daily']` | 일별 통계 |
| `['stats', 'monthly']` | 월별 통계 |
| `['stats', 'summary']` | 요약 통계 |
| `['cameras']` | 카메라 목록 (SSE 연동) |
| `['events']` | 이벤트 목록 (SSE 연동) |
| `['users']` | 사용자 목록 (SSE 연동) |
| `['notifications']` | 알림 목록 (SSE 연동) |

---

## 전역 SSE 연결 (SseContext)

### SseProvider

- 로그인 시 단일 SSE 연결 생성
- 로그아웃 시 연결 종료
- `@microsoft/fetch-event-source` 사용 (Authorization 헤더 지원)
- 연결 끊김 시 자동 재연결 (최대 5회, 지수 백오프)

### SSE 이벤트별 처리

| 이벤트 | React Query 무효화 | 추가 동작 |
|--------|-------------------|----------|
| connect | - | 연결 확인 |
| notification | `['notifications']` | 토스트 알림 표시 |
| camera | `['cameras']`, `['streams']` | - |
| event | `['events']`, `['eventLogs']` | - |
| member | `['users']` | - |

### useStreams()

- React Query 래퍼
- `camerasApi.getAll()` 호출

### useEventLogs()

- React Query 래퍼
- `eventsApi.getAll()` 호출

---

## 전역 WebRTC 연결 (WebRTCContext)

### WebRTCProvider

- 전역 WebRTC 연결 관리 (싱글톤 패턴)
- 페이지 이동해도 스트림 연결 유지
- 현재 그리드에 표시된 카메라만 연결 유지

### 주요 기능

| 기능 | 설명 |
|------|------|
| `connectStream(cameraId)` | WebRTC 연결 시작 |
| `disconnectStream(cameraId)` | WebRTC 연결 종료 |
| `setActiveGridCameras(ids)` | 현재 그리드 카메라 설정 |
| `subscribeToStream(cameraId, callback)` | 스트림 상태 구독 |

### 스트림 상태

| 상태 | 설명 |
|------|------|
| `connecting` | 연결 중 |
| `connected` | 연결 완료 |
| `playing` | 재생 중 |
| `disconnected` | 연결 종료 |
| `error` | 오류 발생 |

### CCTVGrid 연동

- 페이지 변경 시 `localStorage`에 현재 페이지 저장
- 페이지 이동 후 돌아오면 이전 페이지 복원
- `setActiveGridCameras()` 호출로 그리드 외 카메라 연결 해제
- SSE로 카메라 변경 감지 시 자동 그리드 갱신
- `selectedCamera`는 `cameras` prop에서 `useMemo`로 파생 (항상 최신 상태)
- 공통 컴포넌트: `StatusBadges`, `ConnectionBadge`, `CameraInfo`, `OffOverlay`, `OfflineOverlay`

---

## API 클라이언트

### authApi

| 메서드 | 설명 |
|--------|------|
| login | 로그인 |
| signup | 회원가입 |
| logout | 로그아웃 |
| refresh | 토큰 갱신 |
| me | 내 정보 |
| changePassword | 비밀번호 변경 |
| updateProfile | 프로필 수정 |
| deleteAccount | 회원탈퇴 |

### camerasApi

| 메서드 | 설명 |
|--------|------|
| getAll | 카메라 목록 (페이지네이션) |
| getAllList | 카메라 전체 목록 (멤버 관리용) |
| update | 카메라 수정 |

### eventsApi

| 메서드 | 설명 |
|--------|------|
| getAll | 이벤트 목록 |
| getClipBlobUrl | 클립 Blob URL (인증 포함) |
| downloadClip | 클립 다운로드 (인증 포함) |

### notificationsApi

| 메서드 | 설명 |
|--------|------|
| getAll | 알림 목록 |
| deleteAll | 전체 삭제 (모달 닫을 때 호출) |

### statsApi

| 메서드 | 설명 |
|--------|------|
| getDaily | 일별 통계 |
| getEventTypes | 유형별 통계 |
| getMonthly | 월별 통계 |

### usersApi

| 메서드 | 설명 |
|--------|------|
| getAll | 사용자 목록 |
| update | 사용자 수정 |
| delete | 사용자 삭제 |
| approve | 사용자 승인 |
