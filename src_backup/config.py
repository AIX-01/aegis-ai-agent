"""
AEGIS AI Agent 설정 모듈
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Config:
    """시스템 설정"""

    # RTSP 스트림 호스트 및 포트
    rtsp_host: str = "127.0.0.1"  # localhost 대신 IP 직접 사용
    rtsp_port: int = 8554

    # Consumer 설정
    num_workers: int = 4

    # VLM 트리거 엔드포인트
    vlm_endpoint: str = "http://localhost:8001/analyze"

    # 정밀 분석 엔드포인트
    precision_endpoint: str = "http://localhost:8002/precision_analyze"

    # 스프링부트 백엔드 엔드포인트
    backend_endpoint: str = "http://localhost:8080/api/vlm-results" # VLM 결과를 전송할 백엔드 주소

    # VLM용 저해상도 프레임 설정
    frame_width: int = 640
    frame_height: int = 360
    jpeg_quality: int = 60

    fps: int = 1

    # 윈도우 설정
    window_size: int = 8  # 초
    window_slide: int = 4  # 초 (윈도우 크기의 절반, 50% 오버랩)
    flush_timeout: int = 30  # 초, 이 시간 동안 새 프레임이 없으면 버퍼 강제 처리
    min_flush_size: int = 5   # 초, 강제 처리 시 필요한 최소 프레임 수

    # 큐 관리
    queue_max_size: int = 20

    # Mock 서버
    mock_mode: bool = True
    mock_vlm_port: int = 8001
    mock_precision_port: int = 8002

    # 로깅
    log_level: str = "INFO"

    # 네트워크 타임아웃 및 재시도 설정
    vlm_timeout: int = 30
    vlm_max_retries: int = 3
    vlm_retry_delay: float = 1.0

    precision_timeout: int = 60
    precision_max_retries: int = 3
    precision_retry_delay: float = 1.0

    backend_timeout: int = 10
    backend_max_retries: int = 3
    backend_retry_delay: float = 1.0

    # 스트림 재연결
    reconnect_delay: float = 2.0
    max_reconnect_delay: float = 60.0

    # Redis 설정
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    redis_analysis_cameras_key: str = "analysis:cameras"
    redis_update_channel: str = "camera:analysis:update"


# 프레임 추출 상수
FRAME_CAPTURE_INTERVAL = 1.0  # 초 (1 FPS)

# VLM 트리거 조건
TRIGGER_CATEGORIES = ['abnormal', '이상']
