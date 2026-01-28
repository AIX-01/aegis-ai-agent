# 데이터 모델

> AEGIS - CCTV 실시간 AI 안전 모니터링 시스템

---

## ERD

```mermaid
erDiagram
    users ||--o{ user_cameras : has
    users ||--o{ notifications : receives
    cameras ||--o{ user_cameras : assigned_to
    cameras ||--o{ events : generates
    events ||--o{ notifications : triggers

    users {
        uuid id PK
        varchar email
        varchar password
        varchar name
        user_role role
        boolean approved
        boolean deleted
        timestamp deleted_at
        timestamp created_at
        timestamp updated_at
    }

    cameras {
        uuid id PK
        varchar name
        varchar alias
        boolean connected
        boolean enabled
        boolean analysis_enabled
        timestamp created_at
        timestamp updated_at
    }

    user_cameras {
        uuid id PK
        uuid user_id FK
        uuid camera_id FK
    }

    events {
        uuid id PK
        uuid camera_id FK
        event_type type
        timestamp timestamp
        event_status status
        text description
        text agent_action
        varchar clip_url
        text summary
        text analysis_report
        timestamp created_at
        timestamp updated_at
    }

    notifications {
        uuid id PK
        uuid user_id FK
        uuid event_id FK
        notification_type type
        varchar title
        text message
        boolean read
        timestamp created_at
    }
```

---

## 테이블 상세

### users

| 컬럼 | 타입 | NULL | 제약조건 | 기본값 |
|------|------|------|----------|--------|
| id | uuid | NO | PK | auto |
| email | varchar(255) | NO | UNIQUE | - |
| password | varchar(255) | NO | - | - |
| name | varchar(100) | NO | - | - |
| role | user_role | NO | - | USER |
| approved | boolean | NO | - | false |
| deleted | boolean | NO | - | false |
| deleted_at | timestamp | YES | - | - |
| created_at | timestamp | NO | - | auto |
| updated_at | timestamp | NO | - | auto |

### cameras

| 컬럼 | 타입 | NULL | 제약조건 | 기본값 |
|------|------|------|----------|--------|
| id | uuid | NO | PK | auto |
| name | varchar(50) | NO | UNIQUE | - |
| alias | varchar(100) | NO | - | =name |
| connected | boolean | NO | - | false |
| enabled | boolean | NO | - | false |
| analysis_enabled | boolean | NO | - | false |
| created_at | timestamp | NO | - | auto |
| updated_at | timestamp | NO | - | auto |

### user_cameras

| 컬럼 | 타입 | NULL | 제약조건 | 기본값 |
|------|------|------|----------|--------|
| id | uuid | NO | PK | auto |
| user_id | uuid | NO | FK(users.id), UK | - |
| camera_id | uuid | NO | FK(cameras.id), UK | - |

> UK: user_id + camera_id 조합에 대한 유니크 제약조건

### events

| 컬럼 | 타입 | NULL | 제약조건 | 기본값 |
|------|------|------|----------|--------|
| id | uuid | NO | PK | auto |
| camera_id | uuid | NO | FK(cameras.id) | - |
| type | event_type | NO | - | - |
| timestamp | timestamp | NO | - | - |
| status | event_status | NO | - | PROCESSING |
| description | text | NO | - | - |
| agent_action | text | YES | - | - |
| clip_url | varchar(500) | YES | - | - |
| summary | text | YES | - | - |
| analysis_report | text | YES | - | - |
| created_at | timestamp | NO | - | auto |
| updated_at | timestamp | NO | - | auto |

### notifications

| 컬럼 | 타입 | NULL | 제약조건 | 기본값 |
|------|------|------|----------|--------|
| id | uuid | NO | PK | auto |
| user_id | uuid | NO | FK(users.id) | - |
| event_id | uuid | YES | FK(events.id) | - |
| type | notification_type | NO | - | - |
| title | varchar(200) | NO | - | - |
| message | text | NO | - | - |
| read | boolean | NO | - | false |
| created_at | timestamp | NO | - | auto |


---

## Enum 값

### UserRole

| 값 | API 값 | 설명 |
|-----|--------|------|
| ADMIN | "admin" | 관리자 (모든 권한) |
| USER | "user" | 일반 사용자 (할당 카메라만) |

### EventType

| 값 | API 값 | 설명 |
|-----|--------|------|
| ASSAULT | "assault" | 폭행 |
| BURGLARY | "burglary" | 절도 |
| DUMP | "dump" | 투기 |
| SWOON | "swoon" | 실신 |
| VANDALISM | "vandalism" | 파손 |

### EventStatus

| 값 | API 값 | 설명 |
|-----|--------|------|
| PROCESSING | "processing" | 분석 중 |
| RESOLVED | "resolved" | 완료 |

### NotificationType

| 값 | API 값 | 설명 |
|-----|--------|------|
| ALERT | "alert" | 긴급 (폭행, 절도) |
| WARNING | "warning" | 경고 (투기, 실신, 파손) |
| INFO | "info" | 정보 |
| SUCCESS | "success" | 성공 |

---

## 인덱스

### users

- `idx_users_email` (email)
- `idx_users_approved` (approved)

### cameras

- `idx_cameras_connected` (connected)
- `idx_cameras_enabled` (enabled)
- `idx_cameras_analysis_enabled` (analysis_enabled)

### user_cameras

- `uk_user_cameras_user_camera` UNIQUE (user_id, camera_id)
- `idx_user_cameras_user_id` (user_id)
- `idx_user_cameras_camera_id` (camera_id)

### events

- `idx_events_camera_id` (camera_id)
- `idx_events_type` (type)
- `idx_events_status` (status)
- `idx_events_timestamp` (timestamp)

### notifications

- `idx_notifications_user_id` (user_id)
- `idx_notifications_user_read` (user_id, read)
- `idx_notifications_created_at` (created_at)

---

## Redis 키

| 키 패턴 | 값 | TTL |
|---------|----|----|
| `refresh_token:{token}` | userId | 7일 |
| `mediamtx:sync:lock` | "locked" | 1초 |
| `analysis:cameras` | JSON: [{name, alias}, ...] | 없음 |

### Pub/Sub 채널

| 채널 | 메시지 | 구독자 |
|------|--------|--------|
| `camera:analysis:update` | "sync" | Python Agent |

---

## MinIO 버킷

```
files/
└── clips/
    └── {clipId}/
        └── clip.mp4
```

---

## 카메라 규칙

### 활성화 구조

- `enabled=false` → analysisEnabled도 자동 false
- `enabled=true, analysisEnabled=false` → 스트림만 표시
- `enabled=true, analysisEnabled=true` → 스트림 + AI 분석

### 정렬 순서

1. `connected` DESC (온라인 우선)
2. `enabled` DESC (활성화 우선)
3. `alias` ASC (별칭 이름순)
