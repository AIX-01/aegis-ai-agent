import logging
from typing import List, Dict, Any, Optional
import uuid

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import VectorParams, Distance, PointStruct, Filter, FieldCondition, MatchValue
except ImportError:
    QdrantClient = None

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

from ..config import Config

logger = logging.getLogger(__name__)

# 임베딩 모델 전역 캐싱 (메모리 절약 및 로딩 시간 단축)
_embedding_model = None

def get_embedding_model(model_name: str):
    global _embedding_model
    if _embedding_model is None:
        if SentenceTransformer is None:
            raise ImportError("sentence-transformers library is not installed.")
        logger.info(f"Loading embedding model: {model_name}...")
        _embedding_model = SentenceTransformer(model_name)
        logger.info("Embedding model loaded.")
    return _embedding_model

class VectorStoreClient:
    """
    Qdrant Vector DB 클라이언트
    - SOP 매뉴얼 저장 및 검색
    - 과거 이벤트 요약 저장 및 검색
    """

    def __init__(self, config: Config):
        self.config = config
        self.url = config.qdrant_url
        self.api_key = config.qdrant_api_key
        self.model_name = config.embedding_model_name
        
        if QdrantClient is None:
            logger.warning("qdrant-client library is not installed. VectorStoreClient will be disabled.")
            self.client = None
            return

        try:
            self.client = QdrantClient(url=self.url, api_key=self.api_key)
            # 연결 테스트
            self.client.get_collections()
            logger.info(f"Connected to Qdrant at {self.url}")
            
            # 기본 컬렉션 생성 확인
            self._ensure_collection("manuals", vector_size=384) # MiniLM-L12-v2 차원수
            self._ensure_collection("past_events", vector_size=384)
            
        except Exception as e:
            logger.error(f"Failed to connect to Qdrant: {e}")
            self.client = None

    def _ensure_collection(self, collection_name: str, vector_size: int):
        """컬렉션이 없으면 생성합니다."""
        if not self.client:
            return

        try:
            collections = self.client.get_collections().collections
            exists = any(c.name == collection_name for c in collections)
            
            if not exists:
                logger.info(f"Creating collection '{collection_name}'...")
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE)
                )
        except Exception as e:
            logger.error(f"Error ensuring collection '{collection_name}': {e}")

    def _embed_text(self, text: str) -> List[float]:
        """텍스트를 벡터로 변환합니다."""
        try:
            model = get_embedding_model(self.model_name)
            return model.encode(text).tolist()
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return []

    def upsert_document(self, collection_name: str, doc_id: str, text: str, payload: Dict[str, Any]) -> bool:
        """
        문서 하나를 임베딩하여 저장합니다.
        
        Args:
            collection_name: 저장할 컬렉션 이름 ('manuals' or 'past_events')
            doc_id: 문서 ID (UUID 문자열 권장)
            text: 임베딩할 텍스트 (내용 요약 등)
            payload: 함께 저장할 메타데이터 (JSON)
        """
        if not self.client:
            return False

        try:
            vector = self._embed_text(text)
            if not vector:
                return False

            point = PointStruct(
                id=doc_id,
                vector=vector,
                payload={
                    "text": text, # 원본 텍스트도 페이로드에 저장
                    **payload
                }
            )
            
            self.client.upsert(
                collection_name=collection_name,
                points=[point]
            )
            logger.info(f"Upserted document {doc_id} to {collection_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to upsert document to {collection_name}: {e}")
            return False

    def search(self, collection_name: str, query_text: str, limit: int = 3, filter_category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        유사한 문서를 검색합니다.
        
        Args:
            collection_name: 검색할 컬렉션 이름
            query_text: 검색어 (질문 또는 상황 묘사)
            limit: 반환할 결과 개수
            filter_category: (선택) 특정 카테고리만 필터링 (payload에 'category' 필드가 있어야 함)
            
        Returns:
            검색 결과 리스트 (score, payload 포함)
        """
        if not self.client:
            return []

        try:
            query_vector = self._embed_text(query_text)
            if not query_vector:
                return []

            query_filter = None
            if filter_category:
                query_filter = Filter(
                    must=[
                        FieldCondition(
                            key="category",
                            match=MatchValue(value=filter_category)
                        )
                    ]
                )

            results = self.client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True
            )
            
            return [
                {
                    "id": str(hit.id),
                    "score": hit.score,
                    "payload": hit.payload
                }
                for hit in results
            ]
            
        except Exception as e:
            logger.error(f"Search failed in {collection_name}: {e}")
            return []
