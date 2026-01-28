"""
로깅, 오류 처리 및 헬퍼 작업을 위한 유틸리티 함수들
"""
import logging
import sys
from typing import Optional
import signal


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """
    구조화된 형식으로 로깅을 설정합니다.

    Args:
        log_level: 로깅 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Returns:
        설정된 로거 인스턴스
    """
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"잘못된 로그 레벨: {log_level}")

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)8s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    return logging.getLogger("aegis-agent")


def setup_signal_handlers(shutdown_callback):
    """
    SIGINT 및 SIGTERM에 대한 정상 종료(graceful shutdown) 핸들러를 설정합니다.

    Args:
        shutdown_callback: 종료 신호 시 호출할 함수
    """

    def signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        logging.info(f"{sig_name} 수신, 정상 종료를 시작합니다...")
        shutdown_callback()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def get_camera_id(srt_url: str, index: int) -> str:
    """
    SRT URL에서 카메라 ID를 추출하거나 인덱스에서 생성합니다.

    Args:
        srt_url: SRT 스트림 URL
        index: 카메라 인덱스

    Returns:
        카메라 식별자
    """
    # SRT URL에서 경로를 추출하려고 시도합니다.
    # 형식: srt://host:port?streamid=camera_name
    if "streamid=" in srt_url:
        try:
            stream_id = srt_url.split("streamid=")[1].split("&")[0]
            return stream_id
        except Exception:
            pass

    # 인덱스 기반 이름으로 대체(fallback)합니다.
    return f"camera_{index + 1}"


def exponential_backoff(
    attempt: int, base_delay: float, max_delay: Optional[float] = None
) -> float:
    """
    지수 백오프(exponential backoff) 지연 시간을 계산합니다.

    Args:
        attempt: 현재 시도 횟수 (0부터 시작)
        base_delay: 기본 지연 시간 (초)
        max_delay: 최대 지연 시간 상한 (초)

    Returns:
        지연 시간 (초)
    """
    delay = base_delay * (2**attempt)
    if max_delay is not None:
        delay = min(delay, max_delay)
    return delay
