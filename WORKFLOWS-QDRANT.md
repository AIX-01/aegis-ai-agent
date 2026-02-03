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

## 부록: 참고 문서

- [Qdrant 공식 문서](https://qdrant.tech/documentation/)
- [Qdrant Python Client](https://github.com/qdrant/qdrant-client)
- [Sentence Transformers](https://www.sbert.net/)
- [paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)

