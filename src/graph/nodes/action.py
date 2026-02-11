"""
대응 조치(Action) 결정 노드 - LangGraph ReAct Agent

분석 결과를 바탕으로 적절한 대응 조치를 결정하고 실행합니다.
- 기본 도구: 매뉴얼 RAG 검색
- 동적 도구: Redis에서 가져온 액션 코드
"""
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, TYPE_CHECKING

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from ..state import AnalysisState
from ...tools import search_manual, set_vector_client, create_dynamic_tools

if TYPE_CHECKING:
    from ...config import Config
    from ...clients.vector_store_client import VectorStoreClient
    from ...clients.backend_client import BackendClient
    from ...core.redis_manager import RedisManager

logger = logging.getLogger(__name__)

# 전역 참조 (analysis_graph.py에서 주입)
_config: Optional["Config"] = None
_vector_client: Optional["VectorStoreClient"] = None
_redis_manager: Optional["RedisManager"] = None
_backend_client: Optional["BackendClient"] = None


def set_action_dependencies(
    config: "Config",
    vector_client: "VectorStoreClient",
    redis_manager: "RedisManager",
    backend_client: "BackendClient" = None
):
    """action_node에서 사용할 의존성을 설정합니다."""
    global _config, _vector_client, _redis_manager, _backend_client
    _config = config
    _vector_client = vector_client
    _redis_manager = redis_manager
    _backend_client = backend_client

    # 매뉴얼 검색 도구에 VectorStoreClient 주입
    set_vector_client(vector_client)


def action_node(state: AnalysisState) -> Dict[str, Any]:
    """
    정밀 분석 결과를 바탕으로 대응 조치(Action)를 결정하는 노드

    LangGraph ReAct Agent를 사용하여:
    1. 상황에 맞는 매뉴얼 검색 (RAG)
    2. 적절한 액션 도구 호출 (동적 생성)

    Args:
        state: 현재 분석 상태

    Returns:
        업데이트된 상태 딕셔너리 (actions, rag_references)
    """
    camera_id = state["camera_id"]
    camera_name = state.get("camera_name", "unknown")
    camera_location = state.get("camera_location", "unknown")
    risk_level = state.get("risk_level", "UNKNOWN")
    event_type = state.get("event_type", "UNKNOWN")
    summary = state.get("summary", "")

    logger.info(f"[{camera_id}] 대응 조치(Action) Agent 시작...")
    logger.info(f"  - 위험도: {risk_level}, 유형: {event_type}")
    logger.info(f"  - 요약: {summary[:100]}..." if len(summary) > 100 else f"  - 요약: {summary}")

    if _config is None or _vector_client is None or _redis_manager is None:
        logger.error("action_node 의존성이 설정되지 않았습니다.")
        return {"errors": state.get("errors", []) + ["Action node dependencies not set"]}

    try:
        # 1. 도구 목록 구성
        tools = _build_tools()

        if not tools:
            logger.warning(f"[{camera_id}] 사용 가능한 도구가 없습니다.")
            return {"actions": [], "rag_references": []}

        logger.info(f"[{camera_id}] 사용 가능한 도구: {[t.name for t in tools]}")

        # 2. ReAct Agent 생성
        llm = ChatOpenAI(
            model=_config.openai_chat_model,
            api_key=_config.openai_api_key,
            temperature=0.1
        )

        agent = create_react_agent(llm, tools)

        # 3. Agent 프롬프트 구성
        prompt = _build_agent_prompt(
            camera_name=camera_name,
            camera_location=camera_location,
            risk_level=risk_level,
            event_type=event_type,
            summary=summary
        )

        # 4. Agent 실행
        logger.info(f"[{camera_id}] ReAct Agent 실행 중...")
        result = agent.invoke({"messages": [("user", prompt)]})

        # 5. 결과 파싱
        actions_taken, rag_refs = _parse_agent_result(result)

        logger.info(f"[{camera_id}] 대응 조치 완료: {len(actions_taken)}건의 조치 실행됨")
        for action in actions_taken:
            logger.info(f"  - {action.get('tool', 'unknown')}: {action.get('result', '')[:50]}...")

        # 6. 실행된 액션을 백엔드에 기록
        event_id = state.get("event_id")
        if event_id and _backend_client:
            _record_actions_to_backend(event_id, actions_taken)

        return {
            "actions": actions_taken,
            "rag_references": rag_refs
        }

    except Exception as e:
        logger.error(f"[{camera_id}] Action Agent 실행 중 오류: {e}", exc_info=True)
        return {"errors": state.get("errors", []) + [f"Action agent error: {e}"]}


