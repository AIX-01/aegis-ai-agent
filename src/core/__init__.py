"""
Core 패키지: 실시간 영상 처리 및 1차 분석

이 패키지는 [1단계] 실시간 영상 처리를 담당합니다:
- Producer: RTSP 카메라 영상 프레임 캡처
- WindowManager: 프레임 윈도우 구성
- QueueManager: 작업 큐 관리
- Consumer: VLM 1차 분석, 백엔드 보고, LangGraph 파이프라인 트리거
- RedisManager: 동적 카메라 관리
"""

from .producer import FrameProducer
from .consumer import ConsumerPool
from .windowing import WindowManager
from .queue_manager import QueueManager
from .redis_manager import RedisManager

__all__ = [
    "FrameProducer",
    "ConsumerPool",
    "WindowManager",
    "QueueManager",
    "RedisManager",
]
