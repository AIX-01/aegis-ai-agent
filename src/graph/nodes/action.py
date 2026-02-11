import logging
from typing import Dict, Any

from ..state import AnalysisState
from ...clients.action_client import ActionClient

logger = logging.getLogger(__name__)


def action_node(state: AnalysisState, action_client: ActionClient) -> Dict[str, Any]:
    """
    정밀 분석 결과를 바탕으로 대응 조치(Action)를 LLM으로 결정하는 노드

    Args:
        state: 현재 분석 상태
        action_client: 대응 조치 클라이언트 인스턴스

    Returns:
        업데이트된 상태 딕셔너리 (actions)
    """
    camera_id = state["camera_id"]
    camera_name = state.get("camera_name", "unknown")
    camera_location = state.get("camera_location", "unknown")
    risk_level = state.get("risk_level", "UNKNOWN")
    event_type = state.get("event_type", "UNKNOWN")
    risk_score = state.get("risk_score", 0.0)
    summary = state.get("summary", "")

    logger.info(f"[{camera_id}] 대응 조치(Action) 결정 시작... (Risk: {risk_level}, Type: {event_type})")

    try:
        result = action_client.decide_actions(
            camera_id=camera_id,
            camera_name=camera_name,
            camera_location=camera_location,
            event_type=event_type,
            risk_level=risk_level,
            risk_score=risk_score,
            summary=summary,
        )

        if result is not None:
            logger.info(f"[{camera_id}] 대응 조치 결정 완료: {len(result)}건")
            return {"actions": result}
        else:
            logger.warning(f"[{camera_id}] 대응 조치 결정 실패: 응답 없음")
            return {
                "actions": [],
                "errors": state.get("errors", []) + ["Action decision failed: No response"],
            }

    except Exception as e:
        logger.error(f"[{camera_id}] 대응 조치 결정 중 오류 발생: {e}", exc_info=True)
        return {
            "actions": [],
            "errors": state.get("errors", []) + [f"Action exception: {e}"],
        }
