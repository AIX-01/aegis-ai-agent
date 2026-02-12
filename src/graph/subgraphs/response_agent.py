"""
대응 조치 및 보고서 생성을 담당하는 ReAct Agent 서브그래프

이 서브그래프는 verification_router에서 ABNORMAL로 판정된 후 실행됩니다.
지식 검색(매뉴얼/과거 사례)을 먼저 수행한 후, LLM이 도구를 선택하여
대응 조치를 결정하고 최종 보고서를 생성합니다.

[워크플로우]
START → search_knowledge → agent (ReAct) → tools → ... → extract_actions → generate_report → update_backend → END

[노드 설명]
- search_knowledge: 대응 매뉴얼 및 과거 유사 사례 검색 (무조건 실행)
- agent: LLM이 검색 결과를 참조하여 대응 결정
- tools: execute_field_action, emergency_call 실행
- extract_actions: 메시지에서 조치 정보 추출
- generate_report: 보고서 생성 및 업로드
- update_backend: 백엔드에 보고서/조치 갱신

[도구]
- execute_field_action: 현장 물리적 조치 실행 (방송, 조명, PTZ, 사이렌)
- emergency_call: 긴급 신고 접수 (112, 119, 보안팀)

[변경사항 - 2026-02-11]
- search_protocol_and_cases 도구를 search_knowledge 노드로 분리
- 매뉴얼/과거 사례 검색이 무조건 실행되도록 보장
- LLM API 호출 횟수 감소 (비용/속도 최적화)
"""
import logging
from typing import Dict, Any, List, Annotated, TypedDict, Literal, Sequence
from datetime import datetime

from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ..state import AnalysisState
from ...config import Config
from ...tools.response_tools import create_response_tools

logger = logging.getLogger(__name__)


# =========================================
# 서브그래프 상태 정의
# =========================================
class ResponseAgentState(TypedDict):
    """
    대응 에이전트 서브그래프의 상태

    [필드 설명]
    - 부모 그래프에서 전달받는 정보: 카메라, 이벤트 정보
    - 에이전트 실행 중 생성: 메시지, 대응 조치, 보고서 등
    - knowledge_context: search_knowledge 노드에서 생성된 검색 결과 (LLM 프롬프트에 주입)
    """
    # 부모 그래프에서 전달받는 정보
    camera_id: str
    camera_name: str
    camera_location: str
    event_id: str
    event_type: str
    risk_level: str
    risk_score: float
    summary: str
    occurred_at: datetime
    frames: List[bytes]  # [추가] CCTV 캡처 이미지 (보고서 생성용)

    # 에이전트 실행 중 생성
    messages: Annotated[Sequence[BaseMessage], lambda x, y: x + y]
    # actions: 대응 조치 리스트 (백엔드 event_actions 테이블과 일치)
    # 형식: [{"action": str, "description": str, "user_id": str | None}, ...]
    actions: List[Dict[str, Any]]
    rag_references: List[Dict[str, Any]]  # 검색된 참조 문서들
    knowledge_context: str  # [추가] LLM에 주입할 검색 결과 텍스트 (매뉴얼 + 과거 사례)
    report: Dict[str, Any]  # 최종 보고서 {content, files, generated_at}
    report_updated: bool  # 백엔드 갱신 여부
    iteration: int  # 반복 횟수 (무한 루프 방지)
    errors: List[str]  # 에러 목록

    # Human-in-the-Loop 승인 관련
    # =========================================
    # 백엔드 API 경유 방식:
    # POST /internal/agent/events/{eventId}/actions/{actionId}/confirm
    #
    # Response Body:
    # {
    #     "userId": "uuid",        # 승인/거절한 사용자 ID
    #     "userName": "홍길동",     # 사용자 이름
    #     "userMail": "a@b.com",   # 사용자 이메일
    #     "result": true/false     # 승인 여부
    # }
    # =========================================
    pending_approval: Dict[str, Any]  # 승인 대기 중인 emergency_call 정보 (action, action_id 등)
    approval_result: Dict[str, Any]   # 백엔드 응답 결과
    # approval_result 형식:
    # {
    #     "approved": bool,        # result 값 (승인 여부)
    #     "status": str,           # "approved" | "rejected" | "timeout" | "pending"
    #     "user_id": str | None,   # userId (승인/거절자 ID)
    #     "user_name": str | None, # userName (승인/거절자 이름)
    #     "user_mail": str | None, # userMail (승인/거절자 이메일)
    #     "action_id": str | None, # 백엔드에서 생성된 action ID
    # }


