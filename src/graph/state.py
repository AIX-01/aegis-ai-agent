from typing import TypedDict, List, Optional, Literal, Dict, Any, Union
from datetime import datetime

# 1차 분류: VLM 분석 결과
RiskLevel = Literal["NORMAL", "SUSPICIOUS", "ABNORMAL"]

# 2차 분류: 정밀 분석 이벤트 유형
EventType = Literal["ASSAULT", "BURGLARY", "DUMP", "SWOON", "VANDALISM"]

class AnalysisState(TypedDict):
    """LangGraph 분석 파이프라인의 상태를 정의하는 TypedDict"""

    # --- 초기 입력 ---
    camera_id: str
    camera_name: str
    camera_location: str
    occurred_at: datetime  # 분석 윈도우의 시작 시점
    frames: List[bytes]
    event_id: str
    vlm_result: Dict[str, Any]         # 1차 VLM 분석 원본 결과
    window_start: Union[int, str] # 윈도우 시작 시간 추가
    window_end: Union[int, str]   # 윈도우 종료 시간 추가
    
    # --- 워크플로우 진행 중 생성 ---
    precision_result: Dict[str, Any]   # 2차 정밀 분석 원본 결과
    
    # --- 최종 분석 결과 (워크플로우를 거치며 갱신됨) ---
    risk_level: RiskLevel
    event_type: EventType
    summary: str
    risk_score: float
    report: str             # -- 작업중 -- (보고서 생성 LLM 결과)
    
    # --- 메타 데이터 ---
    actions: list           # -- 작업중 --
    rag_references: list    # -- 작업중 --
    errors: List[str]
