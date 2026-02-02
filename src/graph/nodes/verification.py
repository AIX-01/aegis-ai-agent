import logging
from typing import Dict, Any

from ..state import AnalysisState

logger = logging.getLogger(__name__)

def verification_node(state: AnalysisState) -> Dict[str, Any]:
    """
    'SUSPICIOUS' 상태를 검증하는 노드
    
    [작업 예정 / TBD]
    구체적인 검증 로직(예: 점수 확인, 다른 모델 호출 등)은 아직 확정되지 않았습니다.
    현재는 임시로 'ABNORMAL'로 넘겨서 테스트가 가능하게 하거나, 
    'NORMAL'로 종료시키는 등의 동작을 수행합니다.

    Args:
        state: 현재 분석 상태

    Returns:
        업데이트된 상태 딕셔너리
    """
    camera_id = state["camera_id"]
    logger.info(f"[{camera_id}] 검증 노드 실행 (현재 로직 미정 - TBD)")

    # TODO: 구체적인 검증 정책이 결정되면 여기에 구현합니다.
    # 예: if vlm_score > 0.8: return {"risk_level": "ABNORMAL"}
    
    # 임시 동작: 일단 정밀 분석으로 넘기기 위해 ABNORMAL 반환 (또는 필요에 따라 변경)
    return {"risk_level": "ABNORMAL"}