# =========================================
# 도구 정의
# =========================================
def create_tools(config: Config):
    """
    에이전트가 사용할 도구들을 생성합니다.

    도구들은 src/tools/response_tools.py에 정의되어 있습니다:
    - execute_field_action: 현장 물리적 조치 실행 (방송, 조명, PTZ, 사이렌)
    - emergency_call: 긴급 신고 접수 (112, 119, 보안팀)

    [참고] search_protocol_and_cases는 search_knowledge 노드로 분리되어
    ReAct 루프 진입 전에 무조건 실행됩니다.

    Args:
        config: Config 인스턴스

    Returns:
        LangChain 도구 리스트
    """
    return create_response_tools(config)


# =========================================
# 지식 검색 노드 (search_knowledge)
# =========================================
def search_knowledge_node(state: ResponseAgentState, config: Config) -> Dict[str, Any]:
    """
    대응 매뉴얼과 과거 유사 사례를 검색하는 노드

    [역할]
    ReAct 루프 진입 전에 무조건 실행되어 LLM에게 필요한 지식 컨텍스트를 제공합니다.
    기존 search_protocol_and_cases 도구의 로직을 노드로 분리하여 실행을 보장합니다.

    [검색 대상]
    1. 과거 유사 사례 (Qdrant 벡터 검색)
    2. 대응 매뉴얼 (이벤트 유형별 하드코딩)

    Args:
        state: 현재 에이전트 상태
        config: 시스템 설정

    Returns:
        업데이트된 상태 (rag_references, knowledge_context 포함)
    """
    from ...tools.manual_templates import get_manual
    from ...clients.vector_store_client import VectorStoreClient

    # 상태에서 검색에 필요한 정보 추출
    summary = state.get("summary", "")
    event_type = state.get("event_type", "")
    camera_name = state.get("camera_name", "")
    camera_location = state.get("camera_location", "")
    camera_id = state.get("camera_id", "")

    logger.info(f"[{camera_id}] 지식 검색 노드 시작... (event_type: {event_type})")

    rag_references = []
    knowledge_text = ""

    # =========================================
    # 1. 검색 쿼리 구성
    # =========================================
    # 저장 시와 동일한 형식으로 쿼리를 구성하여 검색 정확도를 높임
    # - summary: 상황 요약 (우선순위 1)
    # - camera_name + camera_location: 위치 정보 (우선순위 2)
    # - event_type: 이벤트 유형 (우선순위 3)
    query_parts = []

    if summary:
        query_parts.append(f"상황: {summary}")
    if camera_name or camera_location:
        location_info = f"{camera_name} {camera_location}".strip()
        if location_info:
            query_parts.append(f"위치: {location_info}")
    if event_type:
        query_parts.append(f"유형: {event_type}")

    query = " | ".join(query_parts) if query_parts else summary

    # =========================================
    # 2. 과거 사례 검색 (Qdrant 벡터 유사도 검색)
    # =========================================
    try:
        client = VectorStoreClient(config)

        if client.collection_exists("past_cases"):
            past_results = client.search(
                collection_name="past_cases",
                query=query,
                limit=3,
                filters={"event_type": event_type} if event_type else None
            )

            if past_results:
                knowledge_text += "## 과거 유사 사례\n\n"
                for i, result in enumerate(past_results, 1):
                    payload = result.get("data", {})
                    score = result.get("score", 0)
                    knowledge_text += f"### 사례 {i} (유사도: {score:.2f})\n"
                    knowledge_text += f"- 카메라: {payload.get('camera_name', '')} ({payload.get('camera_location', '')})\n"
                    knowledge_text += f"- 이벤트: {payload.get('event_type', '')}\n"
                    knowledge_text += f"- 발생시각: {payload.get('occurred_at', '')}\n"

                    # =========================================
                    # [추가] 시간대/요일 패턴 표시
                    # =========================================
                    # LLM이 시간대 및 요일 패턴을 분석할 수 있도록 표시
                    hour = payload.get('hour_of_day')
                    day = payload.get('day_of_week')
                    day_names = ['월', '화', '수', '목', '금', '토', '일']
                    if hour is not None:
                        day_str = f" ({day_names[day]}요일)" if day is not None else ""
                        knowledge_text += f"- 발생 시간대: {hour}시{day_str}\n"

                    knowledge_text += f"- 상황: {payload.get('summary', '')}\n"

                    # =========================================
                    # [추가] 과거 대응 조치 표시 (event_actions 테이블 스키마와 일치)
                    # =========================================
                    # actions 필드가 있으면 LLM이 참조할 수 있도록 표시
                    # 형식: [{"action": "BROADCAST", "description": "...", "user_id": ...}, ...]
                    past_actions = payload.get('actions', [])
                    if past_actions:
                        knowledge_text += "- 대응조치:\n"
                        for action in past_actions:
                            action_code = action.get('action', 'unknown')
                            action_desc = action.get('description', '')
                            user_id = action.get('user_id')
                            # description이 너무 길면 첫 100자만 표시
                            if len(action_desc) > 100:
                                action_desc = action_desc[:100] + "..."
                            # HITL 승인 여부 표시
                            user_info = " (사용자 승인)" if user_id else ""
                            knowledge_text += f"  - [{action_code}] {action_desc}{user_info}\n"
                    knowledge_text += "\n"

                rag_references.append({
                    "type": "past_cases",
                    "content": knowledge_text,
                    "count": len(past_results)
                })
                logger.info(f"[{camera_id}] 과거 사례 {len(past_results)}건 검색 완료")
            else:
                knowledge_text += "## 과거 유사 사례\n검색 결과 없음\n\n"
                logger.info(f"[{camera_id}] 과거 사례 검색 결과 없음")
        else:
            knowledge_text += "## 과거 유사 사례\n컬렉션이 존재하지 않습니다.\n\n"
            logger.warning(f"[{camera_id}] past_cases 컬렉션 미존재")

    except Exception as e:
        logger.error(f"[{camera_id}] 과거 사례 검색 실패: {e}")
        knowledge_text += f"## 과거 유사 사례\n검색 실패: {e}\n\n"

    # =========================================
    # 3. 대응 매뉴얼 조회 (이벤트 유형별)
    # =========================================
    manual_text = get_manual(event_type)
    knowledge_text += "\n" + manual_text

    rag_references.append({
        "type": "manual",
        "content": manual_text
    })
    logger.info(f"[{camera_id}] 대응 매뉴얼 조회 완료 (event_type: {event_type})")

    return {
        "rag_references": rag_references,
        "knowledge_context": knowledge_text
    }


