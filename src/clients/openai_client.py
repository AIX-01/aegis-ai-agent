"""
OpenAI 클라이언트 중앙화 모듈

모든 OpenAI API 호출을 이 모듈을 통해 수행합니다.
- 임베딩: get_embedding()
- 챗: get_chat_completion()
- 비전 챗: get_vision_completion()
"""
import logging
from typing import List, Dict, Any, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)


class OpenAIClientManager:
    """OpenAI 클라이언트 관리자 (싱글톤)"""

    _instance = None
    _default_client: Optional[OpenAI] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        pass

    @classmethod
    def get_client(
        cls,
        api_key: str,
        base_url: Optional[str] = None
    ) -> OpenAI:
        """
        OpenAI 클라이언트를 반환합니다.

        Args:
            api_key: OpenAI API 키
            base_url: 커스텀 base URL (vllm-openai 등)

        Returns:
            OpenAI 클라이언트 인스턴스
        """
        if base_url:
            # 커스텀 엔드포인트 (vllm-openai 등)
            return OpenAI(api_key=api_key, base_url=base_url)
        else:
            # 기본 OpenAI API
            if cls._default_client is None:
                cls._default_client = OpenAI(api_key=api_key)
            return cls._default_client


def get_embedding(
    text: str,
    api_key: str,
    model: str = "text-embedding-3-small"
) -> List[float]:
    """
    텍스트를 임베딩 벡터로 변환합니다.

    Args:
        text: 임베딩할 텍스트
        api_key: OpenAI API 키
        model: 임베딩 모델명

    Returns:
        임베딩 벡터 (List[float])
    """
    client = OpenAIClientManager.get_client(api_key=api_key)
    response = client.embeddings.create(
        model=model,
        input=text
    )
    return response.data[0].embedding


def get_chat_completion(
    messages: List[Dict[str, Any]],
    api_key: str,
    model: str = "gpt-4.1-mini",
    base_url: Optional[str] = None,
    timeout: int = 60
) -> str:
    """
    챗 완성 응답을 반환합니다.

    Args:
        messages: 메시지 리스트 [{"role": "user", "content": "..."}]
        api_key: OpenAI API 키
        model: 모델명
        base_url: 커스텀 base URL (vllm-openai 등)
        timeout: 타임아웃 (초)

    Returns:
        응답 텍스트
    """
    client = OpenAIClientManager.get_client(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        timeout=timeout
    )
    return response.choices[0].message.content


def get_vision_completion(
    prompt: str,
    images_base64: List[str],
    api_key: str,
    model: str = "gpt-4.1-mini",
    base_url: Optional[str] = None,
    timeout: int = 60
) -> str:
    """
    이미지를 포함한 비전 챗 완성 응답을 반환합니다.

    Args:
        prompt: 시스템/유저 프롬프트
        images_base64: base64 인코딩된 이미지 리스트
        api_key: OpenAI API 키
        model: 모델명
        base_url: 커스텀 base URL (vllm-openai 등)
        timeout: 타임아웃 (초)

    Returns:
        응답 텍스트
    """
    # 메시지 content 구성
    content = [{"type": "text", "text": prompt}]

    for img_base64 in images_base64:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{img_base64}"
            }
        })

    client = OpenAIClientManager.get_client(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        timeout=timeout
    )
    return response.choices[0].message.content
