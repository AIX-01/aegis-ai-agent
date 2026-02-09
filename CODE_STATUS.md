# AEGIS AI Agent 코드 상태 분석

> 최종 갱신일: 2026-02-09

## 📊 전체 구조

```
src/
├── app.py                  ✅ 완료 - 메인 오케스트레이터
├── config.py               ✅ 완료 - 설정 관리
├── utils.py                ✅ 완료 - 유틸리티
├── api/
│   └── mock_server.py      ✅ 완료 - Mock 서버 (VLM, Precision, Backend)
├── clients/
│   ├── backend_client.py   ✅ 완료 - 백엔드 API 클라이언트
│   ├── vlm_client.py       ✅ 완료 - VLM 클라이언트
│   ├── precision_client.py ✅ 완료 - 정밀 분석 클라이언트
│   ├── vector_store_client.py ✅ 완료 - Qdrant 벡터 스토어
│   ├── verification_client.py ✅ 완료 - 검증 클라이언트
│   └── openai_client.py    ✅ 완료 - OpenAI API 래퍼
├── core/
│   ├── consumer.py         ✅ 완료 - 분석 워커 풀
│   ├── producer.py         ✅ 완료 - RTSP 스트림 프로듀서
│   ├── windowing.py        ✅ 완료 - 윈도우 매니저
│   ├── queue_manager.py    ✅ 완료 - 작업 큐 관리
│   ├── redis_manager.py    ✅ 완료 - Redis Pub/Sub
│   ├── muxer.py            ✅ 완료 - MP4 Muxing
│   └── packet_buffer.py    ✅ 완료 - 패킷 버퍼
├── graph/
│   ├── analysis_graph.py   ✅ 완료 - LangGraph 메인 그래프
│   ├── state.py            ✅ 완료 - 상태 정의
│   ├── edges/              ✅ 완료 - 조건부 라우터
│   ├── nodes/
│   │   ├── precision_analysis.py  ✅ 완료
│   │   ├── verification.py        ✅ 완료
│   │   ├── update_backend.py      ✅ 완료
│   │   └── store_embedding.py     ✅ 완료
│   └── subgraphs/
│       └── response_agent.py      ⚠️ 일부 Mock
├── services/
│   ├── __init__.py         ✅ 완료
│   └── report_generator.py ✅ 완료 - 보고서 생성 서비스
└── tools/
    ├── embedding_tools.py  ✅ 완료
    └── search_tools.py     ✅ 완료
```

---

## 🚀 실행 방법

### CLI 옵션

| 옵션 | 설명 |
|------|------|
| `python -m src.app` | 전체 Mock 모드 |
| `python -m src.app --real-backend` | 백엔드 전체 실제 서버 |
| `python -m src.app --real-backend-events-only` | 1차/2차 갱신 + 클립만 실제, 보고서는 Mock |
| `python -m src.app --no-mock` | 전체 실제 서버 |

### `--real-backend-events-only` 실행 시 상태

| 컴포넌트 | 연결 대상 | 상태 |
|----------|----------|------|
| VLM 1차 분석 | Mock (localhost:8001) | **Mock** |
| 정밀 분석 | OpenAI API | 실제 |
| 검증 | OpenAI API | 실제 |
| 임베딩 | OpenAI API | 실제 |
| Qdrant 저장 | Qdrant (localhost:6333) | 실제 |
| 1차 백엔드 갱신 | 백엔드 (localhost:8080) | **실제** |
| 2차 백엔드 갱신 | 백엔드 (localhost:8080) | **실제** |
| 클립 업로드 | 백엔드 (localhost:8080) | **실제** |
| 보고서 업로드 | Mock (localhost:8088) | **Mock → 로컬 저장** |

---

## ⚠️ 미완성/Mock 상태인 부분

### 1. `response_agent.py` - 대응 조치 도구들 (Mock)

**파일**: `src/graph/subgraphs/response_agent.py`

#### 1.1 `execute_field_action` (Mock)
```python
# Mock 응답 - 실제 구현 시 장비 제어 API 호출
```
**필요 작업**: 실제 CCTV 장비 제어 API 연동
- BROADCAST: 스피커 방송 API
- LIGHT_ON: 조명 제어 API
- PTZ_TRACK: PTZ 카메라 제어 API
- SIREN: 사이렌 제어 API

