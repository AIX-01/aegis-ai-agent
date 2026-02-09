"""
대응 조치 및 보고서 생성을 담당하는 ReAct Agent 서브그래프

이 서브그래프는 verification_router에서 ABNORMAL로 판정된 후 실행됩니다.
LLM이 도구를 선택하여 대응 조치를 결정하고, 최종 보고서를 생성합니다.

도구:
- search_manual: 대응 매뉴얼 검색
- search_past_cases: 유사 과거 사례 검색
- decide_action: 대응 조치 결정

워크플로우:
1. LLM이 상황 분석
2. 필요한 도구 호출 (매뉴얼/사례 검색)
3. 대응 조치 결정
4. 최종 보고서 생성
"""
import logging
from typing import Dict, Any, List, Annotated, TypedDict, Literal, Sequence
from datetime import datetime

from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from ..state import AnalysisState
from ...config import Config

logger = logging.getLogger(__name__)


# =========================================
# 서브그래프 상태 정의
# =========================================
class ResponseAgentState(TypedDict):
    """대응 에이전트 서브그래프의 상태"""
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
    actions: List[Dict[str, Any]]  # 결정된 대응 조치들
    rag_references: List[Dict[str, Any]]  # 검색된 참조 문서들
    report: Dict[str, Any]  # 최종 보고서 {content, files, generated_at}
    report_updated: bool  # 백엔드 갱신 여부
    iteration: int  # 반복 횟수 (무한 루프 방지)
    errors: List[str]  # 에러 목록


