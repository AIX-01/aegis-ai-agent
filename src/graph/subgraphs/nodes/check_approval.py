"""
Human-in-the-Loop 승인 관련 노드

emergency_call 도구 호출 시 사용자 승인을 요청하고 처리합니다.
- check_approval_node: 백엔드 API를 통해 승인 요청 및 대기
- skip_emergency_call_node: 거부/타임아웃 시 스킵 처리

[참고] approval_router는 edges/routers.py로 이동
"""
import logging
from typing import Dict, Any, TYPE_CHECKING

from langchain_core.messages import ToolMessage

if TYPE_CHECKING:
    from ....config import Config
    from ..state import ResponseAgentState

logger = logging.getLogger(__name__)


def check_approval_node(state: "ResponseAgentState", config: "Config") -> Dict[str, Any]:
    """
    emergency_call 도구 호출에 대해 백엔드 API를 통해 사용자 승인을 요청하고 대기하는 노드

    [역할]
    1. 마지막 메시지에서 emergency_call 도구 호출 정보 추출
    2. Action 생성 API 호출 → actionId 획득
       POST /internal/agent/events/{eventId}/actions
    3. 승인 확인 API 호출 → 사용자 응답 대기
       POST /internal/agent/events/{eventId}/actions/{actionId}/pending
    4. 승인 결과를 state에 저장

    [API 흐름]
    1) POST /internal/agent/events/{eventId}/actions
       Request:  { action, description }
       Response: { actionId }

    2) POST /internal/agent/events/{eventId}/actions/{actionId}/pending
       Request:  (없음)
       Response: { userId, userName, userMail, result }

    Args:
        state: 현재 에이전트 상태
        config: 시스템 설정

    Returns:
        업데이트된 상태 (pending_approval, approval_result)
    """
    from ....clients.backend_client import BackendClient

    messages = state.get("messages", [])
    if not messages:
        return {"approval_result": {"approved": False, "status": "no_messages"}}

    last_message = messages[-1]

    # emergency_call 도구 호출 정보 추출
    emergency_call_info = None
    if hasattr(last_message, "tool_calls"):
        for tool_call in last_message.tool_calls:
            if tool_call.get("name") == "emergency_call":
                emergency_call_info = {
                    "tool_call_id": tool_call.get("id"),
                    "agency_type": tool_call.get("args", {}).get("agency_type", ""),
                    "situation_report": tool_call.get("args", {}).get("situation_report", ""),
                }
                break

    if not emergency_call_info:
        logger.warning("[check_approval] emergency_call 도구 호출 정보 없음")
        return {"approval_result": {"approved": True, "status": "no_emergency_call"}}

    # 상태에서 필요한 정보 추출
    camera_id = state.get("camera_id", "")
    event_id = state.get("event_id", "")

    logger.info(f"[{camera_id}] emergency_call 승인 요청 시작: {emergency_call_info['agency_type']}")

    try:
        # 백엔드 클라이언트 생성
        backend_client = BackendClient(config)

        # =========================================
        # Step 1: Action 생성 → actionId 획득
        # POST /internal/agent/events/{eventId}/actions
        # =========================================
        action_id = backend_client.create_action(
            event_id=event_id,
            action=emergency_call_info["agency_type"],
            description=f"긴급 신고 요청: {emergency_call_info['situation_report'][:100]}",
        )

        if not action_id:
            logger.error(f"[{camera_id}] Action 생성 실패")
            return {
                "pending_approval": emergency_call_info,
                "approval_result": {
                    "approved": False,
                    "status": "error",
                    "user_id": None,
                    "user_name": None,
                    "user_mail": None,
                    "action_id": None,
                    "error": "Action 생성 실패",
                },
            }

        logger.info(f"[{camera_id}] Action 생성 완료: actionId={action_id}")

        # =========================================
        # Step 2: 승인 확인 → 사용자 응답 대기
        # POST /internal/agent/events/{eventId}/actions/{actionId}/pending
        # =========================================
        response = backend_client.confirm_action(
            event_id=event_id,
            action_id=action_id,
            timeout=None,  # 사용자 응답까지 무한 대기 (타임아웃 틀은 유지)
        )

        if response:
            # 백엔드 응답 파싱
            # {userId, userName, userMail, result}
            approved = response.get("result", False)
            user_id = response.get("userId")
            user_name = response.get("userName")
            user_mail = response.get("userMail")

            status = "approved" if approved else "rejected"

            result = {
                "approved": approved,
                "status": status,
                "user_id": user_id,
                "user_name": user_name,
                "user_mail": user_mail,
                "action_id": action_id,
            }

            logger.info(f"[{camera_id}] 승인 결과: {status} (user: {user_name})")
        else:
            # 백엔드 응답 실패 시 (타임아웃 처리 틀)
            result = {
                "approved": False,
                "status": "timeout",
                "user_id": None,
                "user_name": None,
                "user_mail": None,
                "action_id": action_id,
            }
            logger.warning(f"[{camera_id}] 승인 확인 응답 없음 (timeout)")

    except Exception as e:
        logger.error(f"[{camera_id}] 승인 요청 중 오류: {e}", exc_info=True)
        result = {
            "approved": False,
            "status": "error",
            "user_id": None,
            "user_name": None,
            "user_mail": None,
            "action_id": None,
            "error": str(e),
        }

    return {
        "pending_approval": emergency_call_info,
        "approval_result": result,
    }



