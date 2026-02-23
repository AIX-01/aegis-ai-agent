import logging
from typing import Dict, Any

from ..state import AnalysisState, RiskLevel, EventType
from ...clients.precision_client import PrecisionClient

logger = logging.getLogger(__name__)

def precision_analysis_node(state: AnalysisState, precision_client: PrecisionClient) -> Dict[str, Any]:
    """
    정밀 분석(LLM)을 수행하는 노드

    Args:
        state: 현재 분석 상태
        precision_client: 정밀 분석 클라이언트 인스턴스

    Returns:
        업데이트된 상태 딕셔너리 (risk_level, event_type, summary, risk_score, precision_result)
    """
    camera_id = state["camera_id"]
    frames = state["frames"]
    occurred_at = state["occurred_at"]
    event_id = state.get("event_id")
    vlm_result = state.get("vlm_result", {}) # VLM 원본 결과 사용

    logger.info(f"[{camera_id}] 정밀 분석(LLM) 시작... (Event ID: {event_id})")

    try:
        # 정밀 분석 요청에 VLM 결과와 메타데이터 전달
        task_metadata = {
            "occurred_at": occurred_at,
            "window_start": state.get("window_start", occurred_at),
            "window_end": state.get("window_end", occurred_at),
            "frame_timestamps": state.get("frame_timestamps", []),  # 프레임별 타임스탬프 추가
            "camera_name": state.get("camera_name", ""),
            "camera_location": state.get("camera_location", ""),
        }

        result = precision_client.send_for_analysis(camera_id, frames, vlm_result, task_metadata)

        if result:
            # 결과 파싱 및 상태 업데이트
            # DATA-MODEL.md의 EventRisk와 EventType을 참고하여 risk_level 결정
            new_event_type: EventType = result.get("event_type", "").upper()
            new_summary: str = result.get("summary", "")
            new_risk_score: float = result.get("risk_score", 0.0)

            # event_type에 따라 risk_level 결정
            if new_event_type in ["ASSAULT", "BURGLARY", "DUMP", "SWOON", "VANDALISM"]:
                new_risk_level: RiskLevel = "ABNORMAL"
            elif new_risk_score > 0.5:  # 유효한 event_type이 없지만 점수가 높으면 SUSPICIOUS
                new_risk_level = "SUSPICIOUS"
            else:
                new_risk_level = "NORMAL"
            
            logger.info(f"[{camera_id}] 정밀 분석 완료: {new_risk_level} - {new_event_type} (Score: {new_risk_score:.2f})")
            
            # 최종 결과를 상태 딕셔너리로 반환
            return {
                "precision_result": result,     # LLM 원본 결과 저장
                "risk_level": new_risk_level,   # 최종 risk_level 갱신
                "event_type": new_event_type,   # 최종 event_type 갱신
                "summary": new_summary,
                "risk_score": new_risk_score
            }
        else:
            logger.error(f"[{camera_id}] 정밀 분석 실패: 응답 없음")
            return {"errors": state.get("errors", []) + ["Precision analysis failed: No response"]}

    except Exception as e:
        logger.error(f"[{camera_id}] 정밀 분석 중 오류 발생: {e}", exc_info=True)
        return {"errors": state.get("errors", []) + [f"Precision analysis exception: {e}"]}