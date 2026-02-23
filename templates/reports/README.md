# 보고서 템플릿

이 폴더에는 보고서 생성을 위한 HTML 템플릿 파일이 위치합니다.

## 템플릿 파일

| 파일명 | 설명 |
|-------|------|
| `report_template.html` | HTML 보고서 템플릿 |

## 템플릿 플레이스홀더

템플릿 내에서 다음 플레이스홀더를 사용할 수 있습니다:

| 플레이스홀더 | 설명 |
|-------------|------|
| `{{event_id}}` | 이벤트 ID |
| `{{occurred_at}}` | 발생 일시 |
| `{{camera_name}}` | 카메라 이름 |
| `{{camera_location}}` | 카메라 위치 |
| `{{event_type}}` | 이벤트 유형 (ASSAULT, BURGLARY 등) |
| `{{event_type_korean}}` | 이벤트 유형 한글 |
| `{{risk_level}}` | 위험도 (ABNORMAL, SUSPICIOUS) |
| `{{summary}}` | 상황 요약 |
| `{{frames}}` | 캡처 프레임 이미지 (base64 img 태그) |
| `{{actions}}` | 대응 조치 목록 |
| `{{generated_at}}` | 보고서 생성 시각 |
| `{{status_text}}` | 분석 상태 텍스트 |
| `{{version}}` | 버전 |

## 처리 흐름

`generate_report` 노드에서 이 템플릿을 로드하여 플레이스홀더를 치환한 후,
백엔드 API (`PATCH /internal/agent/events/{eventId}`)의 `report` 필드로 HTML 문자열을 전달합니다.