# =========================================
# 에이전트 노드
# =========================================
def create_agent_node(config: Config, tools: list):
    """에이전트 노드를 생성합니다."""

    # LLM 초기화
    llm = ChatOpenAI(
        model=config.openai_chat_model,
        api_key=config.openai_api_key,
        temperature=0.3
    ).bind_tools(tools)

    # =========================================
    # 시스템 프롬프트 (수정됨)
    # =========================================
    # search_protocol_and_cases 도구가 search_knowledge 노드로 분리됨
    # LLM은 이미 검색된 결과를 참조하여 대응 결정만 수행
    system_prompt = """당신은 CCTV 이상 감지 시스템의 대응 전문가입니다.

    ## 역할
    이상 상황이 감지되면 적절한 대응 조치를 결정하고 실행합니다.
    
    ## 사용 가능한 도구
    1. **execute_field_action**: 현장 물리적 조치 (방송, 조명, PTZ, 사이렌)
       - action_name: BROADCAST, LIGHT_ON, PTZ_TRACK, SIREN
       - camera_id: 대상 카메라 ID
       - message_content: 방송 메시지 (BROADCAST 시 필수)
    2. **emergency_call**: 긴급 신고 (112, 119, 보안팀)
       - agency_type: POLICE_112, FIRE_119, SECURITY_TEAM
       - situation_report: 상황 설명
    
    ## 참고 정보
    대응 매뉴얼과 과거 유사 사례는 이미 검색되어 아래에 제공됩니다.
    이 정보를 참고하여 적절한 조치를 결정하세요.
    
    ## 프로세스
    1. 상황 분석: 제공된 이벤트 정보와 참조 정보를 분석합니다.
    2. 현장 조치: execute_field_action으로 필요한 현장 조치를 실행합니다.
    3. 긴급 신고: 필요시 emergency_call로 112/119/보안팀에 신고합니다.
    4. 완료: 모든 필요한 조치를 완료했으면 종료합니다.
    
    ## 대응 기준
    - SWOON (실신): 즉시 119 신고, 현장 방송으로 주변에 알림
    - ASSAULT (폭행): 112 신고 + 보안팀 출동, 현장 방송/사이렌
    - BURGLARY (절도): 112 신고 + 보안팀 출동, PTZ 추적
    - VANDALISM (기물파손): 보안팀 출동, 현장 방송
    - DUMP (무단투기): 현장 방송으로 경고, 기록 보존
    
    ## 복합 상황 대응 (LLM 판단)
    상황 요약(summary)을 분석하여 복합적인 대응이 필요한 경우를 판단하세요:
    - 폭행(ASSAULT) 중 부상자/실신자 발생: 112 + 119 동시 신고
    - 절도(BURGLARY) 중 폭행 발생: 112 신고 + PTZ 추적 + 현장 방송
    - 기물파손(VANDALISM) 중 부상자 발생: 112 + 119 동시 신고
    
    ※ 이벤트 유형(event_type)만 보지 말고, 상황 요약(summary)의 세부 내용을 
      분석하여 인명 피해 가능성이 있으면 119를 반드시 포함하세요.
    
    ## 주의사항
    - 상황 심각도에 따라 적절한 도구를 선택하세요.
    - 인명 관련 사건(SWOON, ASSAULT)은 반드시 긴급 신고를 수행하세요.
    - 현장 조치와 신고를 병행할 수 있습니다.
    - 참조 정보(매뉴얼, 과거 사례)를 반드시 확인하고 결정하세요.
    
    ## 응답 형식 (중요)
    도구를 호출하기 전에 반드시 다음 형식으로 판단 근거를 설명하세요:
    
    ```
    ### 과거 사례 분석
    - 유사 사례: [N]건 발견
    - 과거 대응 조치: [조치명] [N]회 ([비율]%)
    - 시간대 패턴: [N]시~[N]시에 [N]건 발생
    - 요일 패턴: [요일]에 [N]건 발생
    - 장소 패턴: [장소명]에서 반복 발생 여부
    
    ### 판단 근거
    [과거 사례와 매뉴얼을 참고하여 선택 이유 1~2문장으로 설명]
    
    ### 선택한 조치
    1. [조치명] - [이유]
    2. [조치명] - [이유] (있는 경우)
    ```
    
    ### 과거 사례가 있는 경우 예시:
    ```
    ### 과거 사례 분석
    - 유사 사례: 3건 발견
    - 과거 대응 조치: 현장 방송 경고 2회 (67%), 영상 보존만 1회 (33%)
    - 시간대 패턴: 22시~02시에 3건 발생 (야간 집중)
    - 요일 패턴: 월요일 2건, 토요일 1건
    - 장소 패턴: 후문 CCTV에서 반복 발생 중
    
    ### 판단 근거
    과거 사례에서 현장 방송 경고가 67% 사용되었고, 매뉴얼에서도 DUMP 상황에서 현장 방송을 권장합니다.
    야간 시간대(22시~02시)에 집중 발생하므로 즉각 대응이 필요합니다.
    
    ### 선택한 조치
    1. 현장 방송 경고 - 무단투기 중단 및 경고 메시지 전달
    ```
    
    ### 과거 사례가 없는 경우 예시:
    ```
    ### 과거 사례 분석
    - 유사 사례: 0건 (과거 사례 없음)
    - 참고: 대응 매뉴얼 기준으로 판단
    
    ### 판단 근거
    과거 유사 사례가 없어 대응 매뉴얼을 기준으로 판단합니다.
    DUMP(무단투기) 매뉴얼에 따라 현장 방송 경고를 실행합니다.
    
    ### 선택한 조치
    1. 현장 방송 경고 - 매뉴얼 권장 조치
    ```
    """

    def agent_node(state: ResponseAgentState) -> Dict[str, Any]:
        """에이전트가 다음 행동을 결정합니다."""
        messages = list(state.get("messages", []))

        # 첫 실행 시 시스템 프롬프트와 상황 정보 추가
        if not messages:
            # search_knowledge 노드에서 생성된 검색 결과 가져오기
            knowledge_context = state.get("knowledge_context", "")

            context = f"""## 현재 상황
            - 카메라: {state.get('camera_name', '')} ({state.get('camera_location', '')})
            - 카메라 ID: {state.get('camera_id', '')}
            - 이벤트 유형: {state.get('event_type', '')}
            - 위험도: {state.get('risk_level', '')} (점수: {state.get('risk_score', 0)})
            - 상황 요약: {state.get('summary', '')}
            - 발생 시각: {state.get('occurred_at', '')}
            
            ## 참조 정보 (대응 매뉴얼 및 과거 사례)
            {knowledge_context}
            
            위 정보를 참고하여 적절한 대응 조치를 결정해주세요."""

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=context)
            ]

        # LLM 호출
        response = llm.invoke(messages)

        return {"messages": [response]}

    return agent_node