def skip_emergency_call_node(state: "ResponseAgentState") -> Dict[str, Any]:
    """
    emergency_call 도구 호출을 스킵하고 ToolMessage를 생성합니다.

    LLM이 emergency_call을 호출했지만 사용자가 거부한 경우,
    emergency_call은 "사용자가 거부함" 메시지를 반환하고,
    다른 도구(field_action 등)는 직접 실행하여 결과를 반환합니다.

    [중요] OpenAI API는 모든 tool_call_id에 대한 ToolMessage가 있어야 합니다.
    emergency_call만 스킵하고 다른 도구 응답을 생성하지 않으면 오류가 발생합니다.

    Args:
        state: 현재 에이전트 상태

    Returns:
        업데이트된 상태 (messages에 모든 도구에 대한 응답 추가)
    """
    messages = state.get("messages", [])
    if not messages:
        return {}

    last_message = messages[-1]
    new_messages = []
    camera_id = state.get("camera_id", "")

    # 도구 호출 처리 - 모든 tool_call에 대해 ToolMessage 생성 필요
    if hasattr(last_message, "tool_calls"):
        for tool_call in last_message.tool_calls:
            tool_name = tool_call.get("name", "")
            tool_call_id = tool_call.get("id", "")
            tool_args = tool_call.get("args", {})

            if tool_name == "emergency_call":
                # emergency_call은 스킵 - 거부 메시지 생성
                approval_result = state.get("approval_result", {})
                status = approval_result.get("status", "rejected")

                if status == "timeout":
                    skip_message = "⏱️ 긴급 신고가 타임아웃되었습니다. 사용자 응답이 없어 신고가 진행되지 않았습니다."
                else:
                    skip_message = "❌ 긴급 신고가 사용자에 의해 거부되었습니다. 신고가 진행되지 않았습니다."

                new_messages.append(ToolMessage(
                    content=skip_message,
                    tool_call_id=tool_call_id,
                ))
                logger.info(f"[skip_emergency_call] emergency_call 스킵됨 (status: {status})")

            elif tool_name == "execute_field_action":
                # =========================================
                # field_action은 실제 로직을 호출하여 실행
                # =========================================
                # execute_field_action_impl: response_tools.py에서 분리된 실제 구현
                # 분리 이유: @tool 데코레이터 함수는 직접 호출이 어려움
                # emergency_call 거부 시에도 execute_field_action은 정상 실행되어야 함
                from ....tools.response_tools import execute_field_action_impl

                action_name = tool_args.get("action_name", tool_args.get("action", "UNKNOWN"))
                message_content = tool_args.get("message_content", tool_args.get("message", ""))
                # camera_id: tool_args에서 먼저 확인, 없으면 state에서 가져옴
                target_camera_id = tool_args.get("camera_id", camera_id)

                # 실제 execute_field_action 로직 실행
                result = execute_field_action_impl(
                    action_name=action_name,
                    camera_id=target_camera_id,
                    message_content=message_content
                )

                new_messages.append(ToolMessage(
                    content=result,
                    tool_call_id=tool_call_id,
                ))
                logger.info(f"[skip_emergency_call] execute_field_action 실제 실행: action={action_name}, camera={target_camera_id}")

            else:
                # 알 수 없는 도구 - 에러 메시지 (OpenAI API 요구사항 충족)
                new_messages.append(ToolMessage(
                    content=f"❌ 알 수 없는 도구: {tool_name}",
                    tool_call_id=tool_call_id,
                ))
                logger.warning(f"[skip_emergency_call] 알 수 없는 도구: {tool_name}")

    return {"messages": new_messages}

