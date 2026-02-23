import logging
from typing import Dict, Any

from ..state import AnalysisState
from ...clients.backend_client import BackendClient

logger = logging.getLogger(__name__)

def update_backend_node(state: AnalysisState, backend_client: BackendClient) -> Dict[str, Any]:
    """
    정밀 분석 결과를 백엔드에 업데이트하는 노드

    Args:
        state: 현재 분석 상태
        backend_client: 백엔드 클라이언트 인스턴스

    Returns:
        업데이트된 상태 딕셔너리
    """
    camera_id = state["camera_id"]
    event_id = state.get("event_id")
    
    if not event_id:
        logger.error(f"[{camera_id}] 업데이트할 Event ID가 없습니다.")
        return {"errors": state.get("errors", []) + ["Update backend failed: No event_id"]}

    logger.info(f"[{camera_id}] 상세 분석 결과 백엔드 업데이트 시작... (Event ID: {event_id})")

    try:
        detail_result = {
            "risk": state.get("risk_level"),
            "type": state.get("event_type"),
            "summary": state.get("summary"),
            "risk_score": state.get("risk_score")
        }

        success = backend_client.update_event(event_id, detail_result)

        if success:
            logger.info(f"[{camera_id}] 백엔드 업데이트 성공")
            return {} # 상태 변경 없음
        else:
            logger.error(f"[{camera_id}] 백엔드 업데이트 실패")
            return {"errors": state.get("errors", []) + ["Update backend failed"]}

    except Exception as e:
        logger.error(f"[{camera_id}] 백엔드 업데이트 중 오류 발생: {e}", exc_info=True)
        return {"errors": state.get("errors", []) + [f"Update backend exception: {e}"]}
