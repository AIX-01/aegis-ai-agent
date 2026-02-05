import functools
from langgraph.graph import StateGraph, END
from .state import AnalysisState
from .nodes import (
    verification_node,
    precision_analysis_node,
    action_node,
    update_backend_node,
    generate_report_node
)
from .edges import analysis_router, verification_router
from ..clients import VLMClient, PrecisionClient, BackendClient
from ..config import Config

def build_graph(config: Config):
    """
    LangGraph 기반 분석 워크플로우를 빌드하고 컴파일합니다.

    이 그래프는 Consumer에서 VLM 분석 및 백엔드 1차 보고가 완료된 후 실행됩니다.
    초기 입력 상태(AnalysisState)에는 이미 risk_level과 event_id가 포함되어 있어야 합니다.
    
    [워크플로우 흐름]
    (Pre-Graph: VLM 분석 -> 백엔드 1차 보고 -> Event ID 생성)
    1. Analysis Router (Entry Point): 
       - ABNORMAL -> Precision Analysis (정밀 분석)
       - SUSPICIOUS -> Verification (검증)
       - NORMAL -> End (종료)
    2. Verification:
       - 검증 결과 ABNORMAL 격상 -> Precision Analysis
       - 그 외 (NORMAL/SUSPICIOUS 유지) -> 종료
       - *(구체적 로직 미정 - TBD)*
    3. Precision Analysis: LLM 기반 상세 분석 수행
    4. Update Backend: 최종 분석 결과로 백엔드 이벤트 갱신
    5. Action: 대응 조치 결정
    6. Generate Report: 최종 보고서 생성

    Args:
        config: 시스템 설정 객체

    Returns:
        컴파일된 LangGraph 객체
    """
    # 클라이언트 초기화
    precision_client = PrecisionClient(config)
    backend_client = BackendClient(config)

    # 노드에 클라이언트 바인딩
    precision_analysis = functools.partial(precision_analysis_node, precision_client=precision_client)
    update_backend = functools.partial(update_backend_node, backend_client=backend_client)
    generate_report = functools.partial(generate_report_node, backend_client=backend_client)

    # 그래프 빌더
    workflow = StateGraph(AnalysisState)

    # 노드 추가 (backend_report 제외)
    workflow.add_node("verification", verification_node)
    workflow.add_node("precision_analysis", precision_analysis)
    workflow.add_node("action", action_node)
    workflow.add_node("update_backend", update_backend)
    workflow.add_node("generate_report", generate_report)

    # 그래프 진입점 설정: 상태에 따라 바로 분기 (Conditional Entry Point)
    workflow.set_conditional_entry_point(
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

    # 정밀 분석 -> 백엔드 갱신 -> 대응 조치 -> 리포트 생성 -> 종료
    workflow.add_edge("precision_analysis", "update_backend")
    workflow.add_edge("update_backend", "action")
    workflow.add_edge("action", "generate_report")
    workflow.add_edge("generate_report", END)

    # 그래프 컴파일
    return workflow.compile()