def should_continue(state: ResponseAgentState) -> Literal["tools", "check_approval", "report", "end"]:
    """
    에이전트가 다음에 어디로 갈지 결정합니다.

    [라우팅 로직]
    - emergency_call 도구 호출 포함 → "check_approval" (승인 대기)
    - field_action 도구만 호출 → "tools" (바로 실행)
    - 도구 호출 없음 → "report" (보고서 생성)
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


def increment_iteration(state: ResponseAgentState) -> Dict[str, Any]:
    """반복 횟수를 증가시킵니다."""
    return {"iteration": state.get("iteration", 0) + 1}


# =========================================
# Human-in-the-Loop 승인 관련 노드
# =========================================
def check_approval_node(state: ResponseAgentState, config: Config) -> Dict[str, Any]:
    """
    emergency_call 도구 호출에 대해 백엔드 API를 통해 사용자 승인을 요청하고 대기하는 노드

    [역할]
    1. 마지막 메시지에서 emergency_call 도구 호출 정보 추출
    2. Action 생성 API 호출 → actionId 획득
       POST /internal/agent/events/{eventId}/actions
    3. 승인 확인 API 호출 → 사용자 응답 대기
       POST /internal/agent/events/{eventId}/actions/{actionId}/confirm
    4. 승인 결과를 state에 저장

    [API 흐름]
    1) POST /internal/agent/events/{eventId}/actions
       Request:  { action, description }
       Response: { actionId }

    2) POST /internal/agent/events/{eventId}/actions/{actionId}/confirm
       Request:  (없음)
       Response: { userId, userName, userMail, result }

    Args:
        state: 현재 에이전트 상태
        config: 시스템 설정

    Returns:
        업데이트된 상태 (pending_approval, approval_result)
    """
    from ...clients.backend_client import BackendClient

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
        # POST /internal/agent/events/{eventId}/actions/{actionId}/confirm
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


def approval_router(state: ResponseAgentState) -> Literal["tools", "skip_emergency"]:
    """
    승인 결과에 따라 다음 노드를 결정합니다.

    - 승인됨 → "tools" (emergency_call 포함 모든 도구 실행)
    - 거부/타임아웃 → "skip_emergency" (emergency_call만 스킵)
    """
    approval_result = state.get("approval_result", {})
    approved = approval_result.get("approved", False)

    if approved:
        logger.info("[approval_router] 승인됨 → 도구 실행")
        return "tools"
    else:
        logger.info(f"[approval_router] 거부/타임아웃 → emergency_call 스킵 (status: {approval_result.get('status')})")
        return "skip_emergency"


def skip_emergency_call_node(state: ResponseAgentState) -> Dict[str, Any]:
    """
    emergency_call 도구 호출을 스킵하고 ToolMessage를 생성합니다.

    LLM이 emergency_call을 호출했지만 사용자가 거부한 경우,
    도구 실행 없이 "사용자가 거부함" 메시지를 반환합니다.
    """
    from langchain_core.messages import ToolMessage

    messages = state.get("messages", [])
    if not messages:
        return {}

    last_message = messages[-1]
    new_messages = []

    # 도구 호출 처리
    if hasattr(last_message, "tool_calls"):
        for tool_call in last_message.tool_calls:
            tool_name = tool_call.get("name", "")
            tool_call_id = tool_call.get("id", "")

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
            else:
                # 다른 도구 (field_action)는 실행해야 함 - 여기서는 처리하지 않음
                # tools 노드에서 처리됨
                pass

    return {"messages": new_messages}


def extract_actions(state: ResponseAgentState, config: Config) -> Dict[str, Any]:
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
    """
    import re
    from datetime import datetime
    from ...clients.backend_client import BackendClient

    actions = []
    rag_references = []

    # agency_type을 action 코드로 변환하는 매핑
    # (response_tools.py의 emergency_call 도구에서 사용하는 코드와 일치)
    AGENCY_TO_ACTION = {
        "경찰청 112": "112_POLICE",
        "소방청 119": "119_FIRE",
        "내부 보안팀": "SECURITY_TEAM",
        "관리사무소": "MANAGEMENT",
    }

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
                # =========================================
                # action 코드 추출 (BROADCAST, LIGHT_ON, PTZ_TRACK, SIREN)
                # =========================================
                # 예시: "- 액션: BROADCAST"
                action_code = None
                action_match = re.search(r"- 액션:\s*(\w+)", content)
                if action_match:
                    action_code = action_match.group(1)

                # description 생성 - 실행 결과를 요약하여 설명 텍스트로 사용
                # 예시: "- 대상 카메라: cam-001"
                camera_match = re.search(r"- 대상 카메라:\s*(.+)", content)
                camera_id = camera_match.group(1).strip() if camera_match else ""

                # 방송 메시지 추출 (BROADCAST인 경우)
                message_match = re.search(r'- 방송 내용:\s*"(.+)"', content)
                broadcast_msg = message_match.group(1) if message_match else ""

                # 실행 시각 추출
                time_match = re.search(r"- 실행 시각:\s*(.+)", content)
                triggered_at = time_match.group(1).strip() if time_match else ""

                # description 조립 - 사람이 읽기 쉬운 형태로
                if action_code == "BROADCAST" and broadcast_msg:
                    description = f"[{action_code}] 카메라 {camera_id}에서 방송 실행: \"{broadcast_msg}\" (실행 시각: {triggered_at})"
                else:
                    description = f"[{action_code}] 카메라 {camera_id}에서 현장 조치 실행 (실행 시각: {triggered_at})"

                actions.append({
                    "action": action_code,      # BROADCAST, LIGHT_ON, PTZ_TRACK, SIREN
                    "description": description, # 조치에 대한 상세 설명
                    "user_id": None             # field_action은 자동 실행 (HITL 미적용)
                })

            # emergency_call 결과 → actions + 백엔드 갱신
            # emergency_call은 HITL 승인이 필요하므로 user_id 포함 가능
            elif "긴급 신고 접수 결과" in content:
                # =========================================
                # agency 추출 후 action 코드로 변환
                # =========================================
                # 예시: "- 신고 기관: 경찰청 112"
                action_code = None
                agency_name = ""
                agency_match = re.search(r"- 신고 기관:\s*(.+)", content)
                if agency_match:
                    agency_name = agency_match.group(1).strip()
                    # 한글 agency명을 action 코드로 변환
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
                if approval_user_name:
                    approver_info = f"승인자: {approval_user_name}"
                    if approval_user_mail:
                        approver_info += f" ({approval_user_mail})"

                # description 조립 - 사람이 읽기 쉬운 형태로 + 승인자 정보 포함
                description = f"[APPROVED] {agency_name} 긴급 신고 접수"
                if approver_info:
                    description += f" | {approver_info}"
                description += f" (접수번호: {receipt_no}, 접수 시각: {triggered_at})"
                if situation_summary:
                    description += f" - 상황: {situation_summary}"

                # =========================================
                # 백엔드 갱신: PATCH /internal/agent/events/{eventId}/actions/{actionId}
                # 도구 실행 완료 후 최종 결과를 백엔드에 업데이트
                # =========================================
                if approval_action_id and event_id:
                    try:
                        backend_client = BackendClient(config)
                        backend_client.update_action(
                            event_id=event_id,
                            action_id=approval_action_id,
                            action=action_code,
                            description=description,
                            user_id=approval_user_id,
                        )
                        logger.info(f"[{event_id}] emergency_call 결과 백엔드 갱신 완료 (actionId: {approval_action_id})")
                    except Exception as e:
                        logger.error(f"[{event_id}] emergency_call 결과 백엔드 갱신 실패: {e}")

                actions.append({
                    "action": action_code,          # 112_POLICE, 119_FIRE, SECURITY_TEAM, MANAGEMENT
                    "description": description,    # 조치에 대한 상세 설명
                    "user_id": approval_user_id    # HITL 승인자 ID (승인된 경우)
                })

            # =========================================
            # emergency_call 거절/타임아웃 결과 → actions + 백엔드 갱신
            # =========================================
            elif "긴급 신고가 사용자에 의해 거부되었습니다" in content:
                # pending_approval에서 원래 요청 정보 가져오기
                pending_approval = state.get("pending_approval", {})
                pending_agency_type = pending_approval.get("agency_type", "")

                action_code = f"REJECTED_{pending_agency_type}" if pending_agency_type else "REJECTED_EMERGENCY"

                # 거절자 정보 조립
                rejecter_info = ""
                if approval_user_name:
                    rejecter_info = f"거절자: {approval_user_name}"
                    if approval_user_mail:
                        rejecter_info += f" ({approval_user_mail})"

                # description 조립 - 거절자 정보 포함
                description = f"[REJECTED] 긴급 신고 요청이 사용자에 의해 거부됨"
                if rejecter_info:
                    description += f" | {rejecter_info}"

                # 백엔드 갱신
                if approval_action_id and event_id:
                    try:
                        backend_client = BackendClient(config)
                        backend_client.update_action(
                            event_id=event_id,
                            action_id=approval_action_id,
                            action=action_code,
                            description=description,
                            user_id=approval_user_id,
                        )
                        logger.info(f"[{event_id}] emergency_call 거절 결과 백엔드 갱신 완료")
                    except Exception as e:
                        logger.error(f"[{event_id}] emergency_call 거절 결과 백엔드 갱신 실패: {e}")

                actions.append({
                    "action": action_code,
                    "description": description,
                    "user_id": approval_user_id
                })

            elif "긴급 신고가 타임아웃되었습니다" in content:
                pending_approval = state.get("pending_approval", {})
                pending_agency_type = pending_approval.get("agency_type", "")

                action_code = f"TIMEOUT_{pending_agency_type}" if pending_agency_type else "TIMEOUT_EMERGENCY"
                description = f"[TIMEOUT] 긴급 신고 요청에 대한 응답 타임아웃"

                # 백엔드 갱신
                if approval_action_id and event_id:
                    try:
                        backend_client = BackendClient(config)
                        backend_client.update_action(
                            event_id=event_id,
                            action_id=approval_action_id,
                            action=action_code,
                            description=description,
                            user_id=None,  # 타임아웃은 응답자 없음
                        )
                        logger.info(f"[{event_id}] emergency_call 타임아웃 결과 백엔드 갱신 완료")
                    except Exception as e:
                        logger.error(f"[{event_id}] emergency_call 타임아웃 결과 백엔드 갱신 실패: {e}")

                actions.append({
                    "action": action_code,
                    "description": description,
                    "user_id": None
                })

    return {"actions": actions, "rag_references": rag_references}


