import logging
from typing import Dict, Any

from ..state import AnalysisState
from ...clients.backend_client import BackendClient

logger = logging.getLogger(__name__)

def backend_report_node(state: AnalysisState, backend_client: BackendClient) -> Dict[str, Any]:
    """
    1차 분석 결과를 백엔드에 보고하고 event_id를 받는 노드

    Args:
        state: 현재 분석 상태
        backend_client: 백엔드 클라이언트 인스턴스

    Returns:
        업데이트된 상태 딕셔너리 (event_id)
    """
    camera_id = state["camera_id"]
    risk_level = state.get("risk_level", "UNKNOWN")
    occurred_at = state["occurred_at"]

    logger.info(f"[{camera_id}] 1차 분석 결과 백엔드 보고 시작... (Risk: {risk_level})")

    try:
        vlm_result = {"primary_category": risk_level}
        task_metadata = {"timestamp": occurred_at}

        event_id = backend_client.send_vlm_result(camera_id, vlm_result, task_metadata)

        if event_id:
            logger.info(f"[{camera_id}] 백엔드로부터 Event ID '{event_id}' 수신")
            return {"event_id": event_id}
        else:
            logger.error(f"[{camera_id}] Event ID 수신 실패")
            return {"errors": state.get("errors", []) + ["Backend report failed: No event_id received"]}

    except Exception as e:
        logger.error(f"[{camera_id}] 백엔드 보고 중 오류 발생: {e}", exc_info=True)
        return {"errors": state.get("errors", []) + [f"Backend report exception: {e}"]}
