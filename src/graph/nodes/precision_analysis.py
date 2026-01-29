import logging
from typing import Dict, Any

from ..state import AnalysisState
from ...clients.precision_client import PrecisionClient

logger = logging.getLogger(__name__)

def precision_analysis_node(state: AnalysisState, precision_client: PrecisionClient) -> Dict[str, Any]:
    """
    정밀 분석(LLM)을 수행하는 노드

    Args:
        state: 현재 분석 상태
        precision_client: 정밀 분석 클라이언트 인스턴스

    Returns:
        업데이트된 상태 딕셔너리 (event_type, summary, risk_score)
    """
    camera_id = state["camera_id"]
    frames = state["frames"]
    occurred_at = state["occurred_at"]
    risk_level = state.get("risk_level", "UNKNOWN")
    event_id = state.get("event_id")

    logger.info(f"[{camera_id}] 정밀 분석(LLM) 시작... (Event ID: {event_id})")

    try:
        # VLM 메타데이터 구성 (1차 분석 결과를 바탕으로)
        vlm_metadata = {
            "primary_category": risk_level,
            "secondary_category": "",
            "confidence": 0.0, # VLM에서 confidence를 받지 않았다면 0.0
            "description": f"Risk Level: {risk_level}"
        }
        
        task_metadata = {
            "timestamp": occurred_at,
            # window_start/end 정보가 state에 있다면 추가
        }

        # 정밀 분석 요청
        result = precision_client.send_for_analysis(camera_id, frames, vlm_metadata, task_metadata)

        if result:
            # 결과 파싱 및 상태 업데이트
            event_type = result.get("event_type", "UNKNOWN")
            summary = result.get("summary", "")
            risk_score = result.get("risk_score", 0.0)
            
            logger.info(f"[{camera_id}] 정밀 분석 완료: {event_type} (Score: {risk_score})")
            
            return {
                "event_type": event_type,
                "summary": summary,
                "risk_score": risk_score
            }
        else:
            logger.error(f"[{camera_id}] 정밀 분석 실패: 응답 없음")
            return {"errors": state.get("errors", []) + ["Precision analysis failed: No response"]}

    except Exception as e:
        logger.error(f"[{camera_id}] 정밀 분석 중 오류 발생: {e}", exc_info=True)
        return {"errors": state.get("errors", []) + [f"Precision analysis exception: {e}"]}
