from typing import Literal
from ..state import AnalysisState


def verification_router(state: AnalysisState) -> Literal["response_agent", "end"]:
    """
    검증 결과에 따른 분기 처리

    update_backend 후 실행됩니다.
    - ABNORMAL: response_agent → store_embedding 순차 실행
    - SUSPICIOUS/기타: 종료

    Args:
        state: 현재 분석 상태

    Returns:
        다음 노드 이름 ("response_agent" 또는 "end")
    """
    risk_level = state.get("risk_level")

    if risk_level == "ABNORMAL":
        return "response_agent"

    # SUSPICIOUS 또는 기타인 경우 종료
    return "end"


