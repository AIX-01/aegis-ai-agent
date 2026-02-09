"""
AEGIS AI Agent 설정 모듈
"""
import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()


@dataclass
class Config:
    """
    AEGIS AI Agent의 모든 설정을 관리하는 중앙 클래스입니다.
    개별 real_* 플래그로 컴포넌트별 실제/Mock 서버를 전환합니다.
    """

    # ===================================================================
    # >> 1. 실제 서버 주소 설정 (이 부분을 실제 운영 서버에 맞게 수정하세요)
    # ===================================================================
    _real_vlm_endpoint: str = "https://apsj89ztypyzpr-8000.proxy.runpod.net/v1"
    _real_vlm_api_key: str = "sk-IrR7Bwxtin0haWagUnPrBgq5PurnUz86"
    _real_vlm_model_id: str = "AIX-01/Qwen3-VL-2B-Instruct-unsloth-bnb-4bit-3000steps-r64-b8-merged-16bit"
    # precision_client.py가 OpenAI Chat API (get_vision_completion)를 사용하도록 리팩토링됨
    # _real_precision_endpoint: str = "http://<실제 LLM 서버 IP>:8002/precision_analyze"

    # 백엔드 엔드포인트 분리 (생성용 / 갱신용)
    # 갱신용 URL에는 {event_id} 플레이스홀더를 사용할 수 있습니다.
    
    # 1차 분석 후 '이상' 또는 '의심'일 때, 새로운 이벤트를 생성(CREATE)하기 위해 사용
    _real_backend_create_endpoint: str = "http://localhost:8080/internal/agent/events"
    # 2차 정밀 분석이 끝난 후 또는 '의심' 상태를 최종 기록할 때, 기존 이벤트의 내용을 갱신(UPDATE)하기 위해 사용
    _real_backend_update_endpoint: str = "http://localhost:8080/internal/agent/events/{event_id}/analysis"
    # 생성된 영상 클립의 경로를 백엔드에 업데이트(CLIP UPDATE)하기 위해 사용
    _real_backend_clip_endpoint: str = "http://localhost:8080/internal/agent/events/{event_id}/clip"

    # ===================================================================
    # >> 2. 모드 설정 (컴포넌트별 True/False로 전환)
    # ===================================================================
    # 개별 컴포넌트의 실제 서버 사용 여부 (기본값: False -> Mock 사용)
    # - 여기서 True로 설정하면 CLI 플래그 없이도 항상 실제 서버 사용
    # - CLI 플래그(--real-vlm 등)는 False → True 전환만 가능 (True → False 불가)
    real_vlm: bool = False
    real_precision: bool = False
    real_backend: bool = False

    # ===================================================================
    # >> 3. 활성 엔드포인트 (수정 금지 - __post_init__에서 자동 설정됨)
    # ===================================================================
    vlm_endpoint: str = field(init=False)
    vlm_api_key: Optional[str] = field(init=False, default=None)
    vlm_model_id: str = field(init=False, default="vlm")
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
    # 모의 서버 포트 설정 (real_*=False인 컴포넌트에 사용)
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
    window_slide: int = 8
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

    # =========================================
    # OpenAI API 설정
    # =========================================
    # API 키는 .env 파일에서 OPENAI_API_KEY로 설정
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))

    # 임베딩 설정 (vector_store용)
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimension: int = 1536

    # 챗 설정 (precision용)
    openai_chat_model: str = "gpt-4.1-mini"
    openai_chat_timeout: int = 60

    # =========================================
    # Qdrant 벡터 DB 설정
    # =========================================
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_timeout: int = 30

    # =========================================
    # VLM 시스템 프롬프트
    # =========================================
    vlm_system_prompt: str = """You are a video incident classifier.

Input: frames at 1 FPS in chronological order. Predict what situation is occurring next.

Output exactly:
class1=<normal|suspicious|abnormal>
class2=<assault|burglary|dump|swoon|vandalism>

No extra text."""

    # =========================================
    # Precision 분석 시스템 프롬프트
    # =========================================
    precision_system_prompt: str = """당신은 CCTV 영상 분석 전문가입니다.

## 분석 지침
1. 제공된 이미지들을 분석하여 상황을 파악하세요.
2. 1차 VLM 분석 결과를 참고하되, 이미지 기반으로 최종 판단하세요.

## 출력 형식 (JSON만 출력)
{
  "event_type": "ASSAULT|BURGLARY|DUMP|SWOON|VANDALISM|UNKNOWN",
  "summary": "상황을 2-3문장으로 요약 (한국어)",
  "risk_score": 0.0~1.0
}

## 이벤트 유형 정의
- ASSAULT: 폭행, 싸움, 물리적 충돌
- BURGLARY: 절도, 침입, 무단 침입
- DUMP: 쓰레기 무단 투기
- SWOON: 실신, 쓰러짐, 의료 응급상황
- VANDALISM: 기물 파손, 낙서
- UNKNOWN: 분류 불가 또는 정상 상황

JSON만 출력하세요."""

    # =========================================
    # Verification 검증 시스템 프롬프트
    # =========================================
    verification_system_prompt: str = """당신은 CCTV 영상의 위험도를 최종 판단하는 검증 전문가입니다.

## 상황
현재 1차 VLM 분석에서 "SUSPICIOUS(의심)" 상태로 판정되었습니다.
이 상태를 "ABNORMAL(이상)"로 격상할지, "SUSPICIOUS(의심)"를 유지할지 판단해주세요.

## 판단 기준
- ABNORMAL로 격상: 명확한 이상 행동이 보이거나, 잠재적 위험이 높은 경우
- SUSPICIOUS 유지: 확실한 이상 징후는 없지만, 계속 주시가 필요한 경우

## 출력 형식 (JSON만 출력)
{
  "risk_level": "ABNORMAL|SUSPICIOUS",
  "reason": "판단 이유를 한 문장으로 작성"
}

JSON만 출력하세요."""

    # Verification 재시도 설정
    verification_max_retries: int = 3
    verification_retry_delay: float = 1.0

    # =========================================
    # LangSmith 추적 설정 (팀원별 .env에서 LANGSMITH_PROJECT 변경)
    # =========================================
    langsmith_tracing: bool = field(default_factory=lambda: os.getenv("LANGSMITH_TRACING", "false").lower() == "true")
    langsmith_api_key: str = field(default_factory=lambda: os.getenv("LANGSMITH_API_KEY", ""))
    langsmith_project: str = field(default_factory=lambda: os.getenv("LANGSMITH_PROJECT", "aegis-default"))

    def __post_init__(self):
        """
        초기화 후 실행되는 로직.
        개별 real_* 플래그 값에 따라 활성 엔드포인트를 동적으로 설정합니다.
        """
        # VLM 엔드포인트 설정
        if self.real_vlm:
            self.vlm_endpoint = self._real_vlm_endpoint
            self.vlm_api_key = self._real_vlm_api_key
            self.vlm_model_id = getattr(self, "_real_vlm_model_id", "vlm")
        else:
            self.vlm_endpoint = f"http://localhost:{self.mock_vlm_port}/analyze"
            self.vlm_api_key = "mock-key"
            self.vlm_model_id = "mock-vlm"

        # 정밀 분석 엔드포인트 설정
        if self.real_precision:
            # precision_client.py가 OpenAI Chat API (get_vision_completion)를 사용하도록 리팩토링됨
            pass
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

        # LangSmith 추적 환경 변수 설정
        if self.langsmith_tracing and self.langsmith_api_key:
            os.environ["LANGSMITH_TRACING"] = "true"
            os.environ["LANGSMITH_API_KEY"] = self.langsmith_api_key
            os.environ["LANGSMITH_PROJECT"] = self.langsmith_project
        else:
            os.environ.pop("LANGSMITH_TRACING", None)
