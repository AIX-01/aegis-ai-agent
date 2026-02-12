"""
지식 검색 노드 (search_knowledge)

대응 매뉴얼과 과거 유사 사례를 검색하여 LLM에게 컨텍스트를 제공합니다.
ReAct 루프 진입 전에 무조건 실행되어 검색을 보장합니다.
"""
import logging
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ....config import Config
    from ..state import ResponseAgentState

logger = logging.getLogger(__name__)


def search_knowledge_node(state: "ResponseAgentState", config: "Config") -> Dict[str, Any]:
    """
    대응 매뉴얼과 과거 유사 사례를 검색하는 노드

    [역할]
    ReAct 루프 진입 전에 무조건 실행되어 LLM에게 필요한 지식 컨텍스트를 제공합니다.
    기존 search_protocol_and_cases 도구의 로직을 노드로 분리하여 실행을 보장합니다.

    [검색 대상]
    1. 과거 유사 사례 (Qdrant 벡터 검색)
    2. 대응 매뉴얼 (이벤트 유형별 하드코딩)

    Args:
        state: 현재 에이전트 상태
        config: 시스템 설정

    Returns:
        업데이트된 상태 (rag_references, knowledge_context 포함)
    """
    from ....tools.manual_templates import get_manual
    from ....clients.vector_store_client import VectorStoreClient

    # 상태에서 검색에 필요한 정보 추출
    summary = state.get("summary", "")
    event_type = state.get("event_type", "")
    camera_name = state.get("camera_name", "")
    camera_location = state.get("camera_location", "")
    camera_id = state.get("camera_id", "")

    logger.info(f"[{camera_id}] 지식 검색 노드 시작... (event_type: {event_type})")

    rag_references = []
    knowledge_text = ""

    # =========================================
    # 1. 검색 쿼리 구성
    # =========================================
    # 저장 시와 동일한 형식으로 쿼리를 구성하여 검색 정확도를 높임
    # - summary: 상황 요약 (우선순위 1)
    # - camera_name + camera_location: 위치 정보 (우선순위 2)
    # - event_type: 이벤트 유형 (우선순위 3)
    query_parts = []

    if summary:
        query_parts.append(f"상황: {summary}")
    if camera_name or camera_location:
        location_info = f"{camera_name} {camera_location}".strip()
        if location_info:
            query_parts.append(f"위치: {location_info}")
    if event_type:
        query_parts.append(f"유형: {event_type}")

    query = " | ".join(query_parts) if query_parts else summary

    # =========================================
    # 2. 과거 사례 검색 (Qdrant 벡터 유사도 검색)
    # =========================================
    try:
        client = VectorStoreClient(config)

        if client.collection_exists("past_cases"):
            past_results = client.search(
                collection_name="past_cases",
                query=query,
                limit=3,
                filters={"event_type": event_type} if event_type else None
            )

            if past_results:
                knowledge_text += "## 과거 유사 사례\n\n"
                for i, result in enumerate(past_results, 1):
                    payload = result.get("data", {})
                    score = result.get("score", 0)
                    knowledge_text += f"### 사례 {i} (유사도: {score:.2f})\n"
                    knowledge_text += f"- 카메라: {payload.get('camera_name', '')} ({payload.get('camera_location', '')})\n"
                    knowledge_text += f"- 이벤트: {payload.get('event_type', '')}\n"
                    knowledge_text += f"- 발생시각: {payload.get('occurred_at', '')}\n"

                    # =========================================
                    # 시간대/요일 패턴 표시
                    # =========================================
                    # LLM이 시간대 및 요일 패턴을 분석할 수 있도록 표시
                    hour = payload.get('hour_of_day')
                    day = payload.get('day_of_week')
                    day_names = ['월', '화', '수', '목', '금', '토', '일']
                    if hour is not None:
                        day_str = f" ({day_names[day]}요일)" if day is not None else ""
                        knowledge_text += f"- 발생 시간대: {hour}시{day_str}\n"

                    knowledge_text += f"- 상황: {payload.get('summary', '')}\n"

                    # =========================================
                    # 과거 대응 조치 표시 (event_actions 테이블 스키마와 일치)
                    # =========================================
                    # actions 필드가 있으면 LLM이 참조할 수 있도록 표시
                    # 형식: [{"action": "BROADCAST", "description": "...", "user_id": ...}, ...]
                    past_actions = payload.get('actions', [])
                    if past_actions:
                        knowledge_text += "- 대응조치:\n"
                        for action in past_actions:
                            action_code = action.get('action', 'unknown')
                            action_desc = action.get('description', '')
                            user_id = action.get('user_id')
                            # description이 너무 길면 첫 100자만 표시
                            if len(action_desc) > 100:
                                action_desc = action_desc[:100] + "..."
                            # HITL 승인 여부 표시
                            user_info = " (사용자 승인)" if user_id else ""
                            knowledge_text += f"  - [{action_code}] {action_desc}{user_info}\n"
                    knowledge_text += "\n"

                rag_references.append({
                    "type": "past_cases",
                    "content": knowledge_text,
                    "count": len(past_results)
                })
                logger.info(f"[{camera_id}] 과거 사례 {len(past_results)}건 검색 완료")
            else:
                knowledge_text += "## 과거 유사 사례\n검색 결과 없음\n\n"
                logger.info(f"[{camera_id}] 과거 사례 검색 결과 없음")
        else:
            knowledge_text += "## 과거 유사 사례\n컬렉션이 존재하지 않습니다.\n\n"
            logger.warning(f"[{camera_id}] past_cases 컬렉션 미존재")

    except Exception as e:
        logger.error(f"[{camera_id}] 과거 사례 검색 실패: {e}")
        knowledge_text += f"## 과거 유사 사례\n검색 실패: {e}\n\n"

    # =========================================
    # 3. 대응 매뉴얼 조회 (이벤트 유형별)
    # =========================================
    manual_text = get_manual(event_type)
    knowledge_text += "\n" + manual_text

    rag_references.append({
        "type": "manual",
        "content": manual_text
    })
    logger.info(f"[{camera_id}] 대응 매뉴얼 조회 완료 (event_type: {event_type})")

    return {
        "rag_references": rag_references,
        "knowledge_context": knowledge_text
    }

