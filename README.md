# AEGIS AI Agent

> Agent 기반 안전 모니터링 시스템 - AI 분석 에이전트

## 개요

AEGIS AI Agent는 RTSP 스트림에서 프레임을 추출하고, LangGraph 기반 분석 파이프라인을 통해 이상행동을 감지하는 Python 애플리케이션입니다.

## 기술 스택

| 분류 | 기술 |
|------|------|
| Language | Python 3.13 |
| Framework | LangGraph 1.0, LangChain Core 1.2 |
| API | FastAPI, Uvicorn |
| 영상처리 | OpenCV (opencv-python) |
| 캐시 | Redis |
| HTTP | httpx, requests |

## 프로젝트 구조

```
src/
├── __init__.py
├── app.py                  # 메인 오케스트레이터 (AegisAgent)
├── config.py               # 설정 (Config 데이터클래스)
├── utils.py                # 유틸리티 (로깅, 시그널 핸들러)
├── api/
│   ├── __init__.py
│   ├── api_server.py       # FastAPI 서버
│   └── mock_server.py      # Mock 서버 (VLM, Precision, Backend)
├── clients/
│   ├── __init__.py
│   ├── vlm_client.py       # VLM API 클라이언트
│   ├── precision_client.py # Precision LLM 클라이언트
│   ├── backend_client.py   # Backend API 클라이언트
│   └── vector_store_client.py # Vector Store 클라이언트
├── core/
│   ├── __init__.py
│   ├── producer.py         # 프레임 프로듀서 (RTSP → 프레임)
│   ├── consumer.py         # 컨슈머 풀 (LangGraph 실행)
│   ├── queue_manager.py    # 프레임 큐 관리
│   ├── windowing.py        # 윈도우 매니저
│   └── redis_manager.py    # Redis 연동 (카메라 목록 동기화)
├── graph/
│   ├── __init__.py
│   ├── analysis_graph.py   # LangGraph 워크플로우 빌드
│   ├── state.py            # 분석 상태 정의 (AnalysisState)
│   ├── nodes/              # 그래프 노드들
│   │   ├── __init__.py
│   │   ├── vlm_analysis.py
│   │   ├── backend_report.py
│   │   ├── verification.py
│   │   ├── precision_analysis.py
│   │   ├── update_backend.py
│   │   ├── action.py
│   │   └── generate_report.py
│   └── edges/              # 그래프 엣지 (라우터)
│       ├── __init__.py
│       └── routers.py
├── retrieval/              # RAG 관련 (작업 중)
│   ├── __init__.py
│   ├── indexer.py          # 문서 인덱싱
│   └── retriever_factory.py
└── tools/                  # LangChain 도구 (작업 중)
    ├── __init__.py
    └── search_tools.py     # 매뉴얼/사례 검색
```

## 설치 및 실행

```bash
# 가상환경 생성
python -m venv .venv
source .venv/bin/activate

# 의존성 설치
pip install -r requirements.txt

# 실행
python -m src.app

# Mock 모드로 실행 (기본값)
python -m src.app --mock
```

## 설정 (config.py)

### 모드 설정

```python
mock_mode: bool = True  # True: Mock 서버, False: 실제 서버
```

### 실제 서버 주소

```python
_real_vlm_endpoint: str = "http://<VLM 서버>:8001/analyze"
_real_precision_endpoint: str = "http://<LLM 서버>:8002/precision_analyze"
_real_backend_endpoint: str = "http://<백엔드>:8080/api/vlm-results"
```

> **주의**: 현재 `backend_client.py`는 Mock 서버용 API를 사용합니다.  
> 실제 Backend API와 연동하려면 다음 수정이 필요합니다:
> - 경로: `/api/vlm-results` → `/internal/agent/events`
> - 이벤트 업데이트: `PUT` → `PATCH /internal/agent/events/{id}/analysis`
> - 필드명: `camera_id` → `cameraId`, `occurred_at` → `occurredAt`

### Mock 서버 포트

| 서버 | 포트 |
|------|------|
| VLM | 8001 |
| Precision LLM | 8002 |
| Backend | 8088 |

### RTSP 설정

| 설정 | 기본값 | 설명 |
|------|--------|------|
| `rtsp_host` | `127.0.0.1` | MediaMTX 호스트 |
| `rtsp_port` | `8554` | RTSP 포트 |
| `frame_width` | `640` | 프레임 너비 |
| `frame_height` | `360` | 프레임 높이 |
| `jpeg_quality` | `60` | JPEG 품질 |
| `fps` | `1` | 초당 프레임 수 |

### 분석 파이프라인 설정

| 설정 | 기본값 | 설명 |
|------|--------|------|
| `num_workers` | `4` | 컨슈머 워커 수 |
| `window_size` | `8` | 윈도우 프레임 수 |
| `window_slide` | `4` | 슬라이드 프레임 수 |
| `flush_timeout` | `30` | 플러시 타임아웃 (초) |
| `min_flush_size` | `5` | 최소 플러시 크기 |
| `queue_max_size` | `20` | 큐 최대 크기 |

### 네트워크 설정

| 설정 | 기본값 | 설명 |
|------|--------|------|
| `vlm_timeout` | `30` | VLM 타임아웃 (초) |
| `vlm_max_retries` | `3` | VLM 재시도 횟수 |
| `precision_timeout` | `60` | Precision 타임아웃 (초) |
| `backend_timeout` | `10` | Backend 타임아웃 (초) |
| `reconnect_delay` | `2.0` | 재연결 지연 (초) |
| `max_reconnect_delay` | `60.0` | 최대 재연결 지연 (초) |

