"""
대응 에이전트 서브그래프 상태 정의

ResponseAgentState는 response_agent 서브그래프에서 사용하는 상태 타입입니다.
부모 그래프(AnalysisState)에서 전달받은 정보와 에이전트 실행 중 생성되는 정보를 포함합니다.
"""
from datetime import datetime
from typing import Dict, Any, List, Annotated, TypedDict, Sequence

from langchain_core.messages import BaseMessage


class ResponseAgentState(TypedDict):
    """
    대응 에이전트 서브그래프의 상태

    [필드 설명]
    - 부모 그래프에서 전달받는 정보: 카메라, 이벤트 정보
    - 에이전트 실행 중 생성: 메시지, 대응 조치, 보고서 등
    - knowledge_context: search_knowledge 노드에서 생성된 검색 결과 (LLM 프롬프트에 주입)
    """
    # =========================================
    # 부모 그래프에서 전달받는 정보
    # =========================================
    camera_id: str
    camera_name: str
    camera_location: str
    event_id: str
    event_type: str
    risk_level: str
    risk_score: float
    summary: str
    occurred_at: datetime
    frames: List[bytes]  # CCTV 캡처 이미지 (보고서 생성용)
    frame_timestamps: List[datetime]  # 각 프레임의 타임스탬프

    # =========================================
    # 에이전트 실행 중 생성
    # =========================================
    # messages: LLM과의 대화 히스토리 (자동 병합)
    messages: Annotated[Sequence[BaseMessage], lambda x, y: x + y]

    # actions: 대응 조치 리스트 (백엔드 event_actions 테이블과 일치)
    # 형식: [{"action": str, "description": str, "user_id": str | None}, ...]
    actions: List[Dict[str, Any]]

    # rag_references: 검색된 참조 문서들
    rag_references: List[Dict[str, Any]]

    # knowledge_context: LLM에 주입할 검색 결과 텍스트 (매뉴얼 + 과거 사례)
    knowledge_context: str

    # reasoning: LLM 판단 근거 (과거 사례 분석, 법적 근거, 판단 근거)
    # extract_actions 노드에서 LLM 응답을 파싱하여 저장
    reasoning: str

    # report: 최종 보고서 HTML 문자열
    report: str

    # report_updated: 백엔드 갱신 여부
    report_updated: bool

    # iteration: 반복 횟수 (무한 루프 방지, 최대 5회)
    iteration: int

    # errors: 에러 목록
    errors: List[str]

    # =========================================
    # Human-in-the-Loop 승인 관련
    # =========================================
    # 백엔드 API 경유 방식:
    # POST /internal/agent/events/{eventId}/actions/{actionId}/pending
    #
    # Response Body:
    # {
    #     "userId": "uuid",        # 승인/거절한 사용자 ID
    #     "userName": "홍길동",     # 사용자 이름
    #     "userMail": "a@b.com",   # 사용자 이메일
    #     "result": true/false     # 승인 여부
    # }
    # =========================================

    # pending_approval: 승인 대기 중인 emergency_call 정보
    # 형식: {"tool_call_id": str, "agency_type": str, "situation_report": str}
    pending_approval: Dict[str, Any]

    # approval_result: 백엔드 응답 결과
    # 형식: {
    #     "approved": bool,        # result 값 (승인 여부)
    #     "status": str,           # "approved" | "rejected" | "timeout" | "pending"
    #     "user_id": str | None,   # userId (승인/거절자 ID)
    #     "user_name": str | None, # userName (승인/거절자 이름)
    #     "user_mail": str | None, # userMail (승인/거절자 이메일)
    #     "action_id": str | None, # 백엔드에서 생성된 action ID
    # }
    approval_result: Dict[str, Any]

