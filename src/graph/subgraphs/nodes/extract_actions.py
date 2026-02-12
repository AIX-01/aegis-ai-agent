"""
조치 정보 추출 노드 (extract_actions)

메시지에서 결정된 조치들과 참조 문서를 추출합니다.
emergency_call 도구 실행 후 백엔드에 update_action API를 호출합니다.
"""
import re
import logging
from typing import Dict, Any, TYPE_CHECKING

from langchain_core.messages import ToolMessage

if TYPE_CHECKING:
    from ....config import Config
    from ..state import ResponseAgentState

logger = logging.getLogger(__name__)

# agency_type을 action 코드로 변환하는 매핑
# (response_tools.py의 emergency_call 도구에서 사용하는 코드와 일치)
AGENCY_TO_ACTION = {
    "경찰청 112": "112_POLICE",
    "소방청 119": "119_FIRE",
    "내부 보안팀": "SECURITY_TEAM",
    "관리사무소": "MANAGEMENT",
}


def extract_actions(state: "ResponseAgentState", config: "Config") -> Dict[str, Any]:
    """
    메시지에서 결정된 조치들과 참조 문서를 추출합니다.
    emergency_call 도구 실행 후 백엔드에 update_action API를 호출합니다.

    [추출 정보 - 백엔드 event_actions 테이블과 일치]
    - action: TEXT - 조치 유형/코드 ("BROADCAST", "112_POLICE" 등)
    - description: TEXT - 조치에 대한 상세 설명
    - user_id: UUID | None - HITL 승인자 ID (시스템 자동 시 None)

    [액션 코드 매핑]
    - field_action: BROADCAST, LIGHT_ON, PTZ_TRACK, SIREN
    - emergency_call (승인): 112_POLICE, 119_FIRE, SECURITY_TEAM, MANAGEMENT
    - emergency_call (거절): REJECTED_112_POLICE, REJECTED_119_FIRE, ...

    [백엔드 갱신]
    - emergency_call 도구 실행 후 PATCH /internal/agent/events/{eventId}/actions/{actionId} 호출

    Args:
        state: 현재 에이전트 상태
        config: 시스템 설정

    Returns:
        업데이트된 상태 (actions, rag_references)
    """
    from ....clients.backend_client import BackendClient

    actions = []
    rag_references = []

    # Human-in-the-Loop 승인 정보 확인
    # 백엔드 API 응답 구조:
    # {
    #     "approved": bool,
    #     "status": "approved" | "rejected" | "timeout",
    #     "user_id": str | None,    # userId
    #     "user_name": str | None,  # userName
    #     "user_mail": str | None,  # userMail
    #     "action_id": str | None   # 백엔드에서 생성된 action ID
    # }
    approval_result = state.get("approval_result", {})
    approval_user_id = approval_result.get("user_id")      # HITL 승인/거절자 ID
    approval_user_name = approval_result.get("user_name")  # HITL 승인/거절자 이름
    approval_user_mail = approval_result.get("user_mail")  # HITL 승인/거절자 이메일
    approval_action_id = approval_result.get("action_id")  # 백엔드에서 생성된 action ID

    # 이벤트 ID (백엔드 갱신에 필요)
    event_id = state.get("event_id", "")

    for message in state.get("messages", []):
        if isinstance(message, ToolMessage):
            content = message.content

            # search_protocol_and_cases 결과 → rag_references
            if "대응 매뉴얼" in content or "과거 유사 사례" in content:
                rag_references.append({
                    "type": "protocol_and_cases",
                    "content": content[:1000]
                })

            # execute_field_action 결과 → actions
            # field_action은 자동 실행이므로 user_id = None
            elif "현장 조치 실행 결과" in content:
                action_data = _extract_field_action(content)
                if action_data:
                    actions.append(action_data)

            # emergency_call 결과 → actions + 백엔드 갱신
            # emergency_call은 HITL 승인이 필요하므로 user_id 포함 가능
            elif "긴급 신고 접수 결과" in content:
                action_data = _extract_emergency_call_approved(
                    content, approval_user_id, approval_user_name, approval_user_mail
                )
                if action_data:
                    actions.append(action_data)
                    # 백엔드 갱신
                    _update_backend_action(
                        config, event_id, approval_action_id,
                        action_data["action"], action_data["description"], approval_user_id
                    )

            # emergency_call 거절 결과 → actions + 백엔드 갱신
            elif "긴급 신고가 사용자에 의해 거부되었습니다" in content:
                action_data = _extract_emergency_call_rejected(
                    state, approval_user_id, approval_user_name, approval_user_mail
                )
                if action_data:
                    actions.append(action_data)
                    _update_backend_action(
                        config, event_id, approval_action_id,
                        action_data["action"], action_data["description"], approval_user_id
                    )

            # emergency_call 타임아웃 결과 → actions + 백엔드 갱신
            elif "긴급 신고가 타임아웃되었습니다" in content:
                action_data = _extract_emergency_call_timeout(state)
                if action_data:
                    actions.append(action_data)
                    _update_backend_action(
                        config, event_id, approval_action_id,
                        action_data["action"], action_data["description"], None
                    )

    return {"actions": actions, "rag_references": rag_references}


