from typing import TypedDict, List, Literal, Dict, Any, Union
from datetime import datetime

# 1차 분류: VLM 분석 결과
RiskLevel = Literal["NORMAL", "SUSPICIOUS", "ABNORMAL"]

# 2차 분류: 정밀 분석 이벤트 유형
EventType = Literal["ASSAULT", "BURGLARY", "DUMP", "SWOON", "VANDALISM"]


class AnalysisState(TypedDict):
    """
    LangGraph 분석 파이프라인의 상태를 정의하는 TypedDict

    태그 설명:
        [M]   = Main Graph에서만 사용
        [S]   = Sub Graph (response_agent)에서만 사용
        [M/S] = 양쪽 모두 사용
        [S→M] = Sub Graph에서 생성되어 Main Graph로 반환
    """

    # =========================================
    # 초기 입력 (Consumer에서 주입)
    # =========================================
    camera_id: str                     # [M/S] 카메라 ID
    camera_name: str                   # [M/S] 카메라 이름
    camera_location: str               # [M/S] 카메라 위치
    occurred_at: datetime              # [M/S] 분석 윈도우의 시작 시점
    frames: List[bytes]                # [M]   JPEG 이미지 바이트 리스트
    frame_timestamps: List[datetime]   # [M]   각 프레임의 타임스탬프 리스트
    event_id: str                      # [M/S] 백엔드에서 생성된 이벤트 ID
    vlm_result: Dict[str, Any]         # [M]   1차 VLM 분석 원본 결과
    window_start: Union[int, str]      # [M]   윈도우 시작 시간
    window_end: Union[int, str]        # [M]   윈도우 종료 시간

    # =========================================
    # 워크플로우 진행 중 생성
    # =========================================
    verification_result: Dict[str, Any]  # [M]   SUSPICIOUS 검증 결과
    precision_result: Dict[str, Any]     # [M]   2차 정밀 분석 원본 결과

    # =========================================
    # 최종 분석 결과 (워크플로우를 거치며 갱신됨)
    # =========================================
    risk_level: RiskLevel              # [M/S] 위험 등급 (NORMAL/SUSPICIOUS/ABNORMAL)
    event_type: EventType              # [M/S] 이벤트 유형 (ASSAULT/BURGLARY/DUMP/SWOON/VANDALISM)
    summary: str                       # [M/S] 상황 요약 텍스트
    risk_score: float                  # [M/S] 위험 점수 (0.0 ~ 1.0)
    report: str                        # [S→M] HTML 보고서 문자열 (백엔드 report 필드로 전달)

    # =========================================
    # 메타 데이터
    # =========================================
    # actions: 대응 조치 리스트 (백엔드 event_actions 테이블과 일치)
    # DB 스키마:
    #   - id: UUID (PK, 자동생성) - AI Agent에서 설정하지 않음
    #   - event_id: UUID (FK → events.id) - 백엔드에서 자동 매핑
    #   - user_id: UUID (FK → users.id) - HITL 승인자 ID (없으면 None)
    #   - action: TEXT - 조치 유형/코드 ("BROADCAST", "112_POLICE" 등)
    #   - description: TEXT - 조치에 대한 상세 설명
    #   - created_at: TIMESTAMP (자동생성)
    #   - updated_at: TIMESTAMP (자동생성)
    #
    # 형식: [
    #   {
    #     "action": "BROADCAST" | "112_POLICE" | ..., # 조치 유형/코드
    #     "description": "상세 설명 텍스트",           # 조치 설명 (기존 log 대신 사용)
    #     "user_id": "UUID" | None                   # HITL 승인자 ID (시스템 자동 시 None)
    #   }, ...
    # ]
    actions: list                      # [S→M] 대응 조치 리스트 [{action, description, user_id}, ...]
    rag_references: list               # [S→M] 검색된 참조 문서들 [{type, content}, ...]
    embedding_stored: bool             # [M]   이벤트 임베딩 저장 여부 (store_embedding 노드)
    report_updated: bool               # [S→M] 보고서 백엔드 갱신 여부 (response_agent 서브그래프)
    errors: List[str]                  # [M/S] 에러 메시지 목록
