import logging
from typing import Dict, Any

from ..state import AnalysisState

logger = logging.getLogger(__name__)

def verification_node(state: AnalysisState) -> Dict[str, Any]:
    """
    'SUSPICIOUS' 상태를 검증하는 노드 (Stub)
    현재는 'ABNORMAL'로 상태를 변경하기만 함.

    Args:
        state: 현재 분석 상태

    Returns:
        업데이트된 상태 딕셔너리 (risk_level)
    """
    camera_id = state["camera_id"]
    logger.info(f"[{camera_id}] 검증 노드 실행 (SUSPICIOUS -> ABNORMAL)...")

    # TODO: 실제 검증 로직 구현 (예: 다른 모델 호출, 규칙 기반 확인 등)
    
    return {"risk_level": "ABNORMAL"}
