import functools
from langgraph.graph import StateGraph, END, START
from .state import AnalysisState
from .nodes import (
    verification_node,
    precision_analysis_node,
    update_backend_node,
    store_embedding_node,
)
from .subgraphs import response_agent_node
from .edges import verification_router
from ..clients import PrecisionClient, BackendClient
from ..config import Config

def build_graph(config: Config):
    """
    LangGraph 기반 분석 워크플로우를 빌드하고 컴파일합니다.

    이 그래프는 Consumer에서 VLM 분석 및 백엔드 1차 보고가 완료된 후 실행됩니다.
    초기 입력 상태(AnalysisState)에는 이미 risk_level과 event_id가 포함되어 있어야 합니다.
    
    [워크플로우 흐름]
    (Pre-Graph: VLM 분석 -> 백엔드 1차 보고 -> Event ID 생성)

    1. precision_analysis: LLM 기반 정밀 분석 수행
    2. verification: 정밀 분석 결과 검증
    3. update_backend: 검증 결과로 백엔드 갱신
    4. verification_router: 검증 결과에 따른 분기
       - ABNORMAL → response_agent (ReAct Agent) → store_embedding (순차) → END
       - SUSPICIOUS → END

    Args:
        config: 시스템 설정 객체

    Returns:
        컴파일된 LangGraph 객체
    """
    # 클라이언트 초기화
    precision_client = PrecisionClient(config)
    backend_client = BackendClient(config)

    # 노드에 클라이언트/설정 바인딩
    verification = functools.partial(verification_node, config=config)
    precision_analysis = functools.partial(precision_analysis_node, precision_client=precision_client)
    update_backend = functools.partial(update_backend_node, backend_client=backend_client)
    store_embedding = functools.partial(store_embedding_node, config=config)
    response_agent = functools.partial(response_agent_node, config=config)

    # 그래프 빌더
    workflow = StateGraph(AnalysisState)

    # 노드 추가
    workflow.add_node("precision_analysis", precision_analysis)
    workflow.add_node("verification", verification)
    workflow.add_node("update_backend", update_backend)
    workflow.add_node("store_embedding", store_embedding)
    workflow.add_node("response_agent", response_agent)  # ReAct Agent 서브그래프

    # 그래프 진입점: START → precision_analysis
    workflow.add_edge(START, "precision_analysis")

    # precision_analysis → verification → update_backend
    workflow.add_edge("precision_analysis", "verification")
    workflow.add_edge("verification", "update_backend")

    # update_backend → verification_router (조건부 분기)
    # ABNORMAL이면 response_agent로, SUSPICIOUS면 END로
    workflow.add_conditional_edges(
        "update_backend",
        verification_router,
        {
            "response_agent": "response_agent",
            "end": END
        }
    )

    # response_agent → store_embedding → END (순차 실행)
    workflow.add_edge("response_agent", "store_embedding")
    workflow.add_edge("store_embedding", END)

    # 그래프 컴파일
    return workflow.compile()
