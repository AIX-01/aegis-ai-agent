import logging
from typing import Dict, Any

from ..state import AnalysisState, RiskLevel
from ...clients.verification_client import VerificationClient

logger = logging.getLogger(__name__)


def verification_node(state: AnalysisState, verification_client: VerificationClient) -> Dict[str, Any]:
    """
    'SUSPICIOUS' 상태를 검증하는 노드

    SUSPICIOUS 상태를 OpenAI Vision API를 통해 검증하여
    ABNORMAL(이상)로 격상하거나 SUSPICIOUS(의심)를 유지합니다.

    Args:
        state: 현재 분석 상태
        verification_client: 검증 클라이언트 인스턴스

    Returns:
        업데이트된 상태 딕셔너리 (risk_level, verification_result)
    """
    camera_id = state["camera_id"]
    frames = state["frames"]
    occurred_at = state["occurred_at"]
    vlm_result = state.get("vlm_result", {})

    logger.info(f"[{camera_id}] SUSPICIOUS 상태 검증 시작...")

    try:
        # 메타데이터 구성
        task_metadata = {
            "occurred_at": occurred_at,
            "window_start": state.get("window_start", occurred_at),
            "window_end": state.get("window_end", occurred_at)
        }

        # 검증 요청
        result = verification_client.verify(camera_id, frames, vlm_result, task_metadata)

        if result:
            new_risk_level: RiskLevel = result.get("risk_level", "ABNORMAL")
            reason = result.get("reason", "")

            logger.info(
                f"[{camera_id}] 검증 완료: {new_risk_level} "
                f"(사유: {reason})"
            )

            return {
                "verification_result": result,
                "risk_level": new_risk_level
            }
        else:
            # 검증 실패 시 안전하게 ABNORMAL로 격상
            logger.warning(f"[{camera_id}] 검증 응답 없음 - 안전을 위해 ABNORMAL로 격상")
            return {
                "risk_level": "ABNORMAL",
                "verification_result": {
                    "risk_level": "ABNORMAL",
                    "reason": "검증 응답 없음으로 인한 안전 격상"
                }
            }

    except Exception as e:
        logger.error(f"[{camera_id}] 검증 중 오류 발생: {e}", exc_info=True)
        # 오류 시에도 안전하게 ABNORMAL로 격상
        return {
            "risk_level": "ABNORMAL",
            "verification_result": {
                "risk_level": "ABNORMAL",
                "reason": f"검증 오류로 인한 안전 격상: {e}"
            },
            "errors": state.get("errors", []) + [f"Verification exception: {e}"]
        }
