# 보고서 템플릿

이 폴더에는 보고서 생성을 위한 템플릿 파일들이 위치합니다.

## 필요한 템플릿 파일

| 파일명 | 포맷 | 설명 |
|-------|------|------|
| `report_template.docx` | Word | Word 문서 템플릿 |
| `report_template.pptx` | PowerPoint | 프레젠테이션 템플릿 |
| `report_template.html` | HTML | PDF 변환용 HTML 템플릿 |
| `report_template.hwp` | 한글 | 한글 문서 템플릿 (옵션) |

## 템플릿 플레이스홀더

템플릿 내에서 다음 플레이스홀더를 사용할 수 있습니다:

| 플레이스홀더 | 설명 |
|-------------|------|
| `{{title}}` | 보고서 제목 |
| `{{occurred_at}}` | 발생 일시 |
| `{{camera_name}}` | 카메라 이름 |
| `{{camera_location}}` | 카메라 위치 |
| `{{event_type}}` | 이벤트 유형 (ASSAULT, BURGLARY 등) |
| `{{risk_level}}` | 위험도 (ABNORMAL, SUSPICIOUS) |
| `{{risk_score}}` | 위험 점수 (0.0 ~ 1.0) |
| `{{summary}}` | 상황 요약 |
| `{{actions}}` | 대응 조치 목록 |
| `{{generated_at}}` | 보고서 생성 시각 |

## 예시

### Word (docx) 템플릿
```
# {{title}}

## 1. 개요
- 발생 일시: {{occurred_at}}
- 위치: {{camera_name}} ({{camera_location}})
- 이벤트 유형: {{event_type}}
- 위험도: {{risk_level}} (점수: {{risk_score}})

## 2. 상황 요약
{{summary}}

## 3. 대응 조치
{{actions}}

---
보고서 생성 시각: {{generated_at}}
담당 시스템: AEGIS AI Agent
```

