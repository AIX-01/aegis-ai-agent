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
            # =========================================
            # 같은 event_type 내 최근 5건 검색
            # =========================================
            # 1) Qdrant에서 event_type 필터 + limit=20으로 넉넉히 검색
            # 2) occurred_at 기준 최신순 정렬 (Python)
            # 3) 상위 5건만 사용
            MAX_RECENT_CASES = 5
            raw_results = client.search(
                collection_name="past_cases",
                query=query,
                limit=20,
                filters={"event_type": event_type} if event_type else None
            )

            # occurred_at 기준 최신순 정렬 후 상위 N건
            if raw_results:
                raw_results.sort(
                    key=lambda r: r.get("data", {}).get("occurred_at", ""),
                    reverse=True
                )
            past_results = raw_results[:MAX_RECENT_CASES]

            if past_results:
                result_count = len(past_results)
                knowledge_text += f"## 과거 유사 사례 (최근 {result_count}건)\n\n"

                # 5건 미만인 경우 LLM에게 알림
                if result_count < MAX_RECENT_CASES:
                    knowledge_text += f"> 참고: 동일 유형({event_type}) 과거 사례가 {result_count}건뿐입니다. 대응 매뉴얼을 우선 참고하세요.\n\n"

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
                    hour = payload.get('hour_of_day')
                    day = payload.get('day_of_week')
                    day_names = ['월', '화', '수', '목', '금', '토', '일']
                    if hour is not None:
                        day_str = f" ({day_names[day]}요일)" if day is not None else ""
                        knowledge_text += f"- 발생 시간대: {hour}시{day_str}\n"

                    knowledge_text += f"- 상황: {payload.get('summary', '')}\n"

                    # =========================================
                    # 과거 대응 조치 표시
                    # =========================================
                    past_actions = payload.get('actions', [])
                    if past_actions:
                        knowledge_text += "- 대응조치:\n"
                        for action in past_actions:
                            action_code = action.get('action', 'unknown')
                            action_desc = action.get('description', '')
                            user_id = action.get('user_id')
                            if len(action_desc) > 100:
                                action_desc = action_desc[:100] + "..."
                            user_info = " (사용자 승인)" if user_id else ""
                            knowledge_text += f"  - [{action_code}] {action_desc}{user_info}\n"
                    knowledge_text += "\n"

                rag_references.append({
                    "type": "past_cases",
                    "content": knowledge_text,
                    "count": result_count
                })
                logger.info(f"[{camera_id}] 과거 사례 {result_count}건 검색 완료 (최근순, 최대 {MAX_RECENT_CASES}건)")
            else:
                knowledge_text += f"## 과거 유사 사례\n동일 유형({event_type}) 과거 사례가 없습니다. 대응 매뉴얼을 참고하여 판단하세요.\n\n"
                logger.info(f"[{camera_id}] 과거 사례 검색 결과 없음 (event_type: {event_type})")
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

