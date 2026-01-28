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
    # [실제 운영 시 변경] 실제 VLM 서버 주소 (예: "http://192.168.1.100:8000/analyze")
    vlm_endpoint: str = "http://localhost:8001/analyze"

    # 정밀 분석 엔드포인트
    # [실제 운영 시 변경] 실제 정밀 분석 서버 주소
    precision_endpoint: str = "http://localhost:8002/precision_analyze"

    # VLM용 저해상도 프레임 설정
    frame_width: int = 640
    frame_height: int = 360
    jpeg_quality: int = 60

    # 정밀 분석용 고해상도 프레임 설정
    precision_frame_width: int = 1920
    precision_frame_height: int = 1080
    precision_jpeg_quality: int = 85

    fps: int = 1

    # 윈도우 설정
    window_size: int = 8  # 초
    window_slide: int = 3  # 초

    # 큐 관리
    queue_max_size: int = 20

    # Pending buffer 관리
    buffer_timeout: int = 60  # 초 - VLM 응답 대기 타임아웃

    # Mock 서버
    # [실제 운영 시 변경] False로 설정하여 실제 서버와 통신
    mock_mode: bool = True
    mock_vlm_port: int = 8001  # VLM 트리거 서버 포트
    mock_precision_port: int = 8002  # 정밀 분석 서버 포트

    # 로깅
    log_level: str = "INFO"

    # 네트워크
    vlm_timeout: int = 30  # 초
    vlm_max_retries: int = 3
    vlm_retry_delay: float = 1.0  # 초, 지수 백오프 기반

    precision_timeout: int = 60  # 초 - 정밀 분석 타임아웃
    precision_max_retries: int = 3
    precision_retry_delay: float = 1.0

    # 스트림 재연결
    reconnect_delay: float = 2.0  # 초, 지수 백오프 기반
    max_reconnect_delay: float = 60.0  # 초

    # Redis 설정
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    redis_analysis_cameras_key: str = "analysis:cameras"
    redis_update_channel: str = "camera:analysis:update"


# 프레임 추출 상수
FRAME_CAPTURE_INTERVAL = 1.0  # 초 (1 FPS)

# 큐 작업 형식
TASK_KEYS = ['camera_id', 'low_res_frames', 'high_res_frames', 'timestamp', 'window_start', 'window_end']

# VLM 트리거 조건
TRIGGER_CATEGORIES = ['abnormal', '이상']
