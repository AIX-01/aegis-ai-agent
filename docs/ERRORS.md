# 에러 코드

> AEGIS - CCTV 실시간 AI 안전 모니터링 시스템

---

## Auth 에러

| 코드 | HTTP | 메시지 |
|------|------|--------|
| EMAIL_NOT_FOUND | 401 | 등록되지 않은 이메일입니다. |
| INVALID_PASSWORD | 401 | 비밀번호가 일치하지 않습니다. |
| USER_NOT_APPROVED | 403 | 관리자 승인 대기 중입니다. |
| DUPLICATE_EMAIL | 400 | 이미 등록된 이메일입니다. |
| REFRESH_TOKEN_NOT_FOUND | 401 | Refresh token이 없습니다. |
| INVALID_REFRESH_TOKEN | 401 | 유효하지 않은 refresh token입니다. |
| INVALID_USER | 401 | 유효하지 않은 사용자입니다. |
| AUTHENTICATION_REQUIRED | 401 | 인증이 필요합니다. |
| USER_NOT_FOUND | 401 | 사용자를 찾을 수 없습니다. |
| CURRENT_PASSWORD_MISMATCH | 400 | 현재 비밀번호가 일치하지 않습니다. |
| PASSWORD_TOO_SHORT | 400 | 새 비밀번호는 6자 이상이어야 합니다. |
| USER_DELETED | 403 | 탈퇴한 계정입니다. |

---

## User 에러

| 코드 | HTTP | 메시지 |
|------|------|--------|
| USER_ID_REQUIRED | 400 | 사용자 ID가 필요합니다. |
| USER_NOT_FOUND_BY_ID | 404 | 사용자를 찾을 수 없습니다. |

---

## Camera 에러

| 코드 | HTTP | 메시지 |
|------|------|--------|
| CAMERA_NOT_FOUND | 404 | 카메라를 찾을 수 없습니다. |
| CAMERA_ACCESS_DENIED | 403 | 해당 카메라에 대한 접근 권한이 없습니다. |
| CAMERA_NOT_CONNECTED | 400 | 카메라가 연결되어 있지 않습니다. |
| CAMERA_NOT_ACTIVE | 400 | 카메라가 비활성화 상태입니다. |

---

## Event 에러

| 코드 | HTTP | 메시지 |
|------|------|--------|
| EVENT_NOT_FOUND | 404 | 이벤트를 찾을 수 없습니다. |

---

## Notification 에러

| 코드 | HTTP | 메시지 |
|------|------|--------|
| NOTIFICATION_NOT_FOUND | 404 | 알림을 찾을 수 없습니다. |

---

## Storage 에러

| 코드 | HTTP | 메시지 |
|------|------|--------|
| S3_UPLOAD_FAILED | 500 | S3 업로드에 실패했습니다. |
| S3_DOWNLOAD_FAILED | 500 | S3 다운로드에 실패했습니다. |
| S3_DELETE_FAILED | 500 | S3 삭제에 실패했습니다. |
| CLIP_EXTRACTION_FAILED | 500 | 클립 추출에 실패했습니다. |
| CAMERA_NOT_FOUND_FOR_CLIP | 404 | 클립 추출을 위한 카메라를 찾을 수 없습니다. |

---

## General 에러

| 코드 | HTTP | 메시지 |
|------|------|--------|
| FORBIDDEN | 403 | 권한이 없습니다. |
| INTERNAL_SERVER_ERROR | 500 | 서버 내부 오류가 발생했습니다. |
