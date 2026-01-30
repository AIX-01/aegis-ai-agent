"""
AEGIS AI Agent 설정 모듈
"""
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Config:
    """시스템 설정"""

    # =========================================
    # 모드 설정
    # =========================================
    # True로 설정 시, 외부 서버 없이 내장된 모의 서버로 전체 파이프라인을 테스트합니다.
    # False로 설정 시, 아래에 정의된 실제 서버 엔드포인트 주소를 사용합니다.
    mock_mode: bool = True

    # =========================================
    # 실제 서버 엔드포인트 (mock_mode=False일 때 사용)
    # =========================================
    vlm_endpoint: str = "http://localhost:8001/analyze"
    precision_endpoint: str = "http://localhost:8002/precision_analyze"
    backend_endpoint: str = "http://localhost:8080/api/vlm-results"

    # =========================================
    # 모의 서버 설정 (mock_mode=True일 때 사용)
    # =========================================
    mock_vlm_port: int = 8001
    mock_precision_port: int = 8002
    mock_backend_port: int = 8088  # 백엔드 목 서버 포트 변경 (8080 -> 8088)

    # =========================================
    # RTSP 및 프레임 처리 설정
    # =========================================
    rtsp_host: str = "127.0.0.1"
    rtsp_port: int = 8554
    frame_width: int = 640
    frame_height: int = 360
    jpeg_quality: int = 60
    fps: int = 1

    # =========================================
    # 분석 파이프라인 설정
    # =========================================
    num_workers: int = 4
    window_size: int = 8  # 초
    window_slide: int = 4  # 초 (50% 오버랩)
    flush_timeout: int = 30  # 초
    min_flush_size: int = 5   # 초
    queue_max_size: int = 20

    # =========================================
    # 네트워크 및 재시도 설정
    # =========================================
    vlm_timeout: int = 30
    vlm_max_retries: int = 3
    vlm_retry_delay: float = 1.0
    precision_timeout: int = 60
    precision_max_retries: int = 3
    precision_retry_delay: float = 1.0
    backend_timeout: int = 10
    backend_max_retries: int = 3
    backend_retry_delay: float = 1.0
    reconnect_delay: float = 2.0
    max_reconnect_delay: float = 60.0

    # =========================================
    # Redis 설정
    # =========================================
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    redis_analysis_cameras_key: str = "analysis:cameras"
    redis_update_channel: str = "camera:analysis:update"
    
    # =========================================
    # 로깅 설정
    # =========================================
    log_level: str = "INFO"

    def __post_init__(self):
        """
        초기화 후 실행되는 로직.
        mock_mode가 True이면, 모든 엔드포인트를 모의 서버 주소로 강제 설정합니다.
        """
        if self.mock_mode:
            self.vlm_endpoint = f"http://localhost:{self.mock_vlm_port}/analyze"
            self.precision_endpoint = f"http://localhost:{self.mock_precision_port}/precision_analyze"
            self.backend_endpoint = f"http://localhost:{self.mock_backend_port}/api/vlm-results"

# =========================================
# 분석 트리거 상수
# =========================================
TRIGGER_CATEGORIES = ['abnormal', '이상']