def generate_report_node(state: ResponseAgentState, app_config: Config) -> Dict[str, Any]:
    """최종 보고서를 생성하고 업로드합니다."""
    from ...services.report_generator import ReportGeneratorService
    from ...clients.backend_client import BackendClient

    camera_name = state.get("camera_name", "")
    camera_location = state.get("camera_location", "")
    event_type = state.get("event_type", "")
    risk_level = state.get("risk_level", "")
    risk_score = state.get("risk_score", 0)
    summary = state.get("summary", "")
    occurred_at = state.get("occurred_at", "")
    actions = state.get("actions", [])
    frames = state.get("frames", [])
    event_id = state.get("event_id", "")

    # 위험 점수 포맷팅
    risk_score_str = f"{risk_score:.2f}" if isinstance(risk_score, (int, float)) else str(risk_score)

    # 마크다운 보고서 내용 생성
    content = f"""# 이상 상황 대응 보고서

## 1. 개요
- **발생 일시**: {occurred_at}
- **위치**: {camera_name} ({camera_location})
- **이벤트 유형**: {event_type}
- **위험도**: {risk_level} (점수: {risk_score_str})

## 2. 상황 요약
{summary}

## 3. 대응 조치
"""

    if actions:
        for i, action in enumerate(actions, 1):
            content += f"{i}. {action.get('description', '조치 내용 없음')}\n"
    else:
        content += "- 결정된 조치 없음\n"

    content += f"""
## 4. 비고
- 보고서 생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 담당 시스템: AEGIS AI Agent
"""

    # 보고서 파일 URL (업로드 후 채워짐)
    file_urls = {"pdf": None, "docx": None, "pptx": None, "hwp": None}

    try:
        # 1. 보고서 파일 생성
        report_generator = ReportGeneratorService()

        report_data = {
            "occurred_at": occurred_at,
            "event_type": event_type,
            "camera_name": camera_name,
            "camera_location": camera_location,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "summary": summary,
            "actions": actions,
        }

        generated_files = report_generator.generate(
            report_data=report_data,
            frames=frames,
            formats=["pdf", "docx", "pptx"]
        )

        logger.info(f"보고서 파일 생성 완료: PDF={generated_files.get('pdf') is not None}, DOCX={generated_files.get('docx') is not None}, PPTX={generated_files.get('pptx') is not None}")

        # 2. 보고서 파일 업로드 (Mock 서버 또는 MinIO)
        if event_id:
            backend_client = BackendClient(app_config)

            # 업로드할 파일들과 Content-Type 매핑
            content_types = {
                "pdf": "application/pdf",
                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            }

            for fmt, file_bytes in generated_files.items():
                if file_bytes and fmt in content_types:
                    try:
                        # presigned URL 획득
                        url_info = backend_client.get_report_upload_url(event_id, fmt)
                        if url_info:
                            upload_url = url_info.get("upload_url")
                            report_path = url_info.get("report_path")

                            # 파일 업로드
                            if backend_client.upload_report(upload_url, file_bytes, content_types[fmt]):
                                file_urls[fmt] = report_path
                                logger.info(f"✅ [{event_id}] {fmt.upper()} 보고서 업로드 완료: {report_path}")
                            else:
                                logger.error(f"❌ [{event_id}] {fmt.upper()} 보고서 업로드 실패")
                        else:
                            logger.error(f"❌ [{event_id}] {fmt.upper()} 업로드 URL 획득 실패")
                    except Exception as e:
                        logger.error(f"❌ [{event_id}] {fmt.upper()} 보고서 업로드 중 오류: {e}")
        else:
            logger.warning("event_id가 없어 보고서 업로드를 건너뜁니다.")

    except Exception as e:
        logger.error(f"보고서 파일 생성/업로드 실패: {e}", exc_info=True)

    # 보고서 Dict 구조 (files에 URL 저장)
    report = {
        "content": content,
        "files": file_urls,
        "generated_at": datetime.now().isoformat()
    }

    logger.info(f"보고서 생성 완료: {len(content)} 자, 업로드된 파일: {[k for k, v in file_urls.items() if v]}")

    return {"report": report}


