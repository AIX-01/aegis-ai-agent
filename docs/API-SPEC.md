# API 명세

> AEGIS - CCTV 실시간 AI 안전 모니터링 시스템

---

## Auth API

### POST /api/auth/login

로그인

**Request:**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| email | string | O | 이메일 |
| password | string | O | 비밀번호 |

**Response:** `200 OK`

| 필드 | 타입 | 설명 |
|------|------|------|
| accessToken | string | JWT 액세스 토큰 |
| user | User | 사용자 정보 |

**Cookie:** `refreshToken` (HttpOnly, Secure, 7일)

**에러:** EMAIL_NOT_FOUND, INVALID_PASSWORD, USER_NOT_APPROVED, USER_DELETED

---

### POST /api/auth/signup

회원가입

**Request:**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| email | string | O | 이메일 |
| password | string | O | 비밀번호 |
| name | string | O | 이름 |

**Response:** `200 OK`

| 필드 | 타입 | 설명 |
|------|------|------|
| success | boolean | true |
| message | string | "회원가입이 완료되었습니다. 관리자 승인 후 로그인이 가능합니다." |

**에러:** DUPLICATE_EMAIL

---

### POST /api/auth/logout

로그아웃 (인증 필요)

**Response:** `200 OK`

| 필드 | 타입 | 설명 |
|------|------|------|
| success | boolean | true |

---

### POST /api/auth/refresh

토큰 갱신

**Cookie:** `refreshToken` 필요

**Response:** `200 OK`

| 필드 | 타입 | 설명 |
|------|------|------|
| accessToken | string | 새 JWT 액세스 토큰 |

**에러:** REFRESH_TOKEN_NOT_FOUND, INVALID_REFRESH_TOKEN

---

### GET /api/auth/me

내 정보 조회 (인증 필요)

**Response:** `200 OK` → User

---

### PATCH /api/auth/me

프로필 수정 (인증 필요)

**Request:**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| name | string | O | 새 이름 |

**Response:** `200 OK` → User

---

### DELETE /api/auth/me

회원탈퇴 (인증 필요, 소프트 삭제)

**Response:** `200 OK`

| 필드 | 타입 | 설명 |
|------|------|------|
| success | boolean | true |
| message | string | "회원탈퇴가 완료되었습니다." |

---

### PATCH /api/auth/password

비밀번호 변경 (인증 필요)

**Request:**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| currentPassword | string | O | 현재 비밀번호 |
| newPassword | string | O | 새 비밀번호 |

**Response:** `200 OK`

| 필드 | 타입 | 설명 |
|------|------|------|
| success | boolean | true |
| message | string | "비밀번호가 변경되었습니다." |

**에러:** CURRENT_PASSWORD_MISMATCH, PASSWORD_TOO_SHORT

---

## Camera API

### GET /api/cameras

카메라 목록 조회 (인증 필요)

**정렬:** connected DESC → enabled DESC → location ASC

**권한:** ADMIN은 전체, USER는 할당된 카메라만

**Response:** `200 OK` → Camera[]

---

### GET /api/cameras/{id}

카메라 상세 조회 (인증 필요)

**Response:** `200 OK` → Camera

**에러:** CAMERA_NOT_FOUND

---

### PATCH /api/cameras/{id}

카메라 수정 (인증 필요)

**Request:**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| location | string | X | 장소 |
| enabled | boolean | X | 활성화 (false시 analysisEnabled도 false) |
| analysisEnabled | boolean | X | AI 분석 활성화 (enabled=true일 때만) |

**Response:** `200 OK` → Camera

**Side Effect:**

- enabled/analysisEnabled 변경 시 → Redis Pub/Sub 발행
- SSE `camera` 이벤트 브로드캐스트

---


## Event API

### GET /api/events

이벤트 목록 조회 (인증 필요, 페이지네이션)

**Query Parameters:**

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| page | number | 0 | 페이지 번호 (0부터 시작) |
| size | number | 20 | 페이지 크기 |

**Response:** `200 OK` → PageResponse\<Event\>

| 필드 | 타입 | 설명 |
|------|------|------|
| content | Event[] | 이벤트 목록 |
| page | number | 현재 페이지 |
| size | number | 페이지 크기 |
| totalElements | number | 전체 개수 |
| totalPages | number | 전체 페이지 수 |
| first | boolean | 첫 페이지 여부 |
| last | boolean | 마지막 페이지 여부 |

---

### GET /api/events/{id}

이벤트 상세 조회 (인증 필요)

**Response:** `200 OK` → Event

**에러:** EVENT_NOT_FOUND

---


### DELETE /api/events/{id}

이벤트 삭제 (Admin 전용)

- S3에서 클립 삭제 + DB에서 연관 알림 삭제 + 이벤트 삭제

**Response:** `200 OK`

| 필드 | 타입 | 설명 |
|------|------|------|
| success | boolean | true |
| message | string | "이벤트가 삭제되었습니다." |

**Side Effect:** SSE `event-deleted` 이벤트 브로드캐스트

---

### GET /api/events/{id}/clip

클립 다운로드 (인증 필요)

