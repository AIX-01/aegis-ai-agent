"""
이벤트 정보를 벡터 스토어에 임베딩하여 저장하는 노드

과거 사례로 저장되어 추후 유사 사례 검색에 활용됩니다.
action 노드와 병렬로 실행됩니다.
"""
import logging
from typing import Dict, Any

from ..state import AnalysisState
from ...clients.vector_store_client import VectorStoreClient
from ...config import Config

logger = logging.getLogger(__name__)

# 컬렉션 이름 상수
PAST_CASES_COLLECTION = "past_cases"

def store_embedding_node(state: AnalysisState, config: Config) -> Dict[str, Any]:
    """
    이벤트 정보를 벡터 스토어에 임베딩하여 저장합니다.

    정밀 분석이 완료되고 ABNORMAL로 확정된 이벤트를 과거 사례로 저장합니다.
    summary + 메타데이터를 결합하여 임베딩하므로, 자연어 검색 시
    카메라 위치, 발생 시각, 이벤트 유형 등으로도 검색이 가능합니다.

    Args:
        state: 현재 분석 상태 (event_id, summary, event_type, risk_score, actions 등)
        config: 시스템 설정

    Returns:
        업데이트된 상태 딕셔너리
    """
    camera_uuid = state["camera_id"]  # camera_id는 실제로 UUID
    camera_name = state.get("camera_name", "")
    camera_location = state.get("camera_location", "")
    event_id = state.get("event_id")
    summary = state.get("summary", "")
    event_type = state.get("event_type", "")
    risk_score = state.get("risk_score", 0.0)
    risk_level = state.get("risk_level", "ABNORMAL")
    occurred_at = state.get("occurred_at")

    # =========================================
    # [추가] response_agent에서 생성된 대응 조치 가져오기
    # =========================================
    # actions는 response_agent의 extract_actions 노드에서 생성됨
    # 형식: [{"type": str, "action": str, "log": str, "triggered_at": str}, ...]
    # 백엔드 EventAction 테이블과 동일한 구조
    actions = state.get("actions", [])

    logger.info(f"[{camera_uuid}] 이벤트 임베딩 저장 시작... (Event ID: {event_id})")

    # summary가 없으면 저장 생략
    if not summary:
        logger.warning(f"[{camera_uuid}] summary가 없어 임베딩 저장을 생략합니다.")
        return {"embedding_stored": False}

    try:
        client = VectorStoreClient(config)

        # 컬렉션 존재 여부 확인 및 생성
        if not client.collection_exists(PAST_CASES_COLLECTION):
            logger.info(f"컬렉션 '{PAST_CASES_COLLECTION}' 생성 중...")
            client.create_collection(PAST_CASES_COLLECTION)

        # 발생 시각 포맷팅
        occurred_at_str = occurred_at.strftime("%Y년 %m월 %d일 %H시 %M분") if occurred_at else "알 수 없음"

        # =========================================
        # 임베딩용 텍스트 구성
        # =========================================
        # 이 텍스트가 OpenAI Embedding API를 통해 1536차원 벡터로 변환되어
        # Qdrant의 'vector' 필드에 저장됩니다.
        #
        # [임베딩 흐름]
        # text_to_embed (문자열)
        #     ↓
        # OpenAI text-embedding-3-small 모델
        #     ↓
        # vector: [0.012, -0.034, 0.056, ...] (1536차원 float 배열)
        #     ↓
        # Qdrant에 저장 (유사도 검색에 사용)
        #
        # [우선순위]
        # summary가 가장 앞에 배치되어 검색 시 가장 높은 영향력을 가짐
        # (임베딩 모델은 텍스트 앞부분에 더 높은 가중치 부여)
        #
        # [검색 시와 동일한 필드 사용]
        # - summary: 상황 요약 (우선순위 1)
        # - camera_name + camera_location: 위치 정보 (우선순위 2)
        # - event_type: 이벤트 유형 (우선순위 3)
        # =========================================
        query_parts = []

        # summary가 가장 중요하므로 맨 앞에 배치
        if summary:
            query_parts.append(f"상황: {summary}")

        # 카메라 정보
        if camera_name or camera_location:
            location_info = f"{camera_name} {camera_location}".strip()
            if location_info:
                query_parts.append(f"위치: {location_info}")

        # 이벤트 유형
        if event_type:
            query_parts.append(f"유형: {event_type}")

        # 최종 임베딩 텍스트 구성
        # 예시: "상황: 1층 로비에서 남성 2인이 폭행 중 | 위치: 주차장 A동 1층 입구 | 유형: ASSAULT"
        text_to_embed = " | ".join(query_parts) if query_parts else summary

        # =========================================
        # Qdrant 저장 데이터 구성
        # =========================================
        # Qdrant에 저장되는 구조:
        # {
        #   id: 123456789 (doc_id 해시값),
        #   vector: [0.012, -0.034, ...] (text_embedded를 임베딩한 1536차원 벡터),
        #   payload: { 아래 doc_data 내용 }
        # }
        #
        # - vector: 유사도 검색에 사용 (임베딩된 벡터)
        # - payload: 메타데이터 저장 (필터링, 결과 표시에 사용)
        # =========================================
        doc_data = {
            "event_id": event_id,
            "camera_uuid": camera_uuid,
            "camera_name": camera_name,           # 필터링 가능 (정확히 일치)
            "camera_location": camera_location,   # 필터링 가능 (정확히 일치)
            "event_type": event_type,             # 필터링 가능 (정확히 일치)
            "risk_level": risk_level,
            "risk_score": risk_score,
            "summary": summary,
            "occurred_at": occurred_at.isoformat() if occurred_at else None,
            "text_embedded": text_to_embed,       # 임베딩된 원본 텍스트 (기록용)
            # =========================================
            # [추가] 대응 조치 정보 (시나리오 1, 2 활용)
            # =========================================
            # response_agent에서 생성된 대응 조치 리스트
            # 형식: [{"type": str, "action": str, "log": str, "triggered_at": str}, ...]
            # 백엔드 EventAction 테이블과 동일한 구조
            #
            # 활용:
            # - 시나리오 1: 유사 상황에서 어떤 대응을 했는지 참조
            # - 시나리오 2: 장소별 대응 이력 패턴 분석
            "actions": actions,
        }

        # 문서 추가
        # text_field="text_embedded" → 이 필드의 값이 임베딩되어 vector로 저장됨
        client.add_document(
            collection_name=PAST_CASES_COLLECTION,
            doc_id=event_id or f"{camera_uuid}_{occurred_at}",
            data=doc_data,
            text_field="text_embedded"
        )

        logger.info(f"[{camera_uuid}] 이벤트 임베딩 저장 완료 (Event ID: {event_id}, Actions: {len(actions)}개)")
        return {"embedding_stored": True}

    except Exception as e:
        logger.error(f"[{camera_uuid}] 이벤트 임베딩 저장 실패: {e}", exc_info=True)
        return {
            "embedding_stored": False,
            "errors": state.get("errors", []) + [f"Store embedding exception: {e}"]
        }