def update_report_to_backend(state: ResponseAgentState, app_config: Config) -> Dict[str, Any]:
    """보고서와 대응 조치를 백엔드에 갱신합니다."""
    from ...clients.backend_client import BackendClient

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

    [Human-in-the-Loop]
    - emergency_call 도구 호출 시 → check_approval 노드
    - SSE로 프론트엔드 모달에 승인 요청 전송
    - 사용자가 모달에서 승인/거부 버튼 클릭
    - 승인 시: tools 노드로 이동하여 실행
    - 거부/타임아웃 시: skip_emergency 노드로 이동하여 스킵

    Args:
        config: 시스템 설정

    Returns:
        컴파일된 서브그래프
    """
    import functools

    # 도구 생성 (search_protocol_and_cases 제외됨)
    tools = create_tools(config)

    # 에이전트 노드 생성
    agent_node = create_agent_node(config, tools)

    # 도구 노드 생성
    tool_node = ToolNode(tools)

    # 지식 검색 노드에 config 바인딩
    search_knowledge = functools.partial(search_knowledge_node, config=config)

    # 백엔드 갱신 노드에 app_config 바인딩
    update_backend = functools.partial(update_report_to_backend, app_config=config)

    # 보고서 생성 노드에 app_config 바인딩 (업로드용)
    generate_report = functools.partial(generate_report_node, app_config=config)

    # Human-in-the-Loop 승인 확인 노드에 config 바인딩
    check_approval = functools.partial(check_approval_node, config=config)

    # extract_actions 노드에 config 바인딩 (백엔드 갱신용)
    extract_actions_with_config = functools.partial(extract_actions, config=config)

    # 그래프 빌더
    workflow = StateGraph(ResponseAgentState)

    # 노드 추가
    workflow.add_node("search_knowledge", search_knowledge)  # 지식 검색 노드
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("increment", increment_iteration)
    workflow.add_node("extract_actions", extract_actions_with_config)  # config 바인딩된 버전
    workflow.add_node("generate_report", generate_report)
    workflow.add_node("update_backend", update_backend)

    # Human-in-the-Loop 노드 추가
    workflow.add_node("check_approval", check_approval)        # 승인 요청 및 대기
    workflow.add_node("skip_emergency", skip_emergency_call_node)  # emergency_call 스킵

    # =========================================
    # 엣지 설정 (Human-in-the-Loop 포함)
    # =========================================
    workflow.add_edge(START, "search_knowledge")
    workflow.add_edge("search_knowledge", "agent")

    # agent → should_continue 조건부 엣지
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",                    # field_action만 있는 경우
            "check_approval": "check_approval",  # emergency_call 포함된 경우
            "report": "extract_actions",         # 도구 호출 없음
            "end": END
        }
    )

    # check_approval → approval_router 조건부 엣지
    workflow.add_conditional_edges(
        "check_approval",
        approval_router,
        {
            "tools": "tools",              # 승인됨 → 도구 실행
            "skip_emergency": "skip_emergency"  # 거부/타임아웃 → 스킵
        }
    )

    # 일반 도구 실행 후 루프
    workflow.add_edge("tools", "increment")
    workflow.add_edge("increment", "agent")

    # emergency_call 스킵 후 루프 (다음 도구 호출 또는 종료)
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

    [워크플로우]
    1. search_knowledge: 매뉴얼/과거 사례 검색 (무조건 실행)
    2. agent: 검색 결과를 참조하여 대응 결정
    3. tools: 현장 조치/긴급 신고 실행
    4. generate_report: 보고서 생성
    5. update_backend: 백엔드 갱신
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
            "frames": state.get("frames", []),  # 보고서 이미지용
            "messages": [],
            "actions": [],
            "rag_references": [],
            "knowledge_context": "",  # search_knowledge 노드에서 채워짐
            "report": {},
            "report_updated": False,
            "iteration": 0,
            "errors": [],
            # Human-in-the-Loop 승인 관련 필드
            "pending_approval": {},   # 승인 대기 중인 emergency_call 정보
            "approval_result": {},    # 승인 결과
        }

        # 에이전트 실행
        result = agent.invoke(agent_state)

        logger.info(f"[{camera_id}] 대응 에이전트 완료: {len(result.get('actions', []))}개 조치 결정, 백엔드 갱신: {result.get('report_updated', False)}")

        return {
            "actions": result.get("actions", []),
            "rag_references": result.get("rag_references", []),
            "report": result.get("report", {}),
            "report_updated": result.get("report_updated", False)
        }

    except Exception as e:
        logger.error(f"[{camera_id}] 대응 에이전트 실행 실패: {e}", exc_info=True)
        return {
            "actions": [],
            "rag_references": [],
            "report": {
                "content": f"보고서 생성 실패: {e}",
                "files": {"pdf": None, "docx": None, "pptx": None, "hwp": None},
                "generated_at": datetime.now().isoformat()
            },
            "report_updated": False,
            "errors": state.get("errors", []) + [f"Response agent exception: {e}"]
        }


