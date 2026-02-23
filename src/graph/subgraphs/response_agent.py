"""
대응 조치 및 보고서 생성을 담당하는 ReAct Agent 서브그래프

이 서브그래프는 verification_router에서 ABNORMAL로 판정된 후 실행됩니다.
지식 검색(매뉴얼/과거 사례)을 먼저 수행한 후, LLM이 도구를 선택하여
대응 조치를 결정하고 최종 보고서를 생성합니다.

[워크플로우]
START → search_knowledge → agent (ReAct) → tools → ... → extract_actions → generate_report → update_backend → END

[폴더 구조]
- nodes/: 노드 함수들
  - search_knowledge.py: 지식 검색 노드
  - agent.py: LLM 에이전트 노드 + 시스템 프롬프트
  - check_approval.py: HITL 승인 관련 노드
  - extract_actions.py: 조치 정보 추출 노드
  - generate_report.py: 보고서 생성 노드
  - update_backend.py: 백엔드 갱신 노드
- edges/: 라우터 함수들
  - routers.py: should_continue, approval_router
"""
import functools
import logging
from datetime import datetime
from typing import Dict, Any

from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode

from ..state import AnalysisState
from ...config import Config
from ...tools.response_tools import create_response_tools

# 서브그래프 상태 import
from .state import ResponseAgentState

# 노드 함수들 import
from .nodes import (
    search_knowledge_node,
    create_agent_node,
    increment_iteration,
    check_approval_node,
    skip_emergency_call_node,
    extract_actions,
    generate_report_node,
    update_report_to_backend,
)

# 라우터 함수들 import (edges 폴더)
from .edges import should_continue, approval_router

logger = logging.getLogger(__name__)


# =========================================
# 도구 정의
# =========================================
def create_tools(config: Config):
    """
    에이전트가 사용할 도구들을 생성합니다.

    도구들은 src/tools/response_tools.py에 정의되어 있습니다:
    - execute_field_action: 현장 물리적 조치 실행 (방송, 조명, PTZ, 사이렌)
    - emergency_call: 긴급 신고 접수 (112, 119, 보안팀)

    Args:
        config: Config 인스턴스

    Returns:
        LangChain 도구 리스트
    """
    return create_response_tools(config)


# =========================================
# 서브그래프 빌더
# =========================================
def build_response_agent(config: Config) -> StateGraph:
    """
    대응 에이전트 서브그래프를 빌드합니다.

    [워크플로우 - Human-in-the-Loop 포함]
    START → search_knowledge → agent (ReAct)
                                    ↓
                             should_continue
                    ┌───────────────┼───────────────┐
                    ↓               ↓               ↓
            (field_action만)  (emergency_call)  (도구 없음)
                 tools       check_approval     extract_actions
                    ↓               ↓               ↓
              increment      approval_router   generate_report
                    ↓         ↓         ↓           ↓
                 agent     tools   skip_emergency  update_backend
                             ↓         ↓               ↓
                         increment  increment         END
                             ↓         ↓
                           agent     agent

    Args:
        config: 시스템 설정

    Returns:
        컴파일된 서브그래프
    """
    # 도구 생성
    tools = create_tools(config)

    # 에이전트 노드 생성
    agent_node = create_agent_node(config, tools)

    # 도구 노드 생성
    tool_node = ToolNode(tools)

    # 지식 검색 노드에 config 바인딩
    search_knowledge = functools.partial(search_knowledge_node, config=config)

    # 백엔드 갱신 노드에 app_config 바인딩
    update_backend = functools.partial(update_report_to_backend, app_config=config)

    # 보고서 생성 노드에 app_config 바인딩
    generate_report = functools.partial(generate_report_node, app_config=config)

    # Human-in-the-Loop 승인 확인 노드에 config 바인딩
    check_approval = functools.partial(check_approval_node, config=config)

    # extract_actions 노드에 config 바인딩
    extract_actions_with_config = functools.partial(extract_actions, config=config)

    # 그래프 빌더
    workflow = StateGraph(ResponseAgentState)

    # 노드 추가
    workflow.add_node("search_knowledge", search_knowledge)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("increment", increment_iteration)
    workflow.add_node("extract_actions", extract_actions_with_config)
    workflow.add_node("generate_report", generate_report)
    workflow.add_node("update_backend", update_backend)

    # Human-in-the-Loop 노드 추가
    workflow.add_node("check_approval", check_approval)
    workflow.add_node("skip_emergency", skip_emergency_call_node)

    # =========================================
    # 엣지 설정
    # =========================================
    workflow.add_edge(START, "search_knowledge")
    workflow.add_edge("search_knowledge", "agent")

    # agent → should_continue 조건부 엣지
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "check_approval": "check_approval",
            "report": "extract_actions",
            "end": END
        }
    )

    # check_approval → approval_router 조건부 엣지
    workflow.add_conditional_edges(
        "check_approval",
        approval_router,
        {
            "tools": "tools",
            "skip_emergency": "skip_emergency"
        }
    )

    # 일반 도구 실행 후 루프
    workflow.add_edge("tools", "increment")
    workflow.add_edge("increment", "agent")

    # emergency_call 스킵 후 루프
    workflow.add_edge("skip_emergency", "increment")

    # 보고서 생성 흐름
    workflow.add_edge("extract_actions", "generate_report")
    workflow.add_edge("generate_report", "update_backend")
    workflow.add_edge("update_backend", END)

    return workflow.compile()


