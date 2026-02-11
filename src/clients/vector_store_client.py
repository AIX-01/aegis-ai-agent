"""
Qdrant Vector Store 클라이언트 (Skeleton)

팀원들이 컬렉션 정의 및 도메인 로직을 직접 구현할 수 있도록
범용 메서드만 제공하는 최소 버전입니다.

사용 예시:
    from src.config import Config
    from src.clients.vector_store_client import VectorStoreClient

    config = Config()
    client = VectorStoreClient(config)

    # 컬렉션 생성
    client.create_collection("my_collection")

    # 문서 추가
    client.add_document(
        collection_name="my_collection",
        doc_id="doc_001",
        data={"title": "제목", "content": "내용"},
        text_field="content"
    )

    # 검색
    results = client.search(
        collection_name="my_collection",
        query="검색어",
        limit=5
    )
"""
import logging
import hashlib
from typing import List, Dict, Any, Optional, TYPE_CHECKING

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    FilterSelector,
)

from .openai_client import get_embedding

if TYPE_CHECKING:
    from ..config import Config

logger = logging.getLogger(__name__)


class VectorStoreClient:
    """Qdrant 벡터 스토어 클라이언트 (Skeleton)"""

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        """싱글톤 패턴"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: "Config"):
        """
        Qdrant 클라이언트 초기화

        Args:
            config: Config 인스턴스
        """
        if VectorStoreClient._initialized:
            return

        try:
            self.qdrant_host = config.qdrant_host
            self.qdrant_port = config.qdrant_port
            self.qdrant_timeout = config.qdrant_timeout
            self.embedding_model = config.openai_embedding_model
            self.embedding_dimension = config.openai_embedding_dimension
            self.api_key = config.openai_api_key

            if not self.api_key:
                raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")

            # Qdrant 클라이언트 초기화
            self.client = QdrantClient(
                host=self.qdrant_host,
                port=self.qdrant_port,
                timeout=self.qdrant_timeout
            )

            VectorStoreClient._initialized = True
            logger.info(
                f"VectorStoreClient 초기화됨: {self.qdrant_host}:{self.qdrant_port}, "
                f"임베딩 모델: {self.embedding_model}"
            )

        except Exception as e:
            logger.error(f"VectorStoreClient 초기화 실패: {e}")
            raise

    def _encode(self, text: str) -> List[float]:
        """OpenAI API를 사용하여 텍스트를 임베딩합니다."""
        return get_embedding(
            text=text,
            api_key=self.api_key,
            model=self.embedding_model
        )

    def _generate_id(self, text: str) -> int:
        """텍스트 기반 고유 ID 생성 (Qdrant는 정수 또는 UUID만 지원)"""
        return int(hashlib.md5(text.encode()).hexdigest()[:15], 16)

    # =========================================
    # 컬렉션 관리
    # =========================================

    def create_collection(self, collection_name: str) -> bool:
        """
        새 컬렉션을 생성합니다.

        Args:
            collection_name: 컬렉션 이름

        Returns:
            성공 여부
        """
        try:
            if self.client.collection_exists(collection_name):
                logger.debug(f"컬렉션 '{collection_name}' 이미 존재함")
                return True

            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=self.embedding_dimension,
                    distance=Distance.COSINE
                )
            )
            logger.info(f"컬렉션 '{collection_name}' 생성됨")
            return True

        except Exception as e:
            logger.error(f"컬렉션 '{collection_name}' 생성 실패: {e}")
            return False

    def delete_collection(self, collection_name: str) -> bool:
        """
        컬렉션을 삭제합니다.

        Args:
            collection_name: 컬렉션 이름

        Returns:
            성공 여부
        """
        try:
            if self.client.collection_exists(collection_name):
                self.client.delete_collection(collection_name)
                logger.info(f"컬렉션 '{collection_name}' 삭제됨")
            return True

        except Exception as e:
            logger.error(f"컬렉션 '{collection_name}' 삭제 실패: {e}")
            return False

    def clear_collection(self, collection_name: str) -> bool:
        """
        컬렉션 내 모든 레코드(포인트)를 삭제합니다. 컬렉션 자체는 유지됩니다.

        Args:
            collection_name: 컬렉션 이름

        Returns:
            성공 여부
        """
        try:
            if not self.client.collection_exists(collection_name):
                logger.warning(f"컬렉션 '{collection_name}'이(가) 존재하지 않습니다.")
                return False

            self.client.delete(
                collection_name=collection_name,
                points_selector=FilterSelector(filter=Filter()),
            )
            logger.info(f"컬렉션 '{collection_name}'의 모든 레코드 삭제 완료")
            return True

        except Exception as e:
            logger.error(f"컬렉션 '{collection_name}' 레코드 삭제 실패: {e}")
            return False

    def collection_exists(self, collection_name: str) -> bool:
        """컬렉션 존재 여부를 확인합니다."""
        try:
            return self.client.collection_exists(collection_name)
        except Exception:
            return False

    # =========================================
    # 문서 CRUD
    # =========================================

    def add_document(
        self,
        collection_name: str,
        doc_id: str,
        data: Dict[str, Any],
        text_field: str
    ) -> bool:
        """
        문서를 벡터 DB에 추가합니다.

        [Qdrant 저장 구조]
        {
            id: 문서 ID (해시값),
            vector: text_field 값을 임베딩한 1536차원 벡터,
            payload: data 전체 (메타데이터)
        }

        [vector 생성 과정]
        data[text_field] (문자열)
            ↓
        OpenAI text-embedding-3-small 모델
            ↓
        vector: [0.012, -0.034, ...] (1536차원 float 배열)

        Args:
            collection_name: 컬렉션 이름
            doc_id: 문서 ID
            data: 저장할 데이터 (payload로 저장됨)
            text_field: 임베딩할 텍스트가 있는 필드명 (이 필드 값이 vector로 변환됨)

        Returns:
            성공 여부
        """
        try:
            # 임베딩할 텍스트 추출
            text = data.get(text_field, "")
            if not text:
                logger.warning(f"문서 '{doc_id}'에 '{text_field}' 필드가 없습니다.")
                return False

            # 텍스트를 벡터로 변환 (OpenAI Embedding API 호출)
            # 결과: [0.012, -0.034, 0.056, ...] 형태의 1536차원 float 배열
            embedding = self._encode(text)
            numeric_id = self._generate_id(doc_id)

            # Qdrant에 저장
            # - id: 문서 식별자
            # - vector: 임베딩된 벡터 (유사도 검색에 사용)
            # - payload: 메타데이터 (필터링, 결과 표시에 사용)
            self.client.upsert(
                collection_name=collection_name,
                points=[PointStruct(
                    id=numeric_id,
                    vector=embedding,
                    payload={**data, "_original_id": doc_id}
                )]
            )

            logger.debug(f"문서 '{doc_id}' -> '{collection_name}' 저장 완료")
            return True

        except Exception as e:
            logger.error(f"문서 저장 실패: {e}")
            return False

    def add_documents_batch(
        self,
        collection_name: str,
        documents: List[Dict[str, Any]],
        id_field: str,
        text_field: str
    ) -> int:
        """
        여러 문서를 한 번에 추가합니다.

        Args:
            collection_name: 컬렉션 이름
            documents: 문서 리스트
            id_field: 문서 ID가 있는 필드명
            text_field: 임베딩할 텍스트가 있는 필드명

        Returns:
            성공적으로 추가된 문서 수
        """
        success_count = 0
        for doc in documents:
            doc_id = doc.get(id_field, "")
            if doc_id and self.add_document(collection_name, doc_id, doc, text_field):
                success_count += 1
        return success_count

    # =========================================
    # 검색
    # =========================================

    def search(
        self,
        collection_name: str,
        query: str,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        min_score: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        유사한 문서를 검색합니다.

        Args:
            collection_name: 컬렉션 이름
            query: 검색 쿼리
            limit: 반환할 최대 결과 수
            filters: 필터 조건 {"field": "value"} 형태
            min_score: 최소 유사도 점수 (0.0 ~ 1.0)

        Returns:
            검색 결과 리스트 [{"id": ..., "score": ..., "data": ...}, ...]
        """
        try:
            query_vector = self._encode(query)

            # 필터 구성
            query_filter = None
            if filters:
                conditions = [
                    FieldCondition(key=k, match=MatchValue(value=v))
                    for k, v in filters.items()
                ]
                query_filter = Filter(must=conditions)

            # 검색 실행
            results = self.client.query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=limit,
                query_filter=query_filter,
                score_threshold=min_score if min_score > 0 else None
            )

            # 결과 포맷팅
            formatted = []
            for point in results.points:
                formatted.append({
                    "id": point.payload.get("_original_id", str(point.id)),
                    "score": round(point.score, 4),
                    "data": point.payload
                })

            logger.debug(
                f"검색 완료: '{collection_name}' -> {len(formatted)}건 "
                f"(쿼리: {query[:30]}...)"
            )
            return formatted

        except Exception as e:
            logger.error(f"검색 실패: {e}")
            return []

    # =========================================
    # 유틸리티
    # =========================================

    def health_check(self) -> bool:
        """Qdrant 연결 상태를 확인합니다."""
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

    def get_stats(self) -> Dict[str, Any]:
        """모든 컬렉션의 통계를 반환합니다."""
        try:
            collections = self.client.get_collections().collections
            stats = {}
            for col in collections:
                info = self.client.get_collection(col.name)
                stats[col.name] = {
                    "points_count": info.points_count
                }
            return stats
        except Exception as e:
            logger.error(f"통계 조회 실패: {e}")
            return {}

    def get_collection_info(self, collection_name: str) -> Optional[Dict[str, Any]]:
        """특정 컬렉션의 정보를 반환합니다."""
        try:
            if not self.client.collection_exists(collection_name):
                return None
            info = self.client.get_collection(collection_name)
            return {
                "name": collection_name,
                "points_count": info.points_count,
                "vector_size": info.config.params.vectors.size
            }
        except Exception as e:
            logger.error(f"컬렉션 정보 조회 실패: {e}")
            return None