#### 1.2 `emergency_call` (Mock)
```python
# Mock 응답 - 실제 구현 시 신고 API 연동
```
**필요 작업**: 실제 신고 시스템 연동
- 112 경찰 신고 API
- 119 소방/응급 신고 API
- 내부 보안팀 호출 시스템
- 관리사무소 알림 시스템

#### 1.3 `search_protocol_and_cases` - 대응 매뉴얼 (하드코딩)
```python
# 대응 매뉴얼 (현재는 하드코딩 - 추후 manuals 컬렉션 구현 시 연동)
manual_templates = { ... }
```
**필요 작업**: 
- `manuals` 컬렉션 생성 및 데이터 적재
- Qdrant 검색 연동 (현재 `past_cases`만 검색)

---

## ✅ 완료된 주요 기능

| 기능 | 상태 | 설명 |
|------|------|------|
| RTSP 스트림 수집 | ✅ | Producer + PacketBuffer |
| 윈도우 기반 프레임 추출 | ✅ | WindowManager |
| VLM 1차 분석 | ✅ | VLMClient (Mock/Real 지원) |
| 백엔드 이벤트 생성 | ✅ | BackendClient.send_vlm_result() |
| LangGraph 정밀 분석 | ✅ | PrecisionAnalysisNode |
| 검증 (Verification) | ✅ | VerificationNode (OpenAI Vision) |
| 백엔드 갱신 | ✅ | UpdateBackendNode |
| 벡터 임베딩 저장 | ✅ | StoreEmbeddingNode + Qdrant |
| 과거 사례 검색 | ✅ | search_protocol_and_cases (past_cases) |
| ReAct Agent | ✅ | ResponseAgent 서브그래프 |
| 보고서 생성 | ✅ | ReportGeneratorService (PDF, DOCX, PPTX) |
| 보고서 업로드 | ✅ | Mock 서버 → 로컬 저장 |
| 클립 MP4 생성 | ✅ | muxer.py |
| 클립 업로드 | ✅ | 실제 백엔드 연동 가능 |
| Mock 서버 | ✅ | VLM, Precision, Backend |

---

## 📋 우선순위별 남은 작업

> 아래 항목들은 **운영 환경에서 실제 장비와 연동**할 때 필요한 작업입니다.  
> **현재 테스트 단계에서는 Mock으로 충분**하며, 실제 운영 시 필요에 따라 구현하면 됩니다.

### 🟡 중간 (운영 환경 연동 시 필요)

#### 1. 대응 매뉴얼 DB화 (현재: 코드에 하드코딩)

**현재 상태:**
```python
# response_agent.py에 직접 작성됨
manual_templates = {
    "ASSAULT": "1. 112 신고 2. 보안팀 출동...",
    "BURGLARY": "1. PTZ 추적 2. 112 신고...",
}
```

**개선하면:**
- 매뉴얼을 Qdrant DB에 저장
- 코드 수정 없이 매뉴얼 추가/변경 가능
- 상황에 맞는 매뉴얼을 검색해서 가져옴

---

#### 2. 실제 CCTV 장비 제어 (현재: Mock - 가짜 응답만 반환)

**현재 상태:**
```python
def execute_field_action(action_name, camera_id):
    return "✅ 성공"  # 실제로는 아무것도 안 함
```

**실제 연동하면:**
| 액션 | 실제 동작 |
|------|----------|
| BROADCAST | 스피커에서 진짜 방송 나감 |
| PTZ_TRACK | 카메라가 진짜로 대상 추적 |
| LIGHT_ON | 조명이 진짜로 켜짐 |
| SIREN | 사이렌이 진짜로 울림 |

---

#### 3. 긴급 신고 시스템 연동 (현재: Mock - 가짜 응답만 반환)

**현재 상태:**
```python
def emergency_call(agency_type, situation_report):
    return "✅ 접수 완료"  # 실제로는 신고 안 됨
```

**실제 연동하면:**
| 기관 | 실제 동작 |
|------|----------|
| 112_POLICE | 경찰에 진짜 신고 접수 |
| 119_FIRE | 소방/응급에 진짜 신고 접수 |
| SECURITY_TEAM | 보안팀에 진짜 알림 전송 |

---

### 🟢 낮음 (선택적)

#### 4. HWP 보고서 생성 (보류)
- 현재 Python에서 HWP 생성이 어려움
- 추후 검토

---

## 🔗 참고 문서

- `REPORT_TEMPLATE_PROMPT.md` - 보고서 템플릿 생성 프롬프트
- `scripts/test_report_templates.py` - 보고서 생성 테스트 코드
- `README.md` - 전체 시스템 문서