def response_agent_node(state: AnalysisState, config: Config) -> Dict[str, Any]:
    """
    메인 그래프에서 호출되는 대응 에이전트 노드입니다.

    AnalysisState를 ResponseAgentState로 변환하여 서브그래프를 실행하고,
    결과를 다시 AnalysisState 형식으로 반환합니다.

    Args:
        state: 메인 그래프 상태 (AnalysisState)
        config: 시스템 설정

    Returns:
        업데이트된 상태 (actions, rag_references, report, report_updated)
    """
    camera_id = state.get("camera_id", "")
    logger.info(f"[{camera_id}] 대응 에이전트 시작...")

    try:
        # 서브그래프 빌드
        agent = build_response_agent(config)

        # 상태 변환 (AnalysisState → ResponseAgentState)
        agent_state: ResponseAgentState = {
            "camera_id": camera_id,
            "camera_name": state.get("camera_name", ""),
            "camera_location": state.get("camera_location", ""),
            "event_id": state.get("event_id", ""),
            "event_type": state.get("event_type", ""),
            "risk_level": state.get("risk_level", "ABNORMAL"),
            "risk_score": state.get("risk_score", 0.0),
            "summary": state.get("summary", ""),
            "occurred_at": state.get("occurred_at"),
            "frames": state.get("frames", []),  # [추가] 보고서 이미지용
            "frame_timestamps": state.get("frame_timestamps", []),  # [추가] 타임스탬프
            "messages": [],
            "actions": [],
            "rag_references": [],
            "knowledge_context": "",
            "reasoning": "",  # LLM 판단 근거
            "report": "",     # HTML 보고서 문자열
            "report_updated": False,
            "iteration": 0,
            "errors": [],
            "pending_approval": {},
            "approval_result": {},
        }

        # 에이전트 실행
        result = agent.invoke(agent_state)

        logger.info(f"[{camera_id}] 대응 에이전트 완료: {len(result.get('actions', []))}개 조치 결정")

        return {
            "actions": result.get("actions", []),
            "rag_references": result.get("rag_references", []),
            "report": result.get("report", ""),
            "report_updated": result.get("report_updated", False)
        }

    except Exception as e:
        logger.error(f"[{camera_id}] 대응 에이전트 실행 실패: {e}", exc_info=True)
        return {
            "actions": [],
            "rag_references": [],
            "report": f"<html><body><h1>보고서 생성 실패</h1><p>{e}</p></body></html>",
            "report_updated": False,
            "errors": state.get("errors", []) + [f"Response agent exception: {e}"]
        }