# =========================================
# 도구 정의
# =========================================
def create_tools(config: Config):
    """에이전트가 사용할 도구들을 생성합니다."""

    @tool
    def search_protocol_and_cases(query: str, event_type: str) -> str:
        """
        지식 검색 도구: event_type에 맞는 표준 대응 매뉴얼과 유사한 과거 사례를 검색합니다.

        Args:
            query: 상황 요약 (예: "1층 로비에서 남성이 쓰러져 있음")
            event_type: 사건 유형 (ASSAULT, BURGLARY, DUMP, SWOON, VANDALISM)

        Returns:
            해당 사건에 대한 단계별 대응 지침, 법적 근거, 과거 유사 처리 결과
        """
        from ...clients.vector_store_client import VectorStoreClient

        logger.info(f"[Tool] search_protocol_and_cases 호출: query='{query[:50]}...', event_type={event_type}")

        result_text = ""

        # 1. 과거 사례 검색 (past_cases 컬렉션 - store_embedding에서 저장한 데이터)
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
                    result_text += "## 과거 유사 사례\n\n"
                    for i, result in enumerate(past_results, 1):
                        payload = result.get("payload", {})
                        score = result.get("score", 0)
                        result_text += f"### 사례 {i} (유사도: {score:.2f})\n"
                        result_text += f"- 카메라: {payload.get('camera_name', '')} ({payload.get('camera_location', '')})\n"
                        result_text += f"- 이벤트: {payload.get('event_type', '')}\n"
                        result_text += f"- 발생시각: {payload.get('occurred_at', '')}\n"
                        result_text += f"- 상황: {payload.get('summary', '')}\n\n"
                else:
                    result_text += "## 과거 유사 사례\n검색 결과 없음\n\n"
            else:
                result_text += "## 과거 유사 사례\n컬렉션이 존재하지 않습니다.\n\n"

        except Exception as e:
            logger.error(f"과거 사례 검색 실패: {e}")
            result_text += f"## 과거 유사 사례\n검색 실패: {e}\n\n"

        # 2. 대응 매뉴얼 (현재는 Mock - 추후 manuals 컬렉션 구현 시 연동)
        manual_templates = {
            "ASSAULT": """## 대응 매뉴얼 (ASSAULT - 폭행)

### 단계별 대응 지침
1. 상황 확인: CCTV 영상으로 현장 상황 재확인
2. 초동 조치: 보안 담당자 현장 출동 지시
3. 경찰 신고: 112 신고 (폭행 현행범)
4. 피해자 보호: 피해자 안전 확보 및 응급 조치
5. 증거 보존: 영상 클립 및 보고서 저장

### 법적 근거
- 형법 제260조 (폭행죄)
- 경비업법 제7조 (경비업무의 범위)""",

            "SWOON": """## 대응 매뉴얼 (SWOON - 실신)

### 단계별 대응 지침
1. 상황 확인: 쓰러진 사람의 상태 확인
2. 119 신고: 즉시 응급 신고
3. 현장 조치: 보안 담당자 출동, 주변 통제
4. 응급 처치: AED 준비, 기도 확보
5. 기록 보존: 영상 클립 및 보고서 저장

### 법적 근거
- 응급의료에 관한 법률 제5조 (응급환자에 대한 신고 및 협조 의무)""",

            "BURGLARY": """## 대응 매뉴얼 (BURGLARY - 절도/침입)

### 단계별 대응 지침
1. 상황 확인: 침입자 위치 및 행동 파악
2. 112 신고: 즉시 경찰 신고
3. PTZ 추적: 카메라로 대상 추적
4. 현장 통제: 보안 담당자 출동, 출입구 봉쇄
5. 증거 보존: 영상 클립 및 보고서 저장

### 법적 근거
- 형법 제329조 (절도죄)
- 형법 제319조 (주거침입죄)""",

            "VANDALISM": """## 대응 매뉴얼 (VANDALISM - 기물파손)

### 단계별 대응 지침
1. 상황 확인: 파손 행위 및 대상 확인
2. 현장 방송: 경고 방송 실시
3. 보안팀 출동: 현장 확인 및 제지
4. 피해 기록: 파손 상태 촬영 및 기록
5. 신고 판단: 피해 규모에 따라 112 신고

### 법적 근거
- 형법 제366조 (재물손괴죄)""",

            "DUMP": """## 대응 매뉴얼 (DUMP - 무단투기)

### 단계별 대응 지침
1. 상황 확인: 투기 행위 및 대상물 확인
2. 현장 방송: 경고 방송 실시
3. 증거 확보: 투기자 인상착의 및 영상 저장
4. 신고: 관할 구청 또는 환경부 신고
5. 기록 보존: 보고서 작성

### 법적 근거
- 폐기물관리법 제68조 (과태료)"""
        }

        result_text += manual_templates.get(event_type, f"## 대응 매뉴얼\n{event_type}에 대한 매뉴얼이 등록되지 않았습니다.")

        return result_text

    @tool
    def execute_field_action(action_name: str, camera_id: str, message_content: str = None) -> str:
        """
        현장 대응 도구: CCTV 방송, 조명 제어, PTZ 추적 등 물리적인 조치를 취합니다.

        Args:
            action_name: 실행할 액션 (BROADCAST, LIGHT_ON, PTZ_TRACK, SIREN)
                - BROADCAST: CCTV 스피커로 음성 방송
                - LIGHT_ON: 현장 조명 점등
                - PTZ_TRACK: PTZ 카메라로 대상 추적
                - SIREN: 경고 사이렌 작동
            camera_id: 대상 카메라 ID
            message_content: 방송 메시지 (BROADCAST 시 필수)

        Returns:
            실행 성공 여부
        """
        logger.info(f"[Tool] execute_field_action 호출: action={action_name}, camera={camera_id}, message={message_content}")

        # Mock 응답 - 실제 구현 시 장비 제어 API 호출
        mock_response = f"""## 현장 조치 실행 결과

- 액션: {action_name}
- 대상 카메라: {camera_id}
- 실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 상태: ✅ 성공

{f'- 방송 내용: "{message_content}"' if message_content else ''}
"""
        return mock_response

    @tool
    def emergency_call(agency_type: str, situation_report: str) -> str:
        """
        긴급 전파 도구: 112, 119 또는 유관 부서에 시스템적으로 신고를 접수합니다.

        Args:
            agency_type: 신고 기관 (112_POLICE, 119_FIRE, SECURITY_TEAM, MANAGEMENT)
                - 112_POLICE: 경찰 신고
                - 119_FIRE: 소방/응급 신고
                - SECURITY_TEAM: 내부 보안팀 호출
                - MANAGEMENT: 관리사무소 연락
            situation_report: 상황 보고 내용 (신고 시 전달할 내용)

        Returns:
            신고 접수 결과
        """
        logger.info(f"[Tool] emergency_call 호출: agency={agency_type}, report={situation_report[:50]}...")

        # Mock 응답 - 실제 구현 시 신고 API 연동
        agency_names = {
            "112_POLICE": "경찰청 112",
            "119_FIRE": "소방청 119",
            "SECURITY_TEAM": "내부 보안팀",
            "MANAGEMENT": "관리사무소"
        }

        mock_response = f"""## 긴급 신고 접수 결과

- 신고 기관: {agency_names.get(agency_type, agency_type)}
- 접수 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 접수 번호: EMG-{datetime.now().strftime('%Y%m%d%H%M%S')}
- 상태: ✅ 접수 완료

### 전달 내용
{situation_report}

### 예상 대응
- 담당자 배정 중
- 예상 도착 시간: 5-10분
"""
        return mock_response

    return [search_protocol_and_cases, execute_field_action, emergency_call]


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

    system_prompt = """당신은 CCTV 이상 감지 시스템의 대응 전문가입니다.

## 역할
이상 상황이 감지되면 적절한 대응 조치를 결정하고 실행합니다.

## 사용 가능한 도구
1. **search_protocol_and_cases**: 대응 매뉴얼과 과거 사례 검색
2. **execute_field_action**: 현장 물리적 조치 (방송, 조명, PTZ, 사이렌)
3. **emergency_call**: 긴급 신고 (112, 119, 보안팀)

## 프로세스
1. 상황 분석: 제공된 이벤트 정보를 분석합니다.
2. 지식 검색: search_protocol_and_cases로 대응 매뉴얼과 유사 사례를 검색합니다.
3. 현장 조치: execute_field_action으로 필요한 현장 조치를 실행합니다.
4. 긴급 신고: 필요시 emergency_call로 112/119/보안팀에 신고합니다.
5. 완료: 모든 필요한 조치를 완료했으면 종료합니다.

## 대응 기준
- SWOON (실신): 즉시 119 신고, 현장 방송으로 주변에 알림
- ASSAULT (폭행): 112 신고 + 보안팀 출동, 현장 방송/사이렌
- BURGLARY (절도): 112 신고 + 보안팀 출동, PTZ 추적
- VANDALISM (기물파손): 보안팀 출동, 현장 방송
- DUMP (무단투기): 현장 방송으로 경고, 기록 보존

## 주의사항
- 상황 심각도에 따라 적절한 도구를 선택하세요.
- 인명 관련 사건(SWOON, ASSAULT)은 반드시 긴급 신고를 수행하세요.
- 현장 조치와 신고를 병행할 수 있습니다.
"""

    def agent_node(state: ResponseAgentState) -> Dict[str, Any]:
        """에이전트가 다음 행동을 결정합니다."""
        messages = list(state.get("messages", []))

        # 첫 실행 시 시스템 프롬프트와 상황 정보 추가
        if not messages:
            context = f"""## 현재 상황
- 카메라: {state.get('camera_name', '')} ({state.get('camera_location', '')})
- 이벤트 유형: {state.get('event_type', '')}
- 위험도: {state.get('risk_level', '')} (점수: {state.get('risk_score', 0)})
- 상황 요약: {state.get('summary', '')}
- 발생 시각: {state.get('occurred_at', '')}

위 상황에 대해 적절한 대응 조치를 결정해주세요."""

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=context)
            ]

        # LLM 호출
        response = llm.invoke(messages)

        return {"messages": [response]}

    return agent_node


