# Vector Store 테스트 가이드

Qdrant 벡터 DB를 사용한 문서 저장 및 검색 테스트 방법입니다.

## 사전 준비

### 1. 환경 변수 설정

프로젝트 루트에 `.env` 파일 생성:

```
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

### 2. Qdrant 컨테이너 실행

```bash
cd ../aegis-infra
docker-compose up -d qdrant
```

컨테이너 상태 확인:
```bash
docker ps | grep qdrant
```

### 3. 패키지 설치

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 테스트 실행

### Step 1: 컬렉션 생성

```bash
cd aegis-ai-agent
python -m scripts.1_create_collection
```

생성되는 컬렉션:
- `manuals` - 대응 매뉴얼
- `past_events` - 과거 이벤트

### Step 2: 예시 문서 추가

```bash
python -m scripts.2_add_documents
```

옵션:
```bash
python -m scripts.2_add_documents --manuals   # 매뉴얼만
python -m scripts.2_add_documents --events    # 이벤트만
```

추가되는 데이터:
- 매뉴얼 4개 (폭행, 실신, 무단투기, 화재)
- 이벤트 5개 (ASSAULT, SWOON, DUMP, VANDALISM)

### Step 3: 검색 테스트

```bash
python -m scripts.3_search_test
```

테스트 내용:
1. 매뉴얼 자연어 검색
2. 과거 이벤트 자연어 검색
3. 필터 검색 (event_type=ASSAULT)

---

## Qdrant 대시보드

웹 브라우저에서 접속:
```
http://localhost:6333/dashboard
```

### Console 쿼리 예시

**컬렉션 목록 조회:**
```
GET /collections
```

**레코드 조회 (상위 10개):**
```json
POST /collections/manuals/points/scroll
{
  "limit": 10,
  "with_payload": true,
  "with_vector": false
}
```

**필터 검색 (ASSAULT만):**
```json
POST /collections/past_events/points/scroll
{
  "limit": 10,
  "filter": {
    "must": [
      { "key": "event_type", "match": { "value": "ASSAULT" } }
    ]
  },
  "with_payload": true,
  "with_vector": false
}
```

---

## VectorStoreClient 사용법

```python
from src.clients.vector_store_client import VectorStoreClient

client = VectorStoreClient()

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
    filters={"category": "emergency"},  # 선택사항
    min_score=0.3  # 선택사항
)

# 결과
for r in results:
    print(f"[{r['score']:.1%}] {r['data']}")
```

---

## 설정값

| 항목 | 값 |
|------|-----|
| Qdrant Host | `localhost` |
| Qdrant Port | `6333` |
| 임베딩 모델 | `text-embedding-3-small` |
| 벡터 차원 | `1536` |

---

## 파일 구조

```
scripts/
├── README.md              # 이 문서
├── __init__.py
├── 1_create_collection.py # 컬렉션 생성
├── 2_add_documents.py     # 문서 추가
└── 3_search_test.py       # 검색 테스트

src/clients/
└── vector_store_client.py # VectorStoreClient 클래스
```
