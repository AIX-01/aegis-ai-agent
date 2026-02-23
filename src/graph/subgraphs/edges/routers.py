"""
서브그래프 라우터 함수 모듈

조건부 엣지에서 사용하는 라우터 함수들을 정의합니다.
- should_continue: agent 노드 후 분기 결정
- approval_router: check_approval 노드 후 분기 결정
"""
import logging
from typing import Literal

# [중요] LangGraph가 add_conditional_edges()에서 get_type_hints()를 호출하여
# 라우터 함수의 타입 힌트를 평가합니다. TYPE_CHECKING 블록 안에서만 import하면
# 런타임에 NameError가 발생하므로, 반드시 런타임에도 import해야 합니다.
from ..state import ResponseAgentState

logger = logging.getLogger(__name__)


def should_continue(state: ResponseAgentState) -> Literal["tools", "check_approval", "report", "end"]:
    """
    에이전트가 다음에 어디로 갈지 결정합니다.

    [라우팅 로직]
    - emergency_call 도구 호출 포함 → "check_approval" (승인 대기)
    - field_action 도구만 호출 → "tools" (바로 실행)
    - 도구 호출 없음 → "report" (보고서 생성)

    Args:
        state: 현재 에이전트 상태

    Returns:
        다음 노드 이름 ("tools" | "check_approval" | "report" | "end")
    """
    messages = state.get("messages", [])
    iteration = state.get("iteration", 0)

    # 최대 반복 횟수 제한 (무한 루프 방지)
    if iteration >= 5:
        logger.warning("에이전트 최대 반복 횟수 도달")
        return "report"

    if not messages:
        return "end"

    last_message = messages[-1]

    # 도구 호출이 있는지 확인
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        # emergency_call 도구가 포함되어 있는지 확인
        for tool_call in last_message.tool_calls:
            if tool_call.get("name") == "emergency_call":
                # emergency_call이 있으면 승인 확인 노드로
                logger.info("[should_continue] emergency_call 감지 → 승인 확인 필요")
                return "check_approval"

        # emergency_call이 없으면 바로 도구 실행
        return "tools"

    # 도구 호출이 없으면 보고서 생성으로
    return "report"


def approval_router(state: ResponseAgentState) -> Literal["tools", "skip_emergency"]:
    """
    승인 결과에 따라 다음 노드를 결정합니다.

    - 승인됨 → "tools" (emergency_call 포함 모든 도구 실행)
    - 거부/타임아웃 → "skip_emergency" (emergency_call만 스킵)

    Args:
        state: 현재 에이전트 상태

    Returns:
        다음 노드 이름 ("tools" | "skip_emergency")
    """
    approval_result = state.get("approval_result", {})
    approved = approval_result.get("approved", False)

    if approved:
        logger.info("[approval_router] 승인됨 → 도구 실행")
        return "tools"
    else:
        logger.info(f"[approval_router] 거부/타임아웃 → emergency_call 스킵 (status: {approval_result.get('status')})")
        return "skip_emergency"