def should_continue(state: ResponseAgentState) -> Literal["tools", "report", "end"]:
    """에이전트가 계속 실행할지 결정합니다."""
    messages = state.get("messages", [])
    iteration = state.get("iteration", 0)

    # 최대 반복 횟수 제한 (무한 루프 방지)
    if iteration >= 5:
        logger.warning("에이전트 최대 반복 횟수 도달")
        return "report"

    if not messages:
        return "end"

    last_message = messages[-1]

    # 도구 호출이 있으면 도구 실행
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    # 도구 호출이 없으면 보고서 생성으로
    return "report"


def increment_iteration(state: ResponseAgentState) -> Dict[str, Any]:
    """반복 횟수를 증가시킵니다."""
    return {"iteration": state.get("iteration", 0) + 1}


def extract_actions(state: ResponseAgentState) -> Dict[str, Any]:
    """메시지에서 결정된 조치들과 참조 문서를 추출합니다."""
    actions = []
    rag_references = []

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
            elif "현장 조치 실행 결과" in content:
                actions.append({
                    "type": "field_action",
                    "description": content
                })

            # emergency_call 결과 → actions
            elif "긴급 신고 접수 결과" in content:
                actions.append({
                    "type": "emergency_call",
                    "description": content
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

    Args:
        config: 시스템 설정

    Returns:
        컴파일된 서브그래프
    """
    import functools

    # 도구 생성
    tools = create_tools(config)

    # 에이전트 노드 생성
    agent_node = create_agent_node(config, tools)

    # 도구 노드 생성
    tool_node = ToolNode(tools)

    # 백엔드 갱신 노드에 app_config 바인딩
    update_backend = functools.partial(update_report_to_backend, app_config=config)

    # 보고서 생성 노드에 app_config 바인딩 (업로드용)
    generate_report = functools.partial(generate_report_node, app_config=config)

    # 그래프 빌더
    workflow = StateGraph(ResponseAgentState)

    # 노드 추가
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("increment", increment_iteration)
    workflow.add_node("extract_actions", extract_actions)
    workflow.add_node("generate_report", generate_report)  # app_config 바인딩된 버전
    workflow.add_node("update_backend", update_backend)

    # 엣지 설정
    workflow.add_edge(START, "agent")

    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "report": "extract_actions",
            "end": END
        }
    )

    workflow.add_edge("tools", "increment")
    workflow.add_edge("increment", "agent")
    workflow.add_edge("extract_actions", "generate_report")
    workflow.add_edge("generate_report", "update_backend")
    workflow.add_edge("update_backend", END)

    return workflow.compile()


def response_agent_node(state: AnalysisState, config: Config) -> Dict[str, Any]:
    """
    메인 그래프에서 호출되는 대응 에이전트 노드입니다.

    AnalysisState를 ResponseAgentState로 변환하여 서브그래프를 실행하고,
    결과를 다시 AnalysisState 형식으로 반환합니다.
    """
    camera_id = state.get("camera_id", "")
    logger.info(f"[{camera_id}] 대응 에이전트 시작...")

    try:
        # 서브그래프 빌드
        agent = build_response_agent(config)

        # 상태 변환
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
            "messages": [],
            "actions": [],
            "rag_references": [],
            "report": {},
            "report_updated": False,
            "iteration": 0,
            "errors": []
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


