import functools
from langgraph.graph import StateGraph, END
from .state import AnalysisState
from .nodes import (
    vlm_analysis_node,
    backend_report_node,
    verification_node,
    precision_analysis_node,
    update_backend_node,
    generate_report_node
)
from .edges import analysis_router, verification_router
from ..clients import VLMClient, PrecisionClient, BackendClient
from ..config import Config

def build_graph(config: Config):
    """
    LangGraph 기반 분석 워크플로우를 빌드하고 컴파일합니다.

    Args:
        config: 시스템 설정 객체

    Returns:
        컴파일된 LangGraph 객체
    """
    # 클라이언트 초기화
    vlm_client = VLMClient(config)
    precision_client = PrecisionClient(config)
    backend_client = BackendClient(config)

    # 노드에 클라이언트 바인딩
    vlm_analysis = functools.partial(vlm_analysis_node, vlm_client=vlm_client)
    backend_report = functools.partial(backend_report_node, backend_client=backend_client)
    precision_analysis = functools.partial(precision_analysis_node, precision_client=precision_client)
    update_backend = functools.partial(update_backend_node, backend_client=backend_client)

    # 그래프 빌더 (StatefulGraph 대신 StateGraph 사용, LangGraph 최신 버전 기준)
    workflow = StateGraph(AnalysisState)

    # 노드 추가
    workflow.add_node("vlm_analysis", vlm_analysis)
    workflow.add_node("backend_report", backend_report)
    workflow.add_node("verification", verification_node)
    workflow.add_node("precision_analysis", precision_analysis)
    workflow.add_node("update_backend", update_backend)
    workflow.add_node("generate_report", generate_report_node)

    # 그래프 구조 정의
    workflow.set_entry_point("vlm_analysis")
    workflow.add_edge("vlm_analysis", "backend_report")
    
    # 1차 분석 라우터
    workflow.add_conditional_edges(
        "backend_report",
        analysis_router,
        {
            "verification": "verification",
            "precision_analysis": "precision_analysis",
            "end": END
        }
    )

    # 검증 후 라우터
    workflow.add_conditional_edges(
        "verification",
        verification_router,
        {
            "precision_analysis": "precision_analysis",
            "end": END
        }
    )

    workflow.add_edge("precision_analysis", "update_backend")
    workflow.add_edge("update_backend", "generate_report")
    workflow.add_edge("generate_report", END)

    # 그래프 컴파일
    return workflow.compile()
