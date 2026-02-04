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
    
    # 백엔드 엔드포인트 분리 (생성용 / 갱신용)
    # 갱신용 URL에는 {event_id} 플레이스홀더를 사용할 수 있습니다.
    
    # 1차 분석 후 '이상' 또는 '의심'일 때, 새로운 이벤트를 생성(CREATE)하기 위해 사용
    _real_backend_create_endpoint: str = "http://localhost:8080/internal/agent/events"
    # 2차 정밀 분석이 끝난 후 또는 '의심' 상태를 최종 기록할 때, 기존 이벤트의 내용을 갱신(UPDATE)하기 위해 사용
    _real_backend_update_endpoint: str = "http://localhost:8080/internal/agent/events/{event_id}/analysis"
    # 생성된 영상 클립의 경로를 백엔드에 업데이트(CLIP UPDATE)하기 위해 사용
    _real_backend_clip_endpoint: str = "http://localhost:8080/internal/agent/events/{event_id}/clip"

    # ===================================================================
    # >> 2. 모드 설정 (이 값만 True/False로 변경하여 모드를 전환하세요)
    # ===================================================================
    # True: 내장된 모의 서버 사용 (로컬 테스트용)
    # False: 위에 설정한 실제 서버 주소 사용 (운영용)
    mock_mode: bool = True
    
    # 개별 컴포넌트의 실제 서버 사용 여부 (기본값: False -> Mock 사용)
    # app.py에서 CLI 인자에 따라 동적으로 설정됩니다.
    real_vlm: bool = False
    real_precision: bool = False
    real_backend: bool = False
    real_s3: bool = False # S3 실제 서버 사용 여부 추가

    # ===================================================================
    # >> 3. 활성 엔드포인트 (수정 금지 - __post_init__에서 자동 설정됨)
    # ===================================================================
    vlm_endpoint: str = field(init=False)
    precision_endpoint: str = field(init=False)
    backend_create_endpoint: str = field(init=False)
    backend_update_endpoint: str = field(init=False)
    backend_clip_endpoint: str = field(init=False) # 추가됨

    # =========================================
    # 에이전트 API 서버 설정 (FastAPI)
    # =========================================
    agent_api_host: str = "0.0.0.0"
    agent_api_port: int = 8000

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
    # 비디오 패킷 버퍼링 시간 (초): 이상 행동 감지 시 추출할 영상의 최대 길이를 결정합니다
    video_buffer_seconds: int = 30



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
        mock_mode 및 개별 real_* 플래그 값에 따라 활성 엔드포인트를 동적으로 설정합니다.
        """
        # VLM 엔드포인트 설정
        if self.real_vlm:
            self.vlm_endpoint = self._real_vlm_endpoint
        else:
            self.vlm_endpoint = f"http://localhost:{self.mock_vlm_port}/analyze"

        # 정밀 분석 엔드포인트 설정
        if self.real_precision:
            self.precision_endpoint = self._real_precision_endpoint
        else:
            self.precision_endpoint = f"http://localhost:{self.mock_precision_port}/precision_analyze"

        # 백엔드 엔드포인트 설정 (생성/갱신/클립 분리)
        if self.real_backend:
            self.backend_create_endpoint = self._real_backend_create_endpoint
            self.backend_update_endpoint = self._real_backend_update_endpoint
            self.backend_clip_endpoint = self._real_backend_clip_endpoint
        else:
            # Mock 서버는 RESTful 규칙을 따르므로 기본 경로 설정
            base_url = f"http://localhost:{self.mock_backend_port}/api/vlm-results"
            self.backend_create_endpoint = base_url
            self.backend_update_endpoint = f"{base_url}/{{event_id}}/analysis"
            self.backend_clip_endpoint = f"{base_url}/{{event_id}}/clip"
