# Qdrant 벡터 데이터베이스 워크플로우

> **작업일**: 2026-02-03  
> **목적**: aegis-ai-agent 내에서 Qdrant를 사용한 유사 사례 검색 기능 구현 및 테스트

---

## 목차

1. [Qdrant 개요](#1-qdrant-개요)
2. [아키텍처](#2-아키텍처)
3. [Docker Compose 설정](#3-docker-compose-설정)
4. [VectorStoreClient API](#4-vectorstoreclient-api)
5. [테스트 실행 과정](#5-테스트-실행-과정)
6. [테스트 결과](#6-테스트-결과)
7. [코드 변경사항](#7-코드-변경사항)
8. [Git 브랜치 관리](#8-git-브랜치-관리)
9. [향후 계획](#9-향후-계획)

---

## 1. Qdrant 개요

Qdrant는 벡터 검색 엔진으로, AEGIS 프로젝트에서 다음 용도로 사용됩니다:

| 컬렉션 | 용도 | 설명 |
|--------|------|------|
| `past_events` | 과거 이벤트 검색 | 유사 사건 조회로 대응 참고 |
| `manuals` | 대응 매뉴얼 검색 | RAG 기반 대응 지침 제공 |
| `frames` | 프레임 메타데이터 | VLM 분석 결과 저장 |

### 1.1 임베딩 모델

- **모델**: `paraphrase-multilingual-MiniLM-L12-v2`
- **차원**: 384
- **특징**: 다국어 지원 (한국어 포함)

---

## 2. 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                      aegis-ai-agent                              │
│                                                                  │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────┐  │
│  │  VLM 분석 결과   │───▶│ VectorStoreClient│───▶│   Qdrant    │  │
│  │  (이벤트 요약)   │    │ (임베딩 생성)    │    │  (6333 포트) │  │
│  └─────────────────┘    └─────────────────┘    └─────────────┘  │
│                                │                                 │
│                                ▼                                 │
│                      ┌─────────────────────┐                    │
│                      │ SentenceTransformer │                    │
│                      │ (다국어 임베딩 모델)  │                    │
│                      └─────────────────────┘                    │
└─────────────────────────────────────────────────────────────────┘
```

### 2.1 데이터 흐름

```
1. VLM이 CCTV 프레임 분석
        │
        ▼
2. 이벤트 요약 텍스트 생성
        │
        ▼
3. SentenceTransformer로 임베딩 변환 (384차원 벡터)
        │
        ▼
4. Qdrant에 벡터 + 메타데이터 저장
        │
        ▼
5. 유사 사례 검색 시 쿼리 임베딩 → 코사인 유사도 검색
```

---

## 3. Docker Compose 설정

**위치**: `aegis-ai-agent/docker-compose.yml`

```yaml
services:
  aegis-agent:
    build: .
    container_name: aegis-agent
    restart: unless-stopped
    ports:
      - "8001:8001"
    environment:
      - QDRANT_HOST=aegis-qdrant
      - QDRANT_PORT=6333
    depends_on:
      - qdrant
    networks:
      - aegis-agent-network

  qdrant:
    image: qdrant/qdrant:latest
    container_name: aegis-qdrant
    restart: unless-stopped
    ports:
      - "6333:6333"  # REST API
      - "6334:6334"  # gRPC
    volumes:
      - qdrant_data:/qdrant/storage
    environment:
      QDRANT__SERVICE__GRPC_PORT: 6334
    networks:
      - aegis-agent-network

volumes:
  qdrant_data:

networks:
  aegis-agent-network:
    name: aegis-agent-network
```

### 3.1 실행 명령어

```powershell
# Qdrant만 실행
cd aegis-ai-agent
docker-compose up qdrant -d

# 전체 서비스 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f qdrant
```

---

## 4. VectorStoreClient API

**파일 위치**: `src/clients/vector_store_client.py`

### 4.1 주요 메서드

| 메서드 | 설명 | 반환 |
|--------|------|------|
| `add_event(event_id, event_data)` | 이벤트 저장 | `bool` |
| `search_similar_events(query, limit, event_type, min_score)` | 유사 이벤트 검색 | `List[Dict]` |
| `add_manual(manual_id, manual_data)` | 매뉴얼 저장 | `bool` |
| `search_manuals(query, limit, category, min_score)` | 매뉴얼 검색 | `List[Dict]` |
| `add_frame_metadata(...)` | 프레임 메타데이터 저장 | `bool` |
| `search_frames(query, limit, camera_id)` | 프레임 검색 | `List[Dict]` |
| `get_stats()` | 컬렉션 통계 조회 | `Dict` |
| `health_check()` | 연결 상태 확인 | `bool` |

### 4.2 사용 예시

```python
from src.clients.vector_store_client import VectorStoreClient

# 클라이언트 초기화 (싱글톤)
client = VectorStoreClient(host="localhost", port=6333)

# 이벤트 저장
client.add_event("EVT-001", {
    "summary": "주차장에서 두 남성이 격렬하게 다툼",
    "event_type": "ASSAULT",
    "location": "주차장 B구역",
    "resolution": "경비원 출동"
})

# 유사 이벤트 검색
results = client.search_similar_events(
    query="두 사람이 싸우고 있다",
    limit=5,
    event_type="ASSAULT",  # 선택적 필터
    min_score=0.5
)

for result in results:
    print(f"[{result['score']:.2%}] {result['data']['summary']}")
```

---

## 5. 테스트 실행 과정

### 5.1 1단계: Qdrant 컨테이너 실행

```powershell
cd aegis-ai-agent
docker-compose up qdrant -d
```

### 5.2 2단계: 헬스체크

```powershell
# PowerShell
Invoke-RestMethod -Uri "http://localhost:6333" -Method GET

# 결과
# title                         version commit
# -----                         ------- ------
# qdrant - vector search engine 1.16.3  bd49f45a...
```

### 5.3 3단계: 필요 패키지 설치

```powershell
pip install qdrant-client sentence-transformers
```

### 5.4 4단계: 테스트 스크립트 실행

```powershell
cd aegis-ai-agent
python -m scripts.test_qdrant_search
```

---

## 6. 테스트 결과

### 6.1 샘플 이벤트 데이터 (5건)

| 이벤트 ID | 요약 | 유형 | 위치 |
|-----------|------|------|------|
| EVT-2026-001 | 두 남성이 격렬하게 다투다가 밀침 | ASSAULT | 주차장 B구역 |
| EVT-2026-002 | 노인 한 명이 갑자기 쓰러짐 | SWOON | 1층 로비 |
| EVT-2026-003 | 대형 가구를 무단으로 투기 | DUMP | 지하 1층 쓰레기장 |
| EVT-2026-004 | 두 여성 언쟁 후 폭행 | ASSAULT | 3층 복도 |
| EVT-2026-005 | 차량 유리창이 깨진 채 발견 | VANDALISM | 지하 주차장 C구역 |

### 6.2 유사 사례 검색 결과

| 쿼리 | Top 1 결과 | 유사도 | 이벤트 유형 |
|------|-----------|--------|------------|
| "두 사람이 싸우고 있다" | 두 여성 언쟁 후 폭행 | 68.26% | ASSAULT |
| "사람이 쓰러져 있다" | 노인 한 명 갑자기 쓰러짐 | **79.97%** | SWOON |
| "쓰레기를 버리고 있다" | 대형 가구 무단 투기 | 43.89% | DUMP |
| "차량에 손상이 발생했다" | 차량 유리창 깨짐 | 54.40% | VANDALISM |

### 6.3 이벤트 타입 필터 검색 (ASSAULT만)

| 순위 | 유사도 | 이벤트 |
|------|--------|--------|
| 1 | 56.09% | 두 남성 격렬하게 다툼 |
| 2 | 51.17% | 두 여성 언쟁 후 폭행 |

### 6.4 Qdrant 컬렉션 통계

```
📊 현재 Qdrant 통계:
  - past_events: 5개 포인트
  - manuals: 0개 포인트
  - frames: 0개 포인트
```

---

## 7. 코드 변경사항

### 7.1 Qdrant 클라이언트 API 업데이트 (v1.16.x)

최신 qdrant-client 버전에서 `search` 메서드가 `query_points`로 변경되었습니다.

**이전 (deprecated)**:
```python
results = self.client.search(
    collection_name="past_events",
    query_vector=query_vector.tolist(),
    limit=limit
)
for result in results:
    # result.payload, result.score
```

**현재 (v1.16.x)**:
```python
results = self.client.query_points(
    collection_name="past_events",
    query=query_vector.tolist(),
    limit=limit
)
for result in results.points:
    # result.payload, result.score
```

### 7.2 수정된 파일

- `src/clients/vector_store_client.py`
  - `search_similar_events()`: `search` → `query_points`
  - `search_manuals()`: `search` → `query_points`
  - `search_frames()`: `search` → `query_points`
  - `get_stats()`: `vectors_count` 속성 제거

---

## 8. Git 브랜치 관리

```
feat/Qdrant ← 작업 브랜치 (현재)
     ↑
    dev ← 베이스 브랜치
     ↑
   main
```

### 8.1 변경된 파일 (12개)

| 파일 | 상태 | 설명 |
|------|------|------|
| `.dockerignore` | 신규 | Docker 빌드 제외 파일 |
| `.env.example` | 신규 | 환경변수 예시 |
| `Dockerfile` | 신규 | Agent 컨테이너 빌드 |
| `docker-compose.yml` | 신규 | Qdrant + Agent 서비스 정의 |
| `scripts/__init__.py` | 신규 | 패키지 초기화 |
| `scripts/init_qdrant_data.py` | 신규 | 매뉴얼 초기 데이터 스크립트 |
| `scripts/test_qdrant_search.py` | 신규 | 유사 검색 테스트 스크립트 |
| `requirements.txt` | 수정 | qdrant-client 추가 |
| `src/clients/vector_store_client.py` | 수정 | API 업데이트 |
| `src/config.py` | 수정 | Qdrant 설정 추가 |
| `src/graph/nodes/generate_report.py` | 수정 | 유사 사례 검색 연동 |
| `WORKFLOWS-QDRANT.md` | 신규 | 본 문서 |

### 8.2 커밋 명령어

```powershell
cd aegis-ai-agent
git add -A
git commit -m "feat: Qdrant 벡터 데이터베이스 통합

- Docker Compose에 Qdrant 서비스 추가
- VectorStoreClient 구현 (유사 이벤트/매뉴얼 검색)
- Qdrant 초기화 및 테스트 스크립트 추가
- qdrant-client v1.16.x API 적용"
```

---

## 9. 향후 계획

| 항목 | 설명 | 우선순위 |
|------|------|----------|
| 매뉴얼 데이터 초기화 | `python -m scripts.init_qdrant_data` 실행 | 높음 |
| 프레임 메타데이터 연동 | VLM 분석 결과 자동 저장 | 중간 |
| RAG 파이프라인 구축 | 매뉴얼 검색 → LLM 응답 생성 | 중간 |
| 임베딩 모델 최적화 | 한국어 특화 모델 검토 | 낮음 |
| 벡터 인덱스 튜닝 | HNSW 파라미터 최적화 | 낮음 |

---

## 10. 실제 운영 시 수정 사항

### 10.1 테스트용 하드코딩 제거

현재 테스트 스크립트에서는 샘플 데이터를 하드코딩으로 저장하고 있습니다. 실제 운영 시에는 다음과 같이 변경해야 합니다:

#### 현재 (테스트용)
```python
# scripts/test_qdrant_search.py
sample_events = [
    {
        "event_id": "EVT-2026-001",
        "summary": "주차장에서 두 남성이 격렬하게 다툼",
        "event_type": "ASSAULT"
    },
    # ... 하드코딩된 샘플 데이터
]

for event in sample_events:
    client.add_event(event["event_id"], event)
```

#### 실제 운영 시
```python
# src/graph/nodes/generate_report.py
def save_event_to_vector_store(state):
    """VLM 분석 결과를 자동으로 Qdrant에 저장"""
    from src.clients.vector_store_client import VectorStoreClient
    
    vector_client = VectorStoreClient()
    
    event_data = {
        "summary": state["vlm_summary"],
        "event_type": state["event_type"],
        "location": state["camera_location"],
        "timestamp": state["timestamp"],
        "resolution": state.get("resolution", ""),
        "confidence": state.get("confidence", 0.0)
    }
    
    vector_client.add_event(
        event_id=state["event_id"],
        event_data=event_data
    )
```

### 10.2 환경변수 설정

#### 개발 환경 (.env.example)
```env
QDRANT_HOST=localhost
QDRANT_PORT=6333
EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2
```

#### 프로덕션 환경 (.env.production)
```env
QDRANT_HOST=aegis-qdrant
QDRANT_PORT=6333
EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2
QDRANT_API_KEY=your-production-api-key  # Qdrant Cloud 사용 시
```

### 10.3 데이터 마이그레이션

기존 PostgreSQL에 저장된 과거 이벤트 데이터를 Qdrant로 마이그레이션:

```python
# scripts/migrate_past_events.py
"""
PostgreSQL → Qdrant 데이터 마이그레이션 스크립트
"""
import psycopg2
from src.clients.vector_store_client import VectorStoreClient

def migrate_events():
    # PostgreSQL 연결
    conn = psycopg2.connect(
        host="localhost",
        database="aegis",
        user="aegis",
        password="trillion"
    )
    cursor = conn.cursor()
    
    # Qdrant 클라이언트
    vector_client = VectorStoreClient()
    
    # 과거 이벤트 조회 (최근 6개월)
    cursor.execute("""
        SELECT id, summary, type, location, created_at, resolution
        FROM events
        WHERE created_at >= NOW() - INTERVAL '6 months'
    """)
    
    migrated_count = 0
    for row in cursor.fetchall():
        event_id, summary, event_type, location, timestamp, resolution = row
        
        success = vector_client.add_event(str(event_id), {
            "summary": summary or "",
            "event_type": event_type or "UNKNOWN",
            "location": location or "",
            "timestamp": str(timestamp),
            "resolution": resolution or ""
        })
        
        if success:
            migrated_count += 1
    
    print(f"✅ {migrated_count}건의 이벤트 마이그레이션 완료")
    cursor.close()
    conn.close()

if __name__ == "__main__":
    migrate_events()
```

### 10.4 매뉴얼 데이터 초기화

현재 `manuals` 컬렉션이 비어있으므로, 대응 매뉴얼 초기 데이터를 추가:

```powershell
cd aegis-ai-agent
python -m scripts.init_qdrant_data
```

### 10.5 자동 백업 설정

Qdrant 데이터 정기 백업 스크립트 (cron으로 매일 실행):

```python
# scripts/backup_qdrant.py
"""Qdrant 스냅샷 백업"""
import os
from datetime import datetime
from qdrant_client import QdrantClient

def backup_qdrant():
    client = QdrantClient(host="localhost", port=6333)
    backup_dir = f"/backups/qdrant_{datetime.now():%Y%m%d}"
    
    os.makedirs(backup_dir, exist_ok=True)
    
    for collection_name in ["past_events", "manuals", "frames"]:
        client.create_snapshot(collection_name)
        print(f"✅ {collection_name} 스냅샷 생성 완료")

if __name__ == "__main__":
    backup_qdrant()
```

### 10.6 모니터링 및 알림

Qdrant 상태 모니터링:

```python
# src/utils/monitoring.py
def check_qdrant_health():
    """Qdrant 헬스체크 및 알림"""
    from src.clients.vector_store_client import VectorStoreClient
    
    client = VectorStoreClient()
    
    if not client.health_check():
        # 슬랙/이메일 알림 전송
        send_alert("❌ Qdrant 연결 실패!")
        return False
    
    stats = client.get_stats()
    
    # 데이터 증가 모니터링
    if stats["past_events"]["points_count"] > 100000:
        send_alert("⚠️ Qdrant past_events 컬렉션 10만건 초과")
    
    return True
```

### 10.7 임베딩 모델 최적화

한국어 특화 모델로 변경 검토:

| 모델 | 차원 | 특징 |
|------|------|------|
| `paraphrase-multilingual-MiniLM-L12-v2` (현재) | 384 | 다국어, 경량 |
| `xlm-r-100langs-bert-base-nli-stsb-mean-tokens` | 768 | 다국어, 고성능 |
| `jhgan/ko-sroberta-multitask` | 768 | 한국어 특화 |

```python
# src/clients/vector_store_client.py 수정
class VectorStoreClient:
    def __init__(self, embedding_model="jhgan/ko-sroberta-multitask"):
        self.encoder = SentenceTransformer(embedding_model)
        # ... 기존 코드
```

### 10.8 인덱스 튜닝

대용량 데이터 처리를 위한 HNSW 파라미터 조정:

```python
# src/clients/vector_store_client.py
from qdrant_client.models import VectorParams, Distance, HnswConfigDiff

self.client.create_collection(
    collection_name="past_events",
    vectors_config=VectorParams(
        size=self.vector_size,
        distance=Distance.COSINE,
        hnsw_config=HnswConfigDiff(
            m=16,              # 연결 수 (기본: 16, 높을수록 정확하지만 느림)
            ef_construct=100,  # 인덱스 구축 시 탐색 깊이 (기본: 100)
        )
    )
)
```

### 10.9 API 엔드포인트 추가

프론트엔드에서 유사 사례를 조회할 수 있도록 API 추가:

```python
# src/api/api_server.py
from fastapi import FastAPI, Query
from src.clients.vector_store_client import VectorStoreClient

app = FastAPI()
vector_client = VectorStoreClient()

@app.get("/api/similar-events")
async def get_similar_events(
    query: str = Query(..., description="검색 쿼리"),
    limit: int = Query(5, ge=1, le=20),
    event_type: str = Query(None, description="이벤트 타입 필터")
):
    """유사 사례 검색 API"""
    results = vector_client.search_similar_events(
        query=query,
        limit=limit,
        event_type=event_type,
        min_score=0.3
    )
    return {"results": results}

@app.get("/api/manuals/search")
async def search_manuals(
    query: str = Query(..., description="검색 쿼리"),
    limit: int = Query(3, ge=1, le=10)
):
    """대응 매뉴얼 검색 API"""
    results = vector_client.search_manuals(
        query=query,
        limit=limit,
        min_score=0.5
    )
    return {"results": results}
```

### 10.10 보안 설정

#### Qdrant API Key 설정 (프로덕션)
```yaml
# docker-compose.yml
services:
  qdrant:
    image: qdrant/qdrant:latest
    environment:
      QDRANT__SERVICE__API_KEY: ${QDRANT_API_KEY}
```

#### 클라이언트 API Key 사용
```python
# src/clients/vector_store_client.py
import os

class VectorStoreClient:
    def __init__(self, api_key=None):
        self.client = QdrantClient(
            host=self.host,
            port=self.port,
            api_key=api_key or os.getenv("QDRANT_API_KEY")
        )
```

---

## 부록: 참고 문서

- [Qdrant 공식 문서](https://qdrant.tech/documentation/)
- [Qdrant Python Client](https://github.com/qdrant/qdrant-client)
- [Sentence Transformers](https://www.sbert.net/)
- [paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)

