import logging
from typing import Optional, TYPE_CHECKING

from langchain_core.tools import tool

if TYPE_CHECKING:
    from ..clients.vector_store_client import VectorStoreClient

logger = logging.getLogger(__name__)

# 전역 클라이언트 (action_node에서 주입)
_vector_client: Optional["VectorStoreClient"] = None


def set_vector_client(client: "VectorStoreClient"):
    """VectorStoreClient 인스턴스를 설정합니다."""
    global _vector_client
    _vector_client = client


@tool
def search_manual(query: str) -> str:
    """
    상황에 맞는 대응 매뉴얼을 검색합니다.

    이 도구는 이상 상황 발생 시 적절한 대응 방법을 찾기 위해 사용합니다.
    폭행, 침입, 불법투기, 기절, 기물파손 등의 상황에 대한 대응 절차를 검색할 수 있습니다.

    Args:
        query: 검색할 상황 설명 (예: "폭행 사건 발생 시 대응 절차", "침입자 발견 시 조치 방법")

    Returns:
        검색된 매뉴얼 내용 또는 검색 실패 메시지
    """
    if _vector_client is None:
        logger.error("VectorStoreClient가 설정되지 않았습니다.")
        return "매뉴얼 검색 서비스를 사용할 수 없습니다."

    try:
        # enabled=true인 매뉴얼만 검색
        results = _vector_client.search(
            collection_name="manuals",
            query=query,
            limit=3,
            filters={"enabled": True},
            min_score=0.5
        )

        if not results:
            logger.info(f"매뉴얼 검색 결과 없음: {query}")
            return f"'{query}'에 대한 관련 매뉴얼을 찾을 수 없습니다."

        # 결과 포맷팅
        formatted_results = []
        for i, result in enumerate(results, 1):
            data = result.get("data", {})
            name = data.get("name", "제목 없음")
            content = data.get("content", "")
            score = result.get("score", 0)

            formatted_results.append(
                f"[매뉴얼 {i}] {name} (관련도: {score:.2f})\n{content}"
            )

        logger.info(f"매뉴얼 검색 완료: {query} -> {len(results)}건")
        return "\n\n---\n\n".join(formatted_results)

    except Exception as e:
        logger.error(f"매뉴얼 검색 중 오류: {e}", exc_info=True)
        return f"매뉴얼 검색 중 오류가 발생했습니다: {str(e)}"

