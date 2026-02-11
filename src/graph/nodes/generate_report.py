"""
최종 보고서를 생성하는 노드 (LLM 기반)
"""
import logging
from typing import Dict, Any

from ..state import AnalysisState
from ...clients.report_client import ReportClient

logger = logging.getLogger(__name__)


def generate_report_node(state: AnalysisState, report_client: ReportClient) -> Dict[str, Any]:
    """
    분석 결과와 대응 조치를 종합하여 최종 사건 보고서를 생성하는 노드

    Args:
        state: 현재 분석 상태
        report_client: 보고서 생성 클라이언트 인스턴스

    Returns:
        업데이트된 상태 딕셔너리 (report)
    """
    camera_id = state["camera_id"]

    logger.info(f"[{camera_id}] 최종 보고서 생성 시작...")

    try:
        report = report_client.generate_report(
            camera_id=camera_id,
            camera_name=state.get("camera_name", "unknown"),
            camera_location=state.get("camera_location", "unknown"),
            occurred_at=state.get("occurred_at", "N/A"),
            event_type=state.get("event_type", "UNKNOWN"),
            risk_level=state.get("risk_level", "UNKNOWN"),
            risk_score=state.get("risk_score", 0.0),
            summary=state.get("summary", ""),
            vlm_summary=state.get("vlm_summary", ""),
            actions=state.get("actions", []),
        )

        if report:
            logger.info(f"[{camera_id}] 보고서 생성 완료 ({len(report)}자)")
            return {"report": report}
        else:
            logger.warning(f"[{camera_id}] 보고서 생성 실패: 응답 없음")
            return {
                "report": "",
                "errors": state.get("errors", []) + ["Report generation failed: No response"],
            }

    except Exception as e:
        logger.error(f"[{camera_id}] 보고서 생성 중 오류 발생: {e}", exc_info=True)
        return {
            "report": "",
            "errors": state.get("errors", []) + [f"Report exception: {e}"],
        }
