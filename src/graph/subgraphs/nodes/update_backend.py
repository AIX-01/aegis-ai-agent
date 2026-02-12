"""
백엔드 갱신 노드 (update_backend)

보고서와 대응 조치를 백엔드에 갱신합니다.
"""
import logging
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ....config import Config
    from ..state import ResponseAgentState

logger = logging.getLogger(__name__)


def update_report_to_backend(state: "ResponseAgentState", app_config: "Config") -> Dict[str, Any]:
    """
    보고서와 대응 조치를 백엔드에 갱신합니다.

    Args:
        state: 현재 에이전트 상태
        app_config: 시스템 설정

    Returns:
        업데이트된 상태 (report_updated)
    """
    from ....clients.backend_client import BackendClient

    event_id = state.get("event_id", "")
    report = state.get("report", {})
    actions = state.get("actions", [])

    logger.info(f"[{event_id}] 보고서 백엔드 갱신 시작...")

    try:
        backend_client = BackendClient(app_config)

        # 보고서 및 조치 갱신 데이터
        update_data = {
            "report": report,  # Dict: {content, files, generated_at}
            "actions": actions,
        }

        success = backend_client.update_event(event_id, update_data)

        if success:
            logger.info(f"[{event_id}] 보고서 백엔드 갱신 성공")
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

