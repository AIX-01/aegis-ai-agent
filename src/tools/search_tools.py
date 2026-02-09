"""
검색(Retrieval) 관련 도구 모음
- 대응 매뉴얼 검색
- 유사 과거 사례 검색

VectorStoreClient를 사용하여 Qdrant에서 유사 문서를 검색합니다.

사용 예시:
    from src.tools.search_tools import search_manual, search_past_cases
    from src.config import Config

    config = Config()

    # 매뉴얼 검색
    results = search_manual("폭행 대응 방법", config)

    # 과거 사례 검색
    results = search_past_cases("야간 절도 사건", config)
"""
import logging
from typing import List, Dict, Any, Optional, TYPE_CHECKING

from ..clients.vector_store_client import VectorStoreClient

if TYPE_CHECKING:
    from ..config import Config

logger = logging.getLogger(__name__)

# 컬렉션 이름 상수
MANUAL_COLLECTION = "manuals"
PAST_CASES_COLLECTION = "past_cases"


def search_manual(
    query: str,
    config: "Config",
    limit: int = 3
) -> List[Dict[str, Any]]:
    """
    대응 매뉴얼을 검색합니다.

    Args:
        query: 검색 쿼리
        config: Config 인스턴스
        limit: 반환할 최대 결과 수

    Returns:
        검색 결과 리스트 [{"id": ..., "score": ..., "payload": {...}}, ...]
    """
    logger.info(f"매뉴얼 검색: query='{query}', limit={limit}")

    try:
        client = VectorStoreClient(config)

        # 컬렉션 존재 여부 확인
        if not client.collection_exists(MANUAL_COLLECTION):
            logger.warning(f"컬렉션 '{MANUAL_COLLECTION}'이 존재하지 않습니다.")
            return []

        results = client.search(
            collection_name=MANUAL_COLLECTION,
            query=query,
            limit=limit
        )

        logger.info(f"매뉴얼 검색 완료: {len(results)}건 발견")
        return results

    except Exception as e:
        logger.error(f"매뉴얼 검색 실패: {e}")
        return []


def search_past_cases(
    query: str,
    config: "Config",
    limit: int = 5,
    event_type: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    유사 과거 사례를 검색합니다.

    Args:
        query: 검색 쿼리
        config: Config 인스턴스
        limit: 반환할 최대 결과 수
        event_type: 이벤트 유형 필터 (ASSAULT, BURGLARY, DUMP, SWOON, VANDALISM)

    Returns:
        검색 결과 리스트 [{"id": ..., "score": ..., "payload": {...}}, ...]
    """
    logger.info(f"과거 사례 검색: query='{query}', limit={limit}, event_type={event_type}")

    try:
        client = VectorStoreClient(config)

        # 컬렉션 존재 여부 확인
        if not client.collection_exists(PAST_CASES_COLLECTION):
            logger.warning(f"컬렉션 '{PAST_CASES_COLLECTION}'이 존재하지 않습니다.")
            return []

        # 필터 구성
        filters = None
        if event_type:
            filters = {"event_type": event_type}

        results = client.search(
            collection_name=PAST_CASES_COLLECTION,
            query=query,
            limit=limit,
            filters=filters
        )

        logger.info(f"과거 사례 검색 완료: {len(results)}건 발견")
        return results

    except Exception as e:
        logger.error(f"과거 사례 검색 실패: {e}")
        return []


def format_search_results(results: List[Dict[str, Any]]) -> str:
    """
    검색 결과를 문자열로 포맷팅합니다.

    Args:
        results: 검색 결과 리스트

    Returns:
        포맷팅된 문자열
    """
    if not results:
        return "검색 결과가 없습니다."

    formatted = []
    for i, result in enumerate(results, 1):
        payload = result.get("payload", {})
        score = result.get("score", 0.0)
        title = payload.get("title", "제목 없음")
        content = payload.get("content", "내용 없음")

        # 내용이 길면 잘라서 표시
        if len(content) > 200:
            content = content[:200] + "..."

        formatted.append(f"[{i}] (유사도: {score:.2f}) {title}\n{content}")

    return "\n\n".join(formatted)

