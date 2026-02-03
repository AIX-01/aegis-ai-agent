"""
최종 보고서를 생성하는 노드 (RAG 기반)
Qdrant에서 유사 과거 사례 및 대응 매뉴얼을 검색하여 보고서 생성
"""
import logging
from typing import Dict, Any
from datetime import datetime

from ..state import AnalysisState

logger = logging.getLogger(__name__)

# VectorStoreClient는 지연 로딩 (Qdrant 연결 실패 시 graceful degradation)
_vector_client = None


def _get_vector_client():
    """VectorStoreClient를 지연 로딩합니다."""
    global _vector_client
    if _vector_client is None:
        try:
            from ...clients.vector_store_client import VectorStoreClient
            _vector_client = VectorStoreClient()
        except Exception as e:
            logger.warning(f"VectorStoreClient 초기화 실패 (RAG 비활성화): {e}")
            _vector_client = False  # 실패 시 False로 설정
    return _vector_client if _vector_client else None


def generate_report_node(state: AnalysisState) -> Dict[str, Any]:
    """
    RAG를 사용하여 과거 사례 및 매뉴얼 기반 최종 보고서를 생성합니다.
    
    Args:
        state: 현재 분석 상태
        
    Returns:
        report 필드가 포함된 상태 업데이트
    """
    camera_id = state.get("camera_id", "unknown")
    camera_name = state.get("camera_name", "알 수 없음")
    camera_location = state.get("camera_location", "알 수 없음")
    summary = state.get("summary", "요약 없음")
    event_type = state.get("event_type", "UNKNOWN")
    risk_level = state.get("risk_level", "UNKNOWN")
    risk_score = state.get("risk_score", 0.0)
    occurred_at = state.get("occurred_at", datetime.now())
    actions = state.get("actions", [])
    
    # 보고서 헤더
    report_parts = [
        "=" * 60,
        "📋 이상 행동 상세 분석 보고서",
        "=" * 60,
        "",
        "## 📍 기본 정보",
        f"- **카메라 ID**: {camera_id}",
        f"- **카메라명**: {camera_name}",
        f"- **위치**: {camera_location}",
        f"- **발생 시각**: {occurred_at}",
        "",
        "## ⚠️ 분석 결과",
        f"- **이벤트 유형**: {event_type}",
        f"- **위험 수준**: {risk_level}",
        f"- **위험도 점수**: {risk_score:.2f} / 1.00",
        "",
        "## 📝 상황 요약",
        summary,
        ""
    ]
    
    # RAG: 유사 과거 사례 검색
    vector_client = _get_vector_client()
    similar_cases = []
    manuals = []
    
    if vector_client:
        try:
            # 1. 유사한 과거 사례 검색
            similar_cases = vector_client.search_similar_events(
                query=summary,
                limit=3,
                event_type=event_type if event_type != "UNKNOWN" else None
            )
            
            # 2. 관련 대응 매뉴얼 검색
            manual_query = f"{event_type} 대응 방법" if event_type != "UNKNOWN" else summary
            manuals = vector_client.search_manuals(
                query=manual_query,
                limit=2
            )
            
            logger.info(f"[{camera_id}] RAG 검색 완료: 유사 사례 {len(similar_cases)}건, 매뉴얼 {len(manuals)}건")
            
        except Exception as e:
            logger.error(f"[{camera_id}] RAG 검색 실패: {e}")
    
    # 유사 과거 사례 추가
    if similar_cases:
        report_parts.append("## 📊 유사 과거 사례")
        for i, case in enumerate(similar_cases, 1):
            case_data = case.get('data', {})
            score = case.get('score', 0)
            report_parts.extend([
                f"",
                f"### 사례 {i} (유사도: {score:.1%})",
                f"- **요약**: {case_data.get('summary', 'N/A')}",
                f"- **이벤트 유형**: {case_data.get('event_type', 'N/A')}",
                f"- **대응 조치**: {case_data.get('resolution', 'N/A')}",
            ])
        report_parts.append("")
    
    # 대응 매뉴얼 추가
    if manuals:
        report_parts.append("## 📘 권장 대응 매뉴얼")
        for manual in manuals:
            manual_data = manual.get('data', {})
            score = manual.get('score', 0)
            report_parts.extend([
                f"",
                f"### {manual_data.get('title', 'N/A')} (관련도: {score:.1%})",
                f"{manual_data.get('content', 'N/A')}",
            ])
        report_parts.append("")
    
    # 수행된 대응 조치
    if actions:
        report_parts.append("## ✅ 수행된 대응 조치")
        for action in actions:
            report_parts.append(f"- {action}")
        report_parts.append("")
    
    # 보고서 푸터
    report_parts.extend([
        "=" * 60,
        f"보고서 생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "AEGIS AI Agent - LangGraph 기반 분석 시스템",
        "=" * 60
    ])
    
    report = "\n".join(report_parts)
    
    # 이벤트를 벡터 DB에 저장 (나중에 유사 사례로 활용)
    if vector_client and summary:
        try:
            event_id = state.get("event_id", f"evt_{camera_id}_{occurred_at}")
            vector_client.add_event(
                event_id=str(event_id),
                event_data={
                    "camera_id": camera_id,
                    "camera_name": camera_name,
                    "camera_location": camera_location,
                    "event_type": event_type,
                    "risk_level": risk_level,
                    "risk_score": risk_score,
                    "summary": summary,
                    "occurred_at": str(occurred_at),
                    "resolution": ", ".join(actions) if actions else "대응 진행 중"
                }
            )
            logger.info(f"[{camera_id}] 이벤트를 벡터 DB에 저장함")
        except Exception as e:
            logger.warning(f"[{camera_id}] 이벤트 저장 실패: {e}")
    
    logger.info(f"[{camera_id}] RAG 기반 보고서 생성 완료 (유사 사례: {len(similar_cases)}, 매뉴얼: {len(manuals)})")
    
    return {"report": report}
