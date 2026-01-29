"""
최종 보고서를 생성하는 노드 (RAG 기반 - 작업 예정)
"""
import logging
from typing import Dict, Any

from ..state import AnalysisState

logger = logging.getLogger(__name__)

def generate_report_node(state: AnalysisState) -> Dict[str, Any]:
    """
    TODO: RAG 및 LLM을 사용하여 실제 보고서 생성 로직 구현
    """
    camera_id = state["camera_id"]
    logger.warning(f"[{camera_id}] 최종 보고서 생성이 호출되었으나, 아직 구현되지 않았습니다.")
    
    return {"report": "Not Implemented"}
