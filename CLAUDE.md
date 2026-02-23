# AEGIS AI Agent - Development Guide

이 문서는 AEGIS AI Agent 프로젝트의 구조와 개발 규칙을 설명합니다.
팀원 및 코딩 에이전트(Claude Code 등)가 새로운 기능을 구현할 때 참고하세요.

## 프로젝트 구조

```
src/
├── clients/                 # API 클라이언트 모듈
│   ├── __init__.py         # 클라이언트 export (새 클라이언트 추가 시 여기에 등록)
│   ├── openai_client.py    # OpenAI API 중앙 관리 (get_embedding, get_chat_completion, get_vision_completion)
│   ├── vlm_client.py       # VLM 1차 분석 클라이언트
│   ├── precision_client.py # 정밀 분석 클라이언트 (OpenAI Chat API)
│   ├── verification_client.py # SUSPICIOUS 검증 클라이언트 (OpenAI Vision API)
│   ├── backend_client.py   # 백엔드 API 클라이언트
│   └── vector_store_client.py # Qdrant 벡터 DB 클라이언트
├── graph/                   # LangGraph 워크플로우
│   ├── state.py            # AnalysisState 정의 (새 필드 추가 시 여기에 등록)
│   ├── analysis_graph.py   # 그래프 빌더 (클라이언트 바인딩)
│   ├── nodes/              # 노드 구현
│   │   ├── __init__.py     # 노드 export
│   │   ├── verification.py
│   │   ├── precision_analysis.py
│   │   ├── action.py
│   │   ├── update_backend.py
│   │   └── generate_report.py
│   └── edges/              # 라우터 (분기 로직)
│       └── routers.py
├── config.py               # 모든 설정 값 (엔드포인트, 프롬프트, 타임아웃 등)
└── utils.py                # 유틸리티 함수 (수정 금지)
```

## 새로운 노드 구현 가이드

### 1. 클라이언트 작성 (`src/clients/`)

외부 API를 호출하는 노드는 반드시 클라이언트를 분리합니다.

```python
# src/clients/my_client.py
import logging
from typing import Dict, Any, Optional

from .openai_client import get_vision_completion  # OpenAI 호출은 여기서 import
from ..utils import exponential_backoff

class MyClient:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger("aegis-agent.my_client")

        # config에서 설정 로드
        self.api_key = config.openai_api_key
        self.model = config.openai_chat_model
        self.timeout = config.openai_chat_timeout
        self.max_retries = config.my_max_retries  # config.py에 추가 필요
        self.system_prompt = config.my_system_prompt  # config.py에 추가 필요

    def process(self, camera_id: str, frames: list, ...) -> Optional[Dict[str, Any]]:
        # 구현
        pass
```

**중요**: 클라이언트 작성 후 `src/clients/__init__.py`에 export 추가:
```python
from .my_client import MyClient
```

### 2. 설정 추가 (`src/config.py`)

모든 하드코딩 값은 `config.py`의 `Config` 클래스에 추가합니다.

```python
@dataclass
class Config:
    # ... 기존 설정 ...

    # =========================================
    # My Feature 설정
    # =========================================
    my_system_prompt: str = """당신은 ...

## 출력 형식 (JSON만 출력)
{
  "field1": "...",
  "field2": 0.0
}

JSON만 출력하세요."""

    my_max_retries: int = 3
    my_retry_delay: float = 1.0
    my_timeout: int = 60
```

### 3. 노드 작성 (`src/graph/nodes/`)

```python
# src/graph/nodes/my_node.py
import logging
from typing import Dict, Any

from ..state import AnalysisState
from ...clients.my_client import MyClient

logger = logging.getLogger(__name__)

def my_node(state: AnalysisState, my_client: MyClient) -> Dict[str, Any]:
    """
    노드 설명

    Args:
        state: 현재 분석 상태
        my_client: 클라이언트 인스턴스

    Returns:
        업데이트된 상태 딕셔너리
    """
    camera_id = state["camera_id"]
    frames = state["frames"]

    try:
        result = my_client.process(camera_id, frames, ...)

        if result:
            return {
                "my_result": result,
                "some_field": result.get("field1")
            }
        else:
            return {"errors": state.get("errors", []) + ["My process failed"]}

    except Exception as e:
        logger.error(f"[{camera_id}] 오류: {e}", exc_info=True)
        return {"errors": state.get("errors", []) + [f"Exception: {e}"]}
```

**중요**: 노드 작성 후 `src/graph/nodes/__init__.py`에 export 추가:
```python
from .my_node import my_node
```

### 4. 상태 필드 추가 (`src/graph/state.py`)

노드가 새로운 데이터를 저장하면 `AnalysisState`에 필드 추가:

```python
class AnalysisState(TypedDict):
    # ... 기존 필드 ...
    my_result: Dict[str, Any]  # 새 필드 추가
```

### 5. 그래프에 노드 등록 (`src/graph/analysis_graph.py`)

