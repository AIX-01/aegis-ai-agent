import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from ..state import AnalysisState
from ...clients.backend_client import BackendClient

logger = logging.getLogger(__name__)

# --- Pydantic Models for Report Structure ---

class CameraInfo(BaseModel):
    id: str
    name: str = "Unknown"
    location: str = "Unknown"

class EventInfo(BaseModel):
    id: str
    occurred_at: str
    camera: CameraInfo

class AnalysisData(BaseModel):
    risk_level: str
    event_type: str
    risk_score: Optional[str] = None
    summary: str = ""
    status: str = "ANALYZED"

class RAGReference(BaseModel):
    id: Optional[str] = None
    source: str
    title: str
    content: str
    category: Optional[str] = None
    relevance_score: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RecommendedAction(BaseModel):
    priority: str = "MEDIUM"  # HIGH, MEDIUM, LOW
    category: str = "GENERAL"
    title: str
    description: str
    estimated_time: Optional[str] = None
    sop_reference: Optional[str] = None

class ClipInfo(BaseModel):
    url: Optional[str] = None
    confirmed: bool = False

class EventReport(BaseModel):
    version: str = "1.0"
    generated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    event: EventInfo
    analysis: AnalysisData
    precision_analysis: Dict[str, Any] = Field(default_factory=dict)
    rag_references: List[RAGReference] = Field(default_factory=list)
    recommended_actions: List[RecommendedAction] = Field(default_factory=list)
    clip: ClipInfo

# --- Node Implementation ---

def generate_report_node(state: AnalysisState, backend_client: BackendClient = None) -> Dict[str, Any]:
    """
    최종 분석 보고서(JSON)를 생성하고 백엔드에 업데이트하는 노드

    Args:
        state: 현재 분석 상태
        backend_client: 백엔드 클라이언트 (선택 사항, 테스트 시 None일 수 있음)

    Returns:
        업데이트된 상태 딕셔너리 (report)
    """
    event_id = state.get("event_id")
    camera_id = state["camera_id"]
    
    if not event_id:
        logger.warning(f"[{camera_id}] 보고서를 생성할 Event ID가 없습니다.")
        return {"errors": state.get("errors", []) + ["Generate report failed: No event_id"]}

    logger.info(f"[{camera_id}] 최종 보고서 생성 시작... (Event ID: {event_id})")

    try:
        # 1. 데이터 매핑
        report_data = EventReport(
            event=EventInfo(
                id=event_id,
                occurred_at=state["occurred_at"].isoformat() if isinstance(state["occurred_at"], datetime) else str(state["occurred_at"]),
                camera=CameraInfo(
                    id=camera_id,
                    name=state.get("camera_name", "Unknown"),
                    location=state.get("camera_location", "Unknown")
                )
            ),
            analysis=AnalysisData(
                risk_level=state.get("risk_level", "UNKNOWN"),
                event_type=state.get("event_type", "UNKNOWN"),
                risk_score=str(state.get("risk_score", "")) if state.get("risk_score") is not None else None,
                summary=state.get("summary", "")
            ),
            precision_analysis=state.get("precision_result", {}),
            # TODO: 추후 RAG 및 Action 노드 구현 시 state에서 가져오도록 수정
            rag_references=state.get("rag_references", []), 
            recommended_actions=state.get("recommended_actions", []),
            clip=ClipInfo(
                url=state.get("clip_url"), # 백엔드에서 확정된 URL이 있다면 state에 있어야 함
                confirmed=bool(state.get("clip_url"))
            )
        )

        # 2. JSON 직렬화
        report_json = report_data.model_dump_json(indent=2)
        
        # 3. 백엔드 전송 (선택적)
        # 현재 백엔드 API에는 report 컬럼 업데이트 전용 API가 없으므로
        # update_event_analysis를 재활용하거나, 추후 추가될 API를 사용해야 함.
        # 여기서는 로깅만 하고 state에 저장합니다.
        # 만약 backend_client가 있고 report 업데이트 기능이 있다면 여기서 호출합니다.
        
        # 예시: backend_client.update_report(event_id, report_json)
        
        logger.info(f"[{camera_id}] 보고서 생성 완료 (길이: {len(report_json)} chars)")
        
        return {"report": report_json}

    except Exception as e:
        logger.error(f"[{camera_id}] 보고서 생성 중 오류 발생: {e}", exc_info=True)
        return {"errors": state.get("errors", []) + [f"Generate report exception: {e}"]}
