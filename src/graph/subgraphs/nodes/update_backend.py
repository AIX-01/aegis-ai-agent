"""
백엔드 갱신 노드 (update_backend)

보고서를 백엔드에 갱신하고 상태를 'analyzed'로 변경합니다.

[API 엔드포인트]
PATCH /internal/agent/events/{eventId}

[Request Body]
{
    "report": "상세 보고서 내용", (optional)
    "status": "analyzed" (optional)
}
"""
import logging
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ....config import Config
    from ..state import ResponseAgentState

logger = logging.getLogger(__name__)


def update_report_to_backend(state: "ResponseAgentState", app_config: "Config") -> Dict[str, Any]:
    """
    보고서를 백엔드에 갱신하고 상태를 'analyzed'로 변경합니다.

    Args:
        state: 현재 에이전트 상태
        app_config: 시스템 설정

    Returns:
        업데이트된 상태 (report_updated)
    """
    from ....clients.backend_client import BackendClient

    event_id = state.get("event_id", "")
    report = state.get("report", "")  # 보고서 내용 (문자열)

    logger.info(f"[{event_id}] 보고서 백엔드 갱신 시작...")

    try:
        backend_client = BackendClient(app_config)

        # 보고서 갱신 데이터 (새 API 스펙에 맞게 report는 문자열, status는 analyzed)
        update_data = {
            "report": report,      # 보고서 내용 (문자열)
            "status": "analyzed",  # 분석 완료 상태로 변경
        }

        success = backend_client.update_event(event_id, update_data)

        if success:
            logger.info(f"[{event_id}] 보고서 백엔드 갱신 성공 (status: analyzed)")
            return {"report_updated": True}
        else:
            logger.error(f"[{event_id}] 보고서 백엔드 갱신 실패")
            return {"report_updated": False}

    except Exception as e:
        logger.error(f"[{event_id}] 보고서 백엔드 갱신 중 오류: {e}", exc_info=True)
        return {
            "report_updated": False,
            "errors": state.get("errors", []) + [f"Update report to backend exception: {e}"]
        }