def _build_tools() -> List:
    """기본 도구 + 동적 도구 목록을 구성합니다."""
    tools = []

    # 기본 도구: 매뉴얼 검색
    tools.append(search_manual)

    # 동적 도구: Redis에서 액션 목록 가져와서 Tool로 변환
    if _redis_manager:
        actions = _redis_manager.get_actions()
        dynamic_tools = create_dynamic_tools(actions)
        tools.extend(dynamic_tools)

    return tools


def _build_agent_prompt(
    camera_name: str,
    camera_location: str,
    risk_level: str,
    event_type: str,
    summary: str
) -> str:
    """Agent에게 전달할 프롬프트를 생성합니다."""
    return f"""당신은 보안 관제 시스템의 대응 조치 담당자입니다.

## 상황 정보
- 카메라: {camera_name} ({camera_location})
- 위험도: {risk_level}
- 이벤트 유형: {event_type}
- 상황 요약: {summary}

## 지시사항
1. 먼저 search_manual 도구를 사용하여 이 상황에 적합한 대응 매뉴얼을 검색하세요.
2. 매뉴얼 내용을 참고하여 상황에 맞는 대응 조치를 실행하세요.
3. 사용 가능한 다른 도구들(메일 발송, 문자 발송 등)이 있다면 적절히 활용하세요.
4. 모든 조치가 완료되면 수행한 조치들을 요약해주세요.

주의: 상황의 심각도({risk_level})에 맞게 적절한 수준의 조치를 취하세요.
"""


def _parse_agent_result(result: Dict[str, Any]) -> tuple:
    """
    Agent 실행 결과를 파싱합니다.

    Returns:
        (actions_taken, rag_references) 튜플
    """
    actions_taken = []
    rag_references = []

    messages = result.get("messages", [])

    for msg in messages:
        # ToolMessage인 경우 도구 호출 결과
        if hasattr(msg, "name") and hasattr(msg, "content"):
            tool_name = getattr(msg, "name", "unknown")
            tool_result = getattr(msg, "content", "")

            actions_taken.append({
                "tool": tool_name,
                "result": tool_result
            })

            # 매뉴얼 검색 결과는 RAG 참조로 저장
            if tool_name == "search_manual" and tool_result:
                rag_references.append({
                    "source": "manual",
                    "content": tool_result
                })

    return actions_taken, rag_references


def _record_actions_to_backend(event_id: str, actions_taken: List[Dict[str, Any]]):
    """
    실행된 액션들을 백엔드에 기록합니다.

    Args:
        event_id: 이벤트 ID
        actions_taken: 실행된 액션 목록
    """
    if not _backend_client:
        return

    for action in actions_taken:
        tool_name = action.get("tool", "unknown")
        result = action.get("result", "")

        # search_manual은 조회용이므로 기록하지 않음
        if tool_name == "search_manual":
            continue

        # tool_name이 None인 경우 스킵 (AI 응답 메시지)
        if tool_name is None or tool_name == "unknown":
            continue

        # action_{uuid} 형식에서 action_id 추출
        action_id = None
        if tool_name.startswith("action_"):
            action_id = tool_name.replace("action_", "")

        try:
            _backend_client.record_event_action(
                event_id=event_id,
                action_id=action_id,
                input_params={"tool_name": tool_name},
                output_result=result[:1000] if len(result) > 1000 else result,
                success="오류" not in result and "error" not in result.lower(),
                executed_at=datetime.now().isoformat()
            )
        except Exception as e:
            logger.error(f"액션 기록 실패: {tool_name} - {e}")
