"""
임베딩(Embedding) 관련 도구 모음

OpenAI Embedding API를 사용하여 텍스트를 벡터로 변환합니다.
LangGraph 노드에서 직접 호출하거나, 다른 툴에서 사용할 수 있습니다.

사용 예시:
    from src.tools.embedding_tools import get_text_embedding, get_batch_embeddings
    from src.config import Config

    config = Config()

    # 단일 텍스트 임베딩
    vector = get_text_embedding("검색할 텍스트", config)

    # 배치 임베딩
    texts = ["텍스트1", "텍스트2", "텍스트3"]
    vectors = get_batch_embeddings(texts, config)
"""
import logging
from typing import List, Optional, TYPE_CHECKING

from ..clients.openai_client import get_embedding

if TYPE_CHECKING:
    from ..config import Config

logger = logging.getLogger(__name__)


def get_text_embedding(
    text: str,
    config: "Config",
    model: Optional[str] = None
) -> List[float]:
    """
    텍스트를 임베딩 벡터로 변환합니다.

    Args:
        text: 임베딩할 텍스트
        config: Config 인스턴스 (API 키, 모델 설정 포함)
        model: 임베딩 모델명 (None이면 config 기본값 사용)

    Returns:
        임베딩 벡터 (List[float])

    Raises:
        ValueError: API 키가 설정되지 않은 경우
        Exception: OpenAI API 호출 실패 시
    """
    if not config.openai_api_key:
        raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")

    embedding_model = model or config.openai_embedding_model

    logger.debug(f"텍스트 임베딩 시작: 모델={embedding_model}, 길이={len(text)}")

    try:
        vector = get_embedding(
            text=text,
            api_key=config.openai_api_key,
            model=embedding_model
        )
        logger.debug(f"텍스트 임베딩 완료: 차원={len(vector)}")
        return vector

    except Exception as e:
        logger.error(f"텍스트 임베딩 실패: {e}")
        raise


def get_batch_embeddings(
    texts: List[str],
    config: "Config",
    model: Optional[str] = None
) -> List[List[float]]:
    """
    여러 텍스트를 배치로 임베딩합니다.

    Args:
        texts: 임베딩할 텍스트 리스트
        config: Config 인스턴스
        model: 임베딩 모델명 (None이면 config 기본값 사용)

    Returns:
        임베딩 벡터 리스트 (List[List[float]])

    Note:
        현재는 순차 처리입니다. 대량 처리 시 OpenAI Batch API 사용을 권장합니다.
    """
    if not texts:
        return []

    logger.info(f"배치 임베딩 시작: {len(texts)}개 텍스트")

    vectors = []
    for i, text in enumerate(texts):
        try:
            vector = get_text_embedding(text, config, model)
            vectors.append(vector)
        except Exception as e:
            logger.error(f"배치 임베딩 실패 (인덱스 {i}): {e}")
            raise

    logger.info(f"배치 임베딩 완료: {len(vectors)}개 벡터")
    return vectors


def calculate_similarity(
    vector1: List[float],
    vector2: List[float]
) -> float:
    """
    두 벡터 간의 코사인 유사도를 계산합니다.

    Args:
        vector1: 첫 번째 벡터
        vector2: 두 번째 벡터

    Returns:
        코사인 유사도 (-1.0 ~ 1.0)
    """
    if len(vector1) != len(vector2):
        raise ValueError(f"벡터 차원이 다릅니다: {len(vector1)} vs {len(vector2)}")

    dot_product = sum(a * b for a, b in zip(vector1, vector2))
    norm1 = sum(a * a for a in vector1) ** 0.5
    norm2 = sum(b * b for b in vector2) ** 0.5

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return dot_product / (norm1 * norm2)

