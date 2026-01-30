"""
AEGIS AI Agent 설정 모듈
"""
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Config:
    """
    AEGIS AI Agent의 모든 설정을 관리하는 중앙 클래스입니다.
    실제 서버 주소를 한 번만 설정해두면, mock_mode 값만 변경하여
    테스트 모드와 실제 운영 모드를 쉽게 전환할 수 있습니다.
    """

    # ===================================================================
    # >> 1. 실제 서버 주소 설정 (이 부분을 실제 운영 서버에 맞게 수정하세요)
    # ===================================================================
    _real_vlm_endpoint: str = "http://<실제 VLM 서버 IP>:8001/analyze"
    _real_precision_endpoint: str = "http://<실제 LLM 서버 IP>:8002/precision_analyze"
    _real_backend_endpoint: str = "http://<실제 백엔드 서버 IP>:8080/api/vlm-results"

    # ===================================================================
    # >> 2. 모드 설정 (이 값만 True/False로 변경하여 모드를 전환하세요)
    # ===================================================================
    # True: 내장된 모의 서버 사용 (로컬 테스트용)
    # False: 위에 설정한 실제 서버 주소 사용 (운영용)
    mock_mode: bool = True

    # ===================================================================
    # >> 3. 활성 엔드포인트 (수정 금지 - __post_init__에서 자동 설정됨)
    # ===================================================================
    vlm_endpoint: str = field(init=False)
    precision_endpoint: str = field(init=False)
    backend_endpoint: str = field(init=False)

    # =========================================
    # 모의 서버 포트 설정 (mock_mode=True일 때 사용)
    # =========================================
    mock_vlm_port: int = 8001
    mock_precision_port: int = 8002
    mock_backend_port: int = 8088

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
    window_size: int = 8
    window_slide: int = 4
    flush_timeout: int = 30
    min_flush_size: int = 5
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
        mock_mode 값에 따라 활성 엔드포인트를 동적으로 설정합니다.
        """
        if self.mock_mode:
            self.vlm_endpoint = f"http://localhost:{self.mock_vlm_port}/analyze"
            self.precision_endpoint = f"http://localhost:{self.mock_precision_port}/precision_analyze"
            self.backend_endpoint = f"http://localhost:{self.mock_backend_port}/api/vlm-results"
        else:
            self.vlm_endpoint = self._real_vlm_endpoint
            self.precision_endpoint = self._real_precision_endpoint
            self.backend_endpoint = self._real_backend_endpoint

# =========================================
# 분석 트리거 상수
# =========================================
TRIGGER_CATEGORIES = ['abnormal', '이상']
