"""
Qdrant Vector Store 클라이언트
과거 이벤트 검색, RAG 기반 대응 매뉴얼 검색
"""
import os
import logging
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
from sentence_transformers import SentenceTransformer
import hashlib

logger = logging.getLogger(__name__)


def get_env(key: str, default: str = None) -> str:
    """환경 변수에서 값을 가져옵니다."""
    return os.environ.get(key, default)


def get_env_int(key: str, default: int = 0) -> int:
    """환경 변수에서 정수 값을 가져옵니다."""
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


class VectorStoreClient:
    """Qdrant 벡터 스토어 클라이언트"""

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        """싱글톤 패턴"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        host: str = None,
        port: int = None,
        embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    ):
        """
        Args:
            host: Qdrant 호스트 (기본: 환경변수 또는 aegis-qdrant)
            port: Qdrant 포트 (기본: 환경변수 또는 6333)
            embedding_model: Sentence Transformer 모델명
        """
        if VectorStoreClient._initialized:
            return

        self.host = host or get_env("QDRANT_HOST", "aegis-qdrant")
        self.port = port or get_env_int("QDRANT_PORT", 6333)

        try:
            self.client = QdrantClient(host=self.host, port=self.port, timeout=30)
            self.encoder = SentenceTransformer(embedding_model)
            self.vector_size = self.encoder.get_sentence_embedding_dimension()

            # 컬렉션 초기화
            self._init_collections()

            VectorStoreClient._initialized = True
            logger.info(f"VectorStoreClient 초기화됨: {self.host}:{self.port}")

        except Exception as e:
            logger.error(f"VectorStoreClient 초기화 실패: {e}")
            raise

    def _init_collections(self):
        """필요한 컬렉션들을 초기화합니다."""
        collections = {
            "past_events": "과거 이벤트 기록",
            "manuals": "대응 매뉴얼",
            "frames": "프레임 메타데이터"
        }

        for collection_name, description in collections.items():
            try:
                if not self.client.collection_exists(collection_name):
                    self.client.create_collection(
                        collection_name=collection_name,
                        vectors_config=VectorParams(
                            size=self.vector_size,
                            distance=Distance.COSINE
                        )
                    )
                    logger.info(f"컬렉션 '{collection_name}' 생성됨: {description}")
                else:
                    logger.debug(f"컬렉션 '{collection_name}' 이미 존재함")
            except Exception as e:
                logger.error(f"컬렉션 '{collection_name}' 초기화 실패: {e}")

    def _generate_id(self, text: str) -> str:
        """텍스트 기반 고유 ID 생성"""
        return hashlib.md5(text.encode()).hexdigest()

    # =========================================
    # 과거 이벤트 관련 메서드
    # =========================================

    def add_event(self, event_id: str, event_data: Dict[str, Any]) -> bool:
        """
        과거 이벤트를 벡터 DB에 저장합니다.

        Args:
            event_id: 이벤트 ID
            event_data: 이벤트 데이터 (summary, event_type, resolution 등)

        Returns:
            성공 여부
        """
        try:
            # 요약문을 임베딩
            summary = event_data.get('summary', '')
            if not summary:
                logger.warning(f"이벤트 '{event_id}'에 summary가 없습니다.")
                return False

            embedding = self.encoder.encode(summary)

            # 숫자 ID 생성 (Qdrant는 정수 또는 UUID만 지원)
            numeric_id = int(self._generate_id(event_id)[:15], 16)

            # Qdrant에 저장
            self.client.upsert(
                collection_name="past_events",
                points=[PointStruct(
                    id=numeric_id,
                    vector=embedding.tolist(),
                    payload={**event_data, "original_id": event_id}
                )]
            )

            logger.info(f"이벤트 '{event_id}' 저장 완료")
            return True

        except Exception as e:
            logger.error(f"이벤트 저장 실패: {e}")
            return False

    def search_similar_events(
        self,
        query: str,
        limit: int = 5,
        event_type: Optional[str] = None,
        min_score: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        유사한 과거 이벤트를 검색합니다.

        Args:
            query: 검색 쿼리 (예: "두 사람이 격렬하게 다툼")
            limit: 반환할 최대 결과 수
            event_type: 이벤트 타입 필터 (예: "ASSAULT")
            min_score: 최소 유사도 점수

        Returns:
            유사한 이벤트 리스트
        """
        try:
            # 쿼리를 임베딩
            query_vector = self.encoder.encode(query)

            # 필터 설정
            query_filter = None
            if event_type:
                query_filter = Filter(
                    must=[FieldCondition(
                        key="event_type",
                        match=MatchValue(value=event_type)
                    )]
                )

            # 검색 실행 (최신 Qdrant 클라이언트 API)
            results = self.client.query_points(
                collection_name="past_events",
                query=query_vector.tolist(),
                limit=limit,
                query_filter=query_filter,
                score_threshold=min_score
            )

            # 결과 포맷팅
            similar_events = []
            for result in results.points:
                similar_events.append({
                    "event_id": result.payload.get("original_id", str(result.id)),
                    "score": round(result.score, 4),
                    "data": result.payload
                })

            logger.info(f"유사 이벤트 {len(similar_events)}건 검색됨 (쿼리: {query[:30]}...)")
            return similar_events

        except Exception as e:
            logger.error(f"유사 이벤트 검색 실패: {e}")
            return []

    # =========================================
    # 대응 매뉴얼 관련 메서드
    # =========================================

    def add_manual(self, manual_id: str, manual_data: Dict[str, Any]) -> bool:
        """
        대응 매뉴얼을 벡터 DB에 저장합니다.

        Args:
            manual_id: 매뉴얼 ID
            manual_data: 매뉴얼 데이터 (title, content, category 등)

        Returns:
            성공 여부
        """
        try:
            # 제목 + 내용을 임베딩
            title = manual_data.get('title', '')
            content = manual_data.get('content', '')
            text = f"{title} {content}"

            if not text.strip():
                logger.warning(f"매뉴얼 '{manual_id}'에 내용이 없습니다.")
                return False

            embedding = self.encoder.encode(text)

            # 숫자 ID 생성
            numeric_id = int(self._generate_id(manual_id)[:15], 16)

            # Qdrant에 저장
            self.client.upsert(
                collection_name="manuals",
                points=[PointStruct(
                    id=numeric_id,
                    vector=embedding.tolist(),
                    payload={**manual_data, "original_id": manual_id}
                )]
            )

            logger.info(f"매뉴얼 '{manual_id}' 저장 완료: {title}")
            return True

        except Exception as e:
            logger.error(f"매뉴얼 저장 실패: {e}")
            return False

    def search_manuals(
        self,
        query: str,
        limit: int = 3,
        category: Optional[str] = None,
        min_score: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        관련 대응 매뉴얼을 검색합니다.

        Args:
            query: 검색 쿼리 (예: "폭행 대응 방법")
            limit: 반환할 최대 결과 수
            category: 카테고리 필터 (예: "emergency")
            min_score: 최소 유사도 점수

        Returns:
            관련 매뉴얼 리스트
        """
        try:
            # 쿼리를 임베딩
            query_vector = self.encoder.encode(query)

            # 필터 설정
            query_filter = None
            if category:
                query_filter = Filter(
                    must=[FieldCondition(
                        key="category",
                        match=MatchValue(value=category)
                    )]
                )

            # 검색 실행 (최신 Qdrant 클라이언트 API)
            results = self.client.query_points(
                collection_name="manuals",
                query=query_vector.tolist(),
                limit=limit,
                query_filter=query_filter,
                score_threshold=min_score
            )

            # 결과 포맷팅
            manuals = []
            for result in results.points:
                manuals.append({
                    "manual_id": result.payload.get("original_id", str(result.id)),
                    "score": round(result.score, 4),
                    "data": result.payload
                })

            logger.info(f"매뉴얼 {len(manuals)}건 검색됨 (쿼리: {query[:30]}...)")
            return manuals

        except Exception as e:
            logger.error(f"매뉴얼 검색 실패: {e}")
            return []

    # =========================================
    # 프레임 메타데이터 관련 메서드
    # =========================================

    def add_frame_metadata(
        self,
        frame_id: str,
        camera_id: str,
        timestamp: str,
        description: str,
        clip_url: Optional[str] = None
    ) -> bool:
        """
        프레임 메타데이터를 벡터 DB에 저장합니다.

        Args:
            frame_id: 프레임 ID
            camera_id: 카메라 ID
            timestamp: 타임스탬프
            description: VLM이 생성한 장면 설명
            clip_url: 관련 클립 URL (MinIO)

        Returns:
            성공 여부
        """
        try:
            embedding = self.encoder.encode(description)
            numeric_id = int(self._generate_id(frame_id)[:15], 16)

            self.client.upsert(
                collection_name="frames",
                points=[PointStruct(
                    id=numeric_id,
                    vector=embedding.tolist(),
                    payload={
                        "original_id": frame_id,
                        "camera_id": camera_id,
                        "timestamp": timestamp,
                        "description": description,
                        "clip_url": clip_url
                    }
                )]
            )

            logger.debug(f"프레임 메타데이터 '{frame_id}' 저장 완료")
            return True

        except Exception as e:
            logger.error(f"프레임 메타데이터 저장 실패: {e}")
            return False

    def search_frames(
        self,
        query: str,
        limit: int = 10,
        camera_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        설명 기반으로 프레임을 검색합니다.

        Args:
            query: 검색 쿼리 (예: "빨간 옷을 입은 사람")
            limit: 반환할 최대 결과 수
            camera_id: 카메라 ID 필터

        Returns:
            관련 프레임 리스트
        """
        try:
            query_vector = self.encoder.encode(query)

            query_filter = None
            if camera_id:
                query_filter = Filter(
                    must=[FieldCondition(
                        key="camera_id",
                        match=MatchValue(value=camera_id)
                    )]
                )

            results = self.client.query_points(
                collection_name="frames",
                query=query_vector.tolist(),
                limit=limit,
                query_filter=query_filter
            )

            frames = []
            for result in results.points:
                frames.append({
                    "frame_id": result.payload.get("original_id", str(result.id)),
                    "score": round(result.score, 4),
                    "data": result.payload
                })

            logger.info(f"프레임 {len(frames)}건 검색됨")
            return frames

        except Exception as e:
            logger.error(f"프레임 검색 실패: {e}")
            return []

    # =========================================
    # 유틸리티 메서드
    # =========================================

    def get_stats(self) -> Dict[str, Any]:
        """벡터 DB 통계를 반환합니다."""
        try:
            stats = {}
            for collection_name in ["past_events", "manuals", "frames"]:
                if self.client.collection_exists(collection_name):
                    info = self.client.get_collection(collection_name)
                    stats[collection_name] = {
                        "points_count": info.points_count
                    }
            return stats
        except Exception as e:
            logger.error(f"통계 조회 실패: {e}")
            return {}

    def health_check(self) -> bool:
        """Qdrant 연결 상태를 확인합니다."""
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

    def clear_collection(self, collection_name: str) -> bool:
        """컬렉션의 모든 데이터를 삭제합니다."""
        try:
            if self.client.collection_exists(collection_name):
                self.client.delete_collection(collection_name)
                self._init_collections()
                logger.info(f"컬렉션 '{collection_name}' 초기화됨")
            return True
        except Exception as e:
            logger.error(f"컬렉션 초기화 실패: {e}")
            return False