**Response:** `200 OK`

- Content-Type: video/mp4
- Content-Disposition: attachment; filename="event_{id}.mp4"

---

### GET /api/events/{id}/clip/stream

클립 스트리밍 (인증 필요, Range 지원)

**Request Header:**

| 헤더 | 설명 |
|------|------|
| Range | bytes=start-end (선택) |

**Response:** `200 OK` 또는 `206 Partial Content`

- Content-Type: video/mp4
- Accept-Ranges: bytes
- Content-Range: bytes start-end/total (206일 때)

---

## Notification API

### GET /api/notifications

알림 목록 조회 (인증 필요)

**Response:** `200 OK` → Notification[]

---

### GET /api/notifications/stream

SSE 스트림 연결 (인증 필요)

**Response:** `200 OK` (text/event-stream)

**이벤트:**

| 이벤트 | 데이터 | 범위 | 설명 |
|--------|--------|------|------|
| connect | "SSE 연결 성공" | 개별 | 연결 확인 |
| notification | Notification (JSON) | 개별 | 새 알림 |
| camera | Camera 또는 "refresh" | 전체 | 카메라 변경 |
| event | Event (JSON) | 전체 | 이벤트 변경 |
| member | User (JSON) | 전체 | 멤버 변경 |

---

### GET /api/notifications/unread-count

읽지 않은 알림 수 (인증 필요)

**Response:** `200 OK`

| 필드 | 타입 | 설명 |
|------|------|------|
| count | number | 읽지 않은 수 |

---

### PATCH /api/notifications/{id}/read

알림 읽음 처리 (인증 필요)

**Response:** `200 OK` → Notification

---

### POST /api/notifications/read-all

전체 읽음 처리 (인증 필요)

**Response:** `200 OK`

| 필드 | 타입 | 설명 |
|------|------|------|
| success | boolean | true |

---

### DELETE /api/notifications/{id}

알림 삭제 (인증 필요)

**Response:** `200 OK`

| 필드 | 타입 | 설명 |
|------|------|------|
| success | boolean | true |

---

## Stats API

### GET /api/stats

통계 조회 (인증 필요)

**Query:**

| 파라미터 | 값 | 설명 |
|----------|-----|------|
| type | 없음 | 전체 통계 |
| type | daily | 최근 7일 일별 |
| type | event-types | 유형별 분포 |
| type | monthly | 월별 캘린더 |

**Response (type 없음):** `200 OK`

| 필드 | 타입 | 설명 |
|------|------|------|
| daily | DailyStat[] | 일별 통계 |
| eventTypes | EventTypeStat[] | 유형별 통계 |
| monthly | Map<string, MonthlyData> | 월별 통계 |

---

## User API (Admin 전용)

### GET /api/users

사용자 목록 조회 (페이지네이션)

**Query Parameters:**

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| page | number | 0 | 페이지 번호 (0부터 시작) |
| size | number | 20 | 페이지 크기 |

**Response:** `200 OK` → PageResponse\<User\>

| 필드 | 타입 | 설명 |
|------|------|------|
| content | User[] | 사용자 목록 |
| page | number | 현재 페이지 |
| size | number | 페이지 크기 |
| totalElements | number | 전체 개수 |
| totalPages | number | 전체 페이지 수 |
| first | boolean | 첫 페이지 여부 |
| last | boolean | 마지막 페이지 여부 |

---

### GET /api/users/{id}

사용자 상세 조회

**Response:** `200 OK` → User

**에러:** USER_NOT_FOUND_BY_ID

---

### PATCH /api/users/{id}

사용자 수정

**Request:**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| name | string | X | 이름 |
| role | string | X | "user" 또는 "admin" |
| assignedCameras | string[] | X | 할당 카메라 ID 목록 |

**Response:** `200 OK` → User

**Side Effect:** SSE `member` 이벤트 브로드캐스트

---

### DELETE /api/users/{id}

사용자 삭제

**Response:** `200 OK`

| 필드 | 타입 | 설명 |
|------|------|------|
| success | boolean | true |

**Side Effect:** SSE `member` 이벤트 브로드캐스트

---

### PATCH /api/users/{id}/approve

사용자 승인

**Response:** `200 OK` → User

**Side Effect:** SSE `member` 이벤트 브로드캐스트

---

## Internal API (내부망)

### POST /internal/mediamtx/sync

카메라 동기화 트리거 (MediaMTX → Spring)

**Request:** 아무 JSON (또는 빈 body)

**Response:** `200 OK`

| 필드 | 타입 | 설명 |
|------|------|------|
| success | boolean | true |

**로직:**

1. Redis `mediamtx:sync:lock` 잠금 확인
2. 잠금 획득 → 1초 대기 (연속 이벤트 병합)
3. MediaMTX `GET /v3/paths/list` 호출
4. 새 카메라: `connected=true, enabled=false, analysisEnabled=false`
5. 기존 카메라: `connected` 상태만 업데이트
6. 변경 시 SSE `camera: "refresh"` 브로드캐스트
7. 변경 시 Redis Pub/Sub `camera:analysis:update` 발행

---