### Redis 설정

| 설정 | 기본값 | 설명 |
|------|--------|------|
| `redis_host` | `localhost` | Redis 호스트 |
| `redis_port` | `6379` | Redis 포트 |
| `redis_db` | `0` | Redis DB 번호 |
| `redis_analysis_cameras_key` | `analysis:cameras` | 카메라 목록 키 |
| `redis_update_channel` | `camera:analysis:update` | 업데이트 채널 |

## 아키텍처

### 전체 흐름

```
1. Redis에서 분석 대상 카메라 목록 구독
2. FrameProducer: RTSP 스트림 → 프레임 추출
3. WindowManager: 프레임 윈도잉 (8프레임/윈도우)
4. QueueManager: 분석 큐에 윈도우 추가
5. ConsumerPool: LangGraph 파이프라인 실행
6. BackendClient: 결과를 Backend API로 전송
```

### LangGraph 분석 파이프라인

```
vlm_analysis
    │
    ▼
backend_report
    │
    ▼
analysis_router ─────────────────┐
    │                            │
    ├─ risk=NORMAL ─────────────▶ END
    │
    ├─ risk=SUSPICIOUS ──────────▶ verification
    │                                   │
    │                            verification_router
    │                                   │
    │                        ┌──────────┴──────────┐
    │                        ▼                     ▼
    │                  precision_analysis         END
    │                        │
    │                        ▼
    └─ risk=ABNORMAL ───────▶ precision_analysis
                                   │
                                   ▼
                             update_backend
                                   │
                                   ▼
                                action
                                   │
                                   ▼
                            generate_report
                                   │
                                   ▼
                                  END
```

## 그래프 노드

### vlm_analysis

- VLM 서버에 프레임 전송
- 1차 분류 결과 수신 (NORMAL/SUSPICIOUS/ABNORMAL)

### backend_report

- Backend API에 이벤트 생성 요청
- `event_id` 반환받아 상태에 저장

### verification

- SUSPICIOUS 판정에 대한 검증
- 추가 분석 필요 여부 결정

### precision_analysis

- Precision LLM 서버에 정밀 분석 요청
- 이벤트 유형, 요약, 위험 점수 등 상세 결과

### update_backend

- 정밀 분석 결과를 Backend API에 업데이트

### action

- 권장 조치 생성 (작업 중)

### generate_report

- 상세 보고서 생성 (작업 중)

## 그래프 상태 (state.py)

```python
class AnalysisState(TypedDict):
    # 초기 입력
    camera_id: str
    camera_name: str
    camera_location: str
    occurred_at: datetime
    frames: List[bytes]
    
    # 워크플로우 중 생성
    event_id: str
    vlm_result: Dict[str, Any]
    precision_result: Dict[str, Any]
    
    # 최종 분석 결과
    risk_level: RiskLevel      # NORMAL, SUSPICIOUS, ABNORMAL
    event_type: EventType      # ASSAULT, BURGLARY, DUMP, SWOON, VANDALISM, UNKNOWN
    summary: str
    risk_score: float
    report: str
    
    # 메타 데이터
    actions: list
    rag_references: list
    errors: List[str]
```

## 외부 클라이언트

### VLMClient

- 엔드포인트: `/analyze`
- 입력: base64 인코딩된 프레임 배열
- 출력: `{ primary_category, secondary_category, confidence, description }`

### PrecisionClient

- 엔드포인트: `/precision_analyze`
- 입력: 프레임 + VLM 결과
- 출력: `{ risk, event_type, summary, risk_score }`

### BackendClient

- 이벤트 생성: `POST /internal/agent/events`
- 분석 결과 업데이트: `PATCH /internal/agent/events/{id}/analysis`

> **주의**: 위 경로는 Backend API 스펙입니다. 현재 `backend_client.py`는 Mock 서버용 `/api/vlm-results` 경로를 사용하므로, 실제 Backend 연동 시 코드 수정이 필요합니다. (상단 "실제 서버 주소" 섹션 참조)

## Redis 연동

### 카메라 목록 동기화

- 키: `analysis:cameras`
- 형식: `[{ id, name, location }, ...]`
- Backend에서 카메라 분석 설정 변경 시 업데이트

### Pub/Sub 구독

- 채널: `camera:analysis:update`
- 메시지 수신 시 카메라 목록 다시 로드
- 프로듀서 동적 추가/제거

## Mock 서버

개발/테스트용 Mock 서버 제공:

```python
# mock_server.py
MockVLMServer      # 포트 8001
MockPrecisionServer # 포트 8002
MockBackendServer   # 포트 8088
```

Mock 서버는 랜덤한 분석 결과를 반환합니다.

## 유틸리티 (utils.py)

### setup_logging

```python
logger = setup_logging("INFO")
```

### setup_signal_handlers

```python
setup_signal_handlers(shutdown_callback)
# SIGINT, SIGTERM 수신 시 graceful shutdown
```

### exponential_backoff

```python
delay = exponential_backoff(attempt=3, base_delay=1.0, max_delay=60.0)
```

## 작업 중 기능

### retrieval/

- `indexer.py`: 대응 매뉴얼 문서 인덱싱
- `retriever_factory.py`: 리트리버 팩토리

### tools/

- `search_tools.py`: 매뉴얼 검색, 유사 사례 검색

## 빌드 및 배포

### 실행

```bash
# Mock 모드
python -m src.app --mock

# 실제 모드
python -m src.app
```

### Docker

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY src/ ./src/
CMD ["python", "-m", "src.app"]
```