```python
from ..clients import MyClient

def build_graph(config: Config):
    # 클라이언트 초기화
    my_client = MyClient(config)

    # 노드에 클라이언트 바인딩
    my_node_bound = functools.partial(my_node, my_client=my_client)

    # 노드 추가
    workflow.add_node("my_node", my_node_bound)

    # 엣지 추가
    workflow.add_edge("previous_node", "my_node")
```

## OpenAI API 사용 규칙

모든 OpenAI API 호출은 `src/clients/openai_client.py`를 통해 수행합니다.

```python
from .openai_client import get_embedding, get_chat_completion, get_vision_completion

# 텍스트 임베딩
embedding = get_embedding(text="...", api_key=self.api_key, model="text-embedding-3-small")

# 텍스트 채팅
response = get_chat_completion(messages=[...], api_key=self.api_key, model="gpt-4.1-mini", timeout=60)

# 이미지 분석 (Vision)
response = get_vision_completion(
    prompt="...",
    images_base64=["base64_encoded_image", ...],
    api_key=self.api_key,
    model="gpt-4.1-mini",
    timeout=60
)
```

## RAG 노드 구현 가이드

RAG(Retrieval-Augmented Generation) 관련 노드 구현 시 `VectorStoreClient`를 사용합니다.

### VectorStoreClient 사용법

```python
from src.config import Config
from src.clients.vector_store_client import VectorStoreClient

# 초기화 (싱글톤, config 필수)
config = Config()
client = VectorStoreClient(config)

# 컬렉션 생성
client.create_collection("my_collection")

# 문서 추가
client.add_document(
    collection_name="my_collection",
    doc_id="doc_001",
    data={"title": "제목", "content": "내용"},
    text_field="content"  # 임베딩할 필드
)

# 검색
results = client.search(
    collection_name="my_collection",
    query="검색어",
    limit=5,
    filters={"category": "emergency"},  # 선택적 필터
    min_score=0.3
)
# 반환: [{"id": "doc_001", "score": 0.85, "data": {...}}, ...]
```

### 사용 예시 참고

`scripts/` 폴더의 테스트 파일들을 참고하세요:

| 파일 | 설명 |
|------|------|
| `scripts/1_create_collection.py` | 컬렉션 생성 예시 |
| `scripts/2_add_documents.py` | 문서 추가 예시 (매뉴얼, 과거 이벤트) |
| `scripts/3_search_test.py` | 검색 및 필터 사용 예시 |

### 기존 컬렉션

| 컬렉션명 | 용도 | 임베딩 필드 |
|---------|------|------------|
| `manuals` | 대응 매뉴얼 | `content` |
| `past_events` | 과거 이벤트 기록 | `summary` |

## 주의사항

1**하드코딩 금지**: 모든 설정값은 `config.py`에 정의합니다.
2**클라이언트 분리**: API 호출 로직은 반드시 `clients/`에 분리합니다.
3**Export 등록**: 새 모듈 작성 시 `__init__.py`에 export를 추가합니다.
4**상태 필드**: 노드가 반환하는 새 데이터는 `state.py`에 필드를 추가합니다.(langgraph에서 subgraph를 사용한다고 하면 개발자 의도가 우선)
5**에러 처리**: 실패 시 `errors` 리스트에 메시지를 추가하고, 안전 방향으로 처리합니다.

## 환경 변수 (.env)

```
OPENAI_API_KEY=sk-...
```

## 참고 파일

- 클라이언트 예시: `src/clients/precision_client.py`, `src/clients/verification_client.py`
- 노드 예시: `src/graph/nodes/precision_analysis.py`, `src/graph/nodes/verification.py`
- 설정 예시: `src/config.py` (프롬프트 섹션 참고)

## 워크플로우 흐름

```
[Consumer에서 VLM 분석 완료]
         │
         ▼
┌─────────────────────────────────────┐
│  Analysis Router (Entry Point)      │
│  - NORMAL → END                     │
│  - SUSPICIOUS → Verification        │
│  - ABNORMAL → Precision Analysis    │
└─────────────────────────────────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐  ┌──────────────────┐
│Verifi- │  │Precision Analysis│
│cation  │  │(LLM 정밀 분석)    │
└────────┘  └──────────────────┘
    │              │
    │ ABNORMAL     │
    └──────┬───────┘
           ▼
  (이후 자유롭게 추가/수정)
    ┌──────────────┐
    │Update Backend│
    └──────────────┘
           │
           ▼
    ┌──────────────┐
    │   Action     │
    └──────────────┘
           │
           ▼
    ┌──────────────┐
    │Generate Report│
    └──────────────┘
           │
           ▼
         [END]
```

## Risk Level 정의

| Level | 설명 | 다음 단계 |
|-------|------|----------|
| NORMAL | 정상 상황 | 종료 |
| SUSPICIOUS | 의심 상황 (확인 필요) | Verification → ABNORMAL 또는 SUSPICIOUS 유지 |
| ABNORMAL | 이상 상황 (조치 필요) | Precision Analysis → 백엔드 갱신 |