def _extract_field_action(content: str) -> Dict[str, Any]:
    """execute_field_action 결과에서 action 정보 추출"""
    # action 코드 추출 (BROADCAST, LIGHT_ON, PTZ_TRACK, SIREN)
    action_code = None
    action_match = re.search(r"- 액션:\s*(\w+)", content)
    if action_match:
        action_code = action_match.group(1)

    # 카메라 ID 추출
    camera_match = re.search(r"- 대상 카메라:\s*(.+)", content)
    camera_id = camera_match.group(1).strip() if camera_match else ""

    # 방송 메시지 추출 (BROADCAST인 경우)
    message_match = re.search(r'- 방송 내용:\s*"(.+)"', content)
    broadcast_msg = message_match.group(1) if message_match else ""

    # 실행 시각 추출
    time_match = re.search(r"- 실행 시각:\s*(.+)", content)
    triggered_at = time_match.group(1).strip() if time_match else ""

    # description 조립
    if action_code == "BROADCAST" and broadcast_msg:
        description = f"[{action_code}] 카메라 {camera_id}에서 방송 실행: \"{broadcast_msg}\" (실행 시각: {triggered_at})"
    else:
        description = f"[{action_code}] 카메라 {camera_id}에서 현장 조치 실행 (실행 시각: {triggered_at})"

    return {
        "action": action_code,
        "description": description,
        "user_id": None  # field_action은 자동 실행 (HITL 미적용)
    }


def _extract_emergency_call_approved(
    content: str,
    user_id: str,
    user_name: str,
    user_mail: str
) -> Dict[str, Any]:
    """emergency_call 승인 결과에서 action 정보 추출"""
    # agency 추출 후 action 코드로 변환
    action_code = None
    agency_name = ""
    agency_match = re.search(r"- 신고 기관:\s*(.+)", content)
    if agency_match:
        agency_name = agency_match.group(1).strip()
        action_code = AGENCY_TO_ACTION.get(agency_name, agency_name)

    # 접수 번호 추출
    receipt_match = re.search(r"- 접수 번호:\s*(.+)", content)
    receipt_no = receipt_match.group(1).strip() if receipt_match else ""

    # 접수 시각 추출
    time_match = re.search(r"- 접수 시각:\s*(.+)", content)
    triggered_at = time_match.group(1).strip() if time_match else ""

    # 전달 내용 요약 추출
    report_match = re.search(r"### 전달 내용\n(.+?)(?:\n###|\Z)", content, re.DOTALL)
    situation_summary = report_match.group(1).strip()[:100] if report_match else ""

    # 승인자 정보 조립
    approver_info = ""
    if user_name:
        approver_info = f"승인자: {user_name}"
        if user_mail:
            approver_info += f" ({user_mail})"

    # description 조립
    description = f"[APPROVED] {agency_name} 긴급 신고 접수"
    if approver_info:
        description += f" | {approver_info}"
    description += f" (접수번호: {receipt_no}, 접수 시각: {triggered_at})"
    if situation_summary:
        description += f" - 상황: {situation_summary}"

    return {
        "action": action_code,
        "description": description,
        "user_id": user_id
    }


def _extract_emergency_call_rejected(
    state: "ResponseAgentState",
    user_id: str,
    user_name: str,
    user_mail: str
) -> Dict[str, Any]:
    """emergency_call 거절 결과에서 action 정보 추출"""
    pending_approval = state.get("pending_approval", {})
    pending_agency_type = pending_approval.get("agency_type", "")

    action_code = f"REJECTED_{pending_agency_type}" if pending_agency_type else "REJECTED_EMERGENCY"

    # 거절자 정보 조립
    rejecter_info = ""
    if user_name:
        rejecter_info = f"거절자: {user_name}"
        if user_mail:
            rejecter_info += f" ({user_mail})"

    description = f"[REJECTED] 긴급 신고 요청이 사용자에 의해 거부됨"
    if rejecter_info:
        description += f" | {rejecter_info}"

    return {
        "action": action_code,
        "description": description,
        "user_id": user_id
    }


def _extract_emergency_call_timeout(state: "ResponseAgentState") -> Dict[str, Any]:
    """emergency_call 타임아웃 결과에서 action 정보 추출"""
    pending_approval = state.get("pending_approval", {})
    pending_agency_type = pending_approval.get("agency_type", "")

    action_code = f"TIMEOUT_{pending_agency_type}" if pending_agency_type else "TIMEOUT_EMERGENCY"
    description = f"[TIMEOUT] 긴급 신고 요청에 대한 응답 타임아웃"

    return {
        "action": action_code,
        "description": description,
        "user_id": None
    }


def _update_backend_action(
    config: "Config",
    event_id: str,
    action_id: str,
    action: str,
    description: str,
    user_id: str
) -> None:
    """백엔드에 action 정보 갱신"""
    if not action_id or not event_id:
        return

    try:
        from ....clients.backend_client import BackendClient
        backend_client = BackendClient(config)
        backend_client.update_action(
            event_id=event_id,
            action_id=action_id,
            action=action,
            description=description,
            user_id=user_id,
        )
        logger.info(f"[{event_id}] action 결과 백엔드 갱신 완료 (actionId: {action_id})")
    except Exception as e:
        logger.error(f"[{event_id}] action 결과 백엔드 갱신 실패: {e}")

