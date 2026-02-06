from typing import Literal
from ..state import AnalysisState

def analysis_router(state: AnalysisState) -> Literal["end", "verification", "precision_analysis"]:
    """
    1차 분석 결과에 따른 분기 처리
    """
    risk_level = state.get("risk_level")
    
    if risk_level == "NORMAL":
        return "end"
    elif risk_level == "SUSPICIOUS":
        return "verification"
    elif risk_level == "ABNORMAL":
        return "precision_analysis"
    
    # 기본값은 종료
    return "end"

def verification_router(state: AnalysisState) -> Literal["end", "precision_analysis"]:
    """
    검증 결과에 따른 분기 처리
    검증 단계에서 'ABNORMAL'로 확정된 경우에만 정밀 분석으로 진행합니다.
    """
    risk_level = state.get("risk_level")
    
    if risk_level == "ABNORMAL":
        return "precision_analysis"
    
    # SUSPICIOUS 유지인 경우 정밀 분석을 수행하지 않고 종료
    return "end"
