"""
검색(Retrieval) 관련 도구 모음
- 대응 매뉴얼 검색
- 유사 과거 사례 검색
"""
import logging

logger = logging.getLogger(__name__)

def search_manual(query: str) -> str:
    """
    대응 매뉴얼을 검색합니다.
    (TODO: LangChain 도구로 구현 예정)
    """
    logger.warning(f"매뉴얼 검색 도구가 호출되었으나, 아직 구현되지 않았습니다: {query}")
    return "매뉴얼 검색 기능은 아직 구현되지 않았습니다."

def search_past_cases(query: str) -> str:
    """
    유사 과거 사례를 검색합니다.
    (TODO: LangChain 도구로 구현 예정)
    """
    logger.warning(f"유사 과거 사례 검색 도구가 호출되었으나, 아직 구현되지 않았습니다: {query}")
    return "유사 과거 사례 검색 기능은 아직 구현되지 않았습니다."
