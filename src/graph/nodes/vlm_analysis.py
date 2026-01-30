import logging
from typing import Dict, Any

from ..state import AnalysisState
from ...clients.vlm_client import VLMClient

logger = logging.getLogger(__name__)

def vlm_analysis_node(state: AnalysisState, vlm_client: VLMClient) -> Dict[str, Any]:
    """
    VLM을 사용하여 1차 분석을 수행하는 노드

    Args:
        state: 현재 분석 상태
        vlm_client: VLM 클라이언트 인스턴스

    Returns:
        업데이트된 상태 딕셔너리
    """
    camera_id = state["camera_id"]
    frames = state["frames"]
    occurred_at = state["occurred_at"]

    logger.info(f"[{camera_id}] VLM 1차 분석 시작...")

    try:
        # VLM 클라이언트를 사용하여 프레임 분석
        task_metadata = {"timestamp": occurred_at}
        result = vlm_client.analyze_frames(camera_id, frames, task_metadata)

        if result and "primary_category" in result:
            risk_level = result["primary_category"].upper()
            event_type = result.get("secondary_category", "")
            
            logger.info(f"[{camera_id}] VLM 분석 결과: {risk_level} ({event_type})")
            
            return {
                "vlm_result": result,       # 원본 결과 저장
                "risk_level": risk_level,   # 최종 상태 초기화
                "event_type": event_type    # 최종 상태 초기화
            }
        else:
            logger.error(f"[{camera_id}] VLM 분석 결과가 유효하지 않습니다.")
            return {"errors": state.get("errors", []) + ["VLM analysis failed: Invalid response"]}

    except Exception as e:
        logger.error(f"[{camera_id}] VLM 분석 중 오류 발생: {e}", exc_info=True)
        return {"errors": state.get("errors", []) + [f"VLM analysis exception: {e}"]}