### POST /internal/mediamtx/auth

스트림 인증 검증 (MediaMTX → Spring)

**Request:**

| 필드 | 타입 | 설명 |
|------|------|------|
| user | string | Basic Auth 사용자 |
| password | string | Basic Auth 비밀번호 |
| ip | string | 클라이언트 IP |
| action | string | "read" 또는 "publish" |
| path | string | 스트림 경로 |
| protocol | string | "webrtc", "hls", "rtsp" |
| id | string | 연결 ID |
| query | string | 쿼리스트링 |
| jwt | string | JWT 토큰 |

**Response:**

- `200 OK`: 인증 성공
- `401 Unauthorized`: 인증 실패

**로직:**

- action=publish: 항상 통과 (MediaMTX 내부 인증)
- protocol=rtsp/hls: 항상 통과 (내부 사용)
- protocol=webrtc, action=read: 토큰 검증 (query에서 `token=` 추출)
  - Redis에서 `stream_token:{token}` 조회 및 삭제 (일회용)

---


### POST /internal/agent/events

이벤트 생성 (Agent → Spring)

- 클립 추출은 비동기로 수행됨

**Request:**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| cameraId | string | O | 카메라 UUID |
| risk | string | O | normal/suspicious/abnormal |
| type | string | O | assault/burglary/dump/swoon/vandalism |
| occurredAt | string | X | ISO8601 (기본: 현재) |

**Response:** `201 Created`

| 필드 | 타입 | 설명 |
|------|------|------|
| eventId | string | 생성된 이벤트 ID |

**로직:**

1. cameraId로 카메라 조회
2. DB에 Event 저장 (status=PROCESSING)
3. 비동기: HLS 세그먼트 다운로드 → MinIO 업로드
4. 카메라 권한 있는 사용자에게 Notification 생성 (ALERT)
5. SSE `notification` 개별 전송
6. SSE `event` 전체 브로드캐스트

---

### PATCH /internal/agent/events/{id}/analysis

분석 결과 추가 (Agent → Spring)

**Request:**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| summary | string | X | 요약 |
| riskScore | string | X | 위험 점수 (예: HIGH, MEDIUM, LOW) |
| actions | object[] | X | 권장 조치 목록 (JSON) |
| ragReferences | object[] | X | RAG 참조 자료 (JSON) |
| report | string | X | 상세 리포트 |

**Response:** `200 OK`

| 필드 | 타입 | 설명 |
|------|------|------|
| eventId | string | 이벤트 ID |

**Side Effect:**

1. Event 업데이트 (status=ANALYZED)
2. 카메라 권한 있는 사용자에게 Notification 생성 (WARNING)
3. SSE `notification` 개별 전송
4. SSE `event` 전체 브로드캐스트

---

## DTO 정의

### User

| 필드 | 타입 | 설명 |
|------|------|------|
| id | string | UUID |
| email | string | 이메일 |
| name | string | 이름 |
| role | "user" \| "admin" | 역할 |
| assignedCameras | string[] | 할당된 카메라 ID |
| createdAt | string | 생성일 (ISO8601) |
| approved | boolean | 승인 여부 |

### Camera

| 필드 | 타입 | 설명 |
|------|------|------|
| id | string | UUID |
| name | string | MediaMTX 스트림 이름 |
| location | string | 사용자 지정 장소 |
| connected | boolean | MediaMTX 연결 상태 |
| enabled | boolean | 메인 활성화 스위치 |
| analysisEnabled | boolean | AI 분석 활성화 |

### Event

| 필드 | 타입 | 설명 |
|------|------|------|
| id | string | UUID |
| cameraId | string | 카메라 ID |
| cameraName | string | 카메라 장소 |
| risk | string | 위험 수준 (normal/suspicious/abnormal) |
| type | string | 이벤트 타입 |
| occurredAt | string | 발생 시각 (ISO8601) |
| status | "processing" \| "analyzed" | 상태 |
| clipUrl | string? | 클립 키 |
| summary | string? | 요약 |
| riskScore | string? | 위험 점수 |
| actions | object[]? | 권장 조치 (JSON) |
| ragReferences | object[]? | RAG 참조 (JSON) |
| report | string? | 상세 리포트 |

### Notification

| 필드 | 타입 | 설명 |
|------|------|------|
| id | string | UUID |
| type | "alert" \| "warning" \| "info" \| "success" | 타입 |
| title | string | 제목 |
| message | string | 내용 |
| timestamp | string | 생성일 (ISO8601) |
| read | boolean | 읽음 여부 |
| eventId | string? | 연결된 이벤트 ID |

### DailyStat

| 필드 | 타입 | 설명 |
|------|------|------|
| day | string | 날짜 |
| events | number | 이벤트 수 |
| analyzed | number | 분석 완료 수 |

### EventTypeStat

| 필드 | 타입 | 설명 |
|------|------|------|
| type | string | 이벤트 타입 |
| count | number | 개수 |
| color | string | 차트 색상 |

### MonthlyData

| 필드 | 타입 | 설명 |
|------|------|------|
| events | number | 이벤트 수 |
| alerts | number | 알림 수 |

