"""
이벤트 정보를 벡터 스토어에 임베딩하여 저장하는 노드

과거 사례로 저장되어 추후 유사 사례 검색에 활용됩니다.
action 노드와 병렬로 실행됩니다.
"""
import logging
from typing import Dict, Any

from ..state import AnalysisState
from ...clients.vector_store_client import VectorStoreClient
from ...config import Config

logger = logging.getLogger(__name__)

# 컬렉션 이름 상수
PAST_CASES_COLLECTION = "past_cases"


def store_embedding_node(state: AnalysisState, config: Config) -> Dict[str, Any]:
    """
    이벤트 정보를 벡터 스토어에 임베딩하여 저장합니다.

    정밀 분석이 완료되고 ABNORMAL로 확정된 이벤트를 과거 사례로 저장합니다.
    summary + 메타데이터를 결합하여 임베딩하므로, 자연어 검색 시
    카메라 위치, 발생 시각, 이벤트 유형 등으로도 검색이 가능합니다.

    Args:
        state: 현재 분석 상태 (event_id, summary, event_type, risk_score 등)
        config: 시스템 설정

    Returns:
        업데이트된 상태 딕셔너리
    """
    camera_uuid = state["camera_id"]  # camera_id는 실제로 UUID
    camera_name = state.get("camera_name", "")
    camera_location = state.get("camera_location", "")
    event_id = state.get("event_id")
    summary = state.get("summary", "")
    event_type = state.get("event_type", "")
    risk_score = state.get("risk_score", 0.0)
    risk_level = state.get("risk_level", "ABNORMAL")
    occurred_at = state.get("occurred_at")

    logger.info(f"[{camera_uuid}] 이벤트 임베딩 저장 시작... (Event ID: {event_id})")

    # summary가 없으면 저장 생략
    if not summary:
        logger.warning(f"[{camera_uuid}] summary가 없어 임베딩 저장을 생략합니다.")
        return {"embedding_stored": False}

    try:
        client = VectorStoreClient(config)

        # 컬렉션 존재 여부 확인 및 생성
        if not client.collection_exists(PAST_CASES_COLLECTION):
            logger.info(f"컬렉션 '{PAST_CASES_COLLECTION}' 생성 중...")
            client.create_collection(PAST_CASES_COLLECTION)

        # 발생 시각 포맷팅
        occurred_at_str = occurred_at.strftime("%Y년 %m월 %d일 %H시 %M분") if occurred_at else "알 수 없음"

        # 임베딩용 텍스트 구성 (summary + 메타데이터)
        # 자연어 검색 시 카메라 위치, 시간, 이벤트 유형으로도 검색 가능
        text_to_embed = f"""카메라: {camera_name} ({camera_location})
발생시각: {occurred_at_str}
이벤트유형: {event_type}
상황: {summary}"""

        # 저장할 문서 데이터 구성 (payload)
        doc_data = {
            "event_id": event_id,
            "camera_uuid": camera_uuid,
            "camera_name": camera_name,
            "camera_location": camera_location,
            "event_type": event_type,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "summary": summary,
            "occurred_at": occurred_at.isoformat() if occurred_at else None,
            "text_embedded": text_to_embed,  # 임베딩된 원본 텍스트 저장
        }

        # 문서 추가 (text_to_embed를 임베딩)
        client.add_document(
            collection_name=PAST_CASES_COLLECTION,
            doc_id=event_id or f"{camera_uuid}_{occurred_at}",
            data=doc_data,
            text_field="text_embedded"
        )

        logger.info(f"[{camera_uuid}] 이벤트 임베딩 저장 완료 (Event ID: {event_id})")
        return {"embedding_stored": True}

    except Exception as e:
        logger.error(f"[{camera_uuid}] 이벤트 임베딩 저장 실패: {e}", exc_info=True)
        return {
            "embedding_stored": False,
            "errors": state.get("errors", []) + [f"Store embedding exception: {e}"]
        }

