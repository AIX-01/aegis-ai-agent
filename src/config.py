"""
AEGIS AI Agent 설정 모듈

모든 설정값은 os.getenv()로 환경변수 오버라이드 가능.
기본값은 기존 로컬 Docker Compose 환경과 동일.
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

    AGENT_MODE:
        - "all": 로컬 모드 (Producer + Consumer 동일 프로세스, queue.Queue 사용)
        - "ingest": Producer만 실행, SQS로 태스크 전송, EFS에 패킷 덤프
        - "worker": Consumer만 실행, SQS에서 태스크 수신, EFS에서 패킷 읽기
    """

    # ===================================================================
    # >> 0. 에이전트 동작 모드 (AWS 마이그레이션용)
    # ===================================================================
    agent_mode: str = field(default_factory=lambda: os.getenv("AGENT_MODE", "all"))

    # ===================================================================
    # >> 1. 실제 서버 주소 설정 (환경변수로 오버라이드 가능)
    # ===================================================================
    _real_vlm_endpoint: str = field(
        default_factory=lambda: os.getenv(
            "VLM_ENDPOINT", "https://nt89vcc8yd5d8e-8000.proxy.runpod.net/v1"

        )
    )
    _real_vlm_api_key: str = field(
        default_factory=lambda: os.getenv(
            "VLM_API_KEY", "sk-IrR7Bwxtin0haWagUnPrBgq5PurnUz86"
        )
    )
    _real_vlm_model_id: str = field(
        default_factory=lambda: os.getenv(
            "VLM_MODEL_ID",
            "AIX-01/Qwen3-VL-2B-Instruct-unsloth-bnb-4bit-3000steps-r64-b8-merged-16bit",
        )
    )

    # 백엔드 엔드포인트: BACKEND_URL 환경변수로 베이스 URL 오버라이드
    # 갱신용 URL에는 {event_id} 플레이스홀더를 사용할 수 있습니다.
    _real_backend_create_endpoint: str = field(init=False)
    _real_backend_update_endpoint: str = field(init=False)
    _real_backend_clip_endpoint: str = field(init=False)

    # =========================================
    # Human-in-the-Loop (HITL) API 엔드포인트
    # =========================================
    _real_backend_action_create_endpoint: str = field(init=False)
    _real_backend_action_confirm_endpoint: str = field(init=False)
    _real_backend_action_update_endpoint: str = field(init=False)

    # ===================================================================
    # >> 2. 모드 설정 (컴포넌트별 True/False로 전환)
    # ===================================================================
    # 개별 컴포넌트의 실제 서버 사용 여부 (기본값: False -> Mock 사용)
    # - 여기서 True로 설정하면 CLI 플래그 없이도 항상 실제 서버 사용
    # - CLI 플래그(--real-vlm 등)는 False → True 전환만 가능 (True → False 불가)
    real_vlm: bool = False
    real_backend: bool = False

    # ===================================================================
    # >> 3. 활성 엔드포인트 (수정 금지 - __post_init__에서 자동 설정됨)
    # ===================================================================
    vlm_endpoint: str = field(init=False)
    vlm_api_key: Optional[str] = field(init=False, default=None)
    vlm_model_id: str = field(init=False, default="vlm")
    backend_create_endpoint: str = field(init=False)
    backend_update_endpoint: str = field(init=False)  # 이벤트 갱신 (분석 결과, 보고서, 상태 통합)
    backend_clip_endpoint: str = field(init=False)

    # Human-in-the-Loop (HITL) 엔드포인트
    backend_action_create_endpoint: str = field(init=False)   # Action 생성
    backend_action_confirm_endpoint: str = field(init=False)  # Action 승인 확인
    backend_action_update_endpoint: str = field(init=False)   # Action 갱신

    # =========================================
    # 에이전트 API 서버 설정 (FastAPI)
    # =========================================
    agent_api_host: str = "0.0.0.0"
    agent_api_port: int = 8000

    # =========================================
    # 모의 서버 포트 설정 (real_*=False인 컴포넌트에 사용)
    # =========================================
    mock_vlm_port: int = 8001
    mock_backend_port: int = 8088

    # =========================================
    # RTSP 및 프레임 처리 설정
    # =========================================
    rtsp_host: str = field(default_factory=lambda: os.getenv("RTSP_HOST", "127.0.0.1"))
    rtsp_port: int = field(default_factory=lambda: int(os.getenv("RTSP_PORT", "8554")))
    frame_width: int = 640
    frame_height: int = 360
    jpeg_quality: int = 60
    fps: int = 1
    # 비디오 패킷 버퍼링 시간 (초): 이상 행동 감지 시 추출할 영상의 최대 길이를 결정합니다
    # all 모드: 30초, AWS 모드(ingest/worker): 120초 (분석 지연 대비) → __post_init__에서 설정
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
    redis_host: str = field(default_factory=lambda: os.getenv("REDIS_HOST", "localhost"))
    redis_port: int = field(default_factory=lambda: int(os.getenv("REDIS_PORT", "6379")))
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
    openai_embedding_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    )
    openai_embedding_dimension: int = 1536

    # 챗 설정 (precision용)
    openai_chat_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")
    )
    openai_chat_timeout: int = 60

    # =========================================
    # Qdrant 벡터 DB 설정
    # =========================================
    qdrant_host: str = field(default_factory=lambda: os.getenv("QDRANT_HOST", "localhost"))
    qdrant_port: int = field(default_factory=lambda: int(os.getenv("QDRANT_PORT", "6333")))
    qdrant_timeout: int = 30

    # =========================================
    # 보고서 설정
    # =========================================
    # 보고서 템플릿 경로 (프로젝트 루트 기준)
    report_template_dir: str = "templates/reports"

    # =========================================
    # AWS 리소스 설정 (AGENT_MODE=ingest/worker 시 사용)
    # =========================================
    sqs_queue_url: str = field(default_factory=lambda: os.getenv("SQS_QUEUE_URL", ""))
    s3_bucket: str = field(default_factory=lambda: os.getenv("S3_BUCKET", ""))
    aws_region: str = field(default_factory=lambda: os.getenv("AWS_REGION", "ap-northeast-2"))
    efs_buffer_path: str = field(default_factory=lambda: os.getenv("EFS_BUFFER_PATH", "/efs/buffers"))

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

    ## 입력 정보
    - 1FPS로 캡처된 8개의 연속 프레임이 시간순으로 제공됩니다.
    - 이 프레임들은 1차 VLM 분석에서 "이상(ABNORMAL)" 또는 "의심(SUSPICIOUS)"으로 판정된 영상입니다.
    - 즉, 정상 상황이 아닌 이상 현상이 포착된 프레임만 전달됩니다.

    ## 분석 지침
    1. 제공된 8개의 프레임을 시간순으로 분석하여 상황을 파악하세요.
    2. 1차 VLM 분석 결과를 참고하되, 이미지 기반으로 최종 판단하세요.
    3. **위험도(risk_level)를 판별하세요:**
       - ABNORMAL (이상): 명확한 이상 행동이 확인됨
       - SUSPICIOUS (의심): 이상 행동이 불명확하거나 추가 확인이 필요함
    4. **summary 작성 시 반드시 이상 행동 주체의 특징을 포함하세요:**
       - 인상착의 (옷 색상, 스타일 등)
       - 체형/성별/추정 연령대
       - 예시: "검은 후드티를 입은 중년 남성이 쓰레기봉투를 골목에 투기하고 있습니다."

    ## risk_score 산정 기준
    이벤트 유형별 **기본 위험도**를 기준으로, 상황의 **심각도**에 따라 점수를 조정하세요.

    | 이벤트 유형 | 기본 위험도 | 점수 범위 | 설명 |
    |------------|------------|----------|------|
    | SWOON (실신) | 0.9 | 0.85 ~ 1.0 | 의료 응급상황, 즉시 대응 필요 |
    | ASSAULT (폭행) | 0.85 | 0.75 ~ 1.0 | 신체적 위협, 긴급 대응 필요 |
    | BURGLARY (절도) | 0.7 | 0.6 ~ 0.85 | 재산 피해 우려, 신속 확인 필요 |
    | VANDALISM (기물파손) | 0.6 | 0.5 ~ 0.75 | 재산 피해, 확인 필요 |
    | DUMP (무단투기) | 0.4 | 0.3 ~ 0.55 | 경범죄, 기록 필요 |

    **심각도 조정 요소:**
    - 행동의 명확성이 높으면 → 점수 상향
    - 피해 규모가 크면 → 점수 상향
    - 진행 중인 상황이면 → 점수 상향
    - 불명확하거나 종료된 상황이면 → 점수 하향

    ## 출력 형식 (JSON만 출력)
    {
      "risk_level": "ABNORMAL|SUSPICIOUS",
      "event_type": "ASSAULT|BURGLARY|DUMP|SWOON|VANDALISM",
      "summary": "[인상착의]를 한 [성별/연령대]이(가) [행동]을 하고 있습니다. [추가 상황 설명]",
      "risk_score": 0.0~1.0
    }

    ## 이벤트 유형 정의
    - ASSAULT: 폭행, 싸움, 물리적 충돌
    - BURGLARY: 절도, 침입, 무단 침입
    - DUMP: 쓰레기 무단 투기
    - SWOON: 실신, 쓰러짐, 의료 응급상황
    - VANDALISM: 기물 파손, 낙서

    JSON만 출력하세요."""

    # =========================================
    # Verification 검증 시스템 프롬프트
    # =========================================
    verification_system_prompt: str = """당신은 CCTV 영상 분석 결과를 최종 검증하는 전문가입니다.

    ## 입력 정보
    - 1FPS로 캡처된 8개의 연속 프레임이 시간순으로 제공됩니다.
    - 정밀 분석(precision_analysis) 결과가 함께 제공됩니다:
      - risk_level: 위험도 (ABNORMAL/SUSPICIOUS)
      - event_type: 이벤트 유형 (ASSAULT/BURGLARY/DUMP/SWOON/VANDALISM)
      - summary: 상황 요약 (인상착의 포함)

    ## 검증 지침
    1. **8개 프레임을 시간순으로 분석**하여 실제 상황을 파악하세요.
    2. 정밀 분석의 summary 내용이 이미지와 일치하는지 검증하세요:
       - 인상착의 (옷 색상, 스타일 등)가 실제 이미지와 맞는가?
       - 행동 설명이 이미지에서 확인되는가?
    3. **event_type이 실제 상황과 일치하는지 확인**하세요:
       - 이미지에서 확인되는 행동이 다른 유형이면 event_type을 수정하세요.
       - 예: 정밀 분석이 ASSAULT라고 했지만, 실제로는 VANDALISM인 경우 수정

    ## 이벤트 유형 정의
    - ASSAULT: 폭행, 싸움, 물리적 충돌 (사람 간 신체 접촉)
    - BURGLARY: 절도, 침입, 무단 침입 (물건을 훔치거나 불법 진입)
    - DUMP: 쓰레기 무단 투기 (쓰레기봉투/폐기물 투기)
    - SWOON: 실신, 쓰러짐, 의료 응급상황 (사람이 바닥에 쓰러짐)
    - VANDALISM: 기물 파손, 낙서 (물건/시설물 파손)

    ## 판단 기준
    - **ABNORMAL (이상 확정)**:
      - 8개 프레임에서 명확한 이상 행동이 확인됨
      - event_type이 맞으면 유지, 틀리면 올바른 유형으로 수정
    - **SUSPICIOUS (의심으로 하향)**:
      - 이상 행동이 불명확하거나 정상 상황으로 판단됨
      - 오탐으로 보이는 경우

    ## 출력 형식 (JSON만 출력)
    {
      "risk_level": "ABNORMAL|SUSPICIOUS",
      "event_type": "ASSAULT|BURGLARY|DUMP|SWOON|VANDALISM",
      "reason": "판단 이유를 한 문장으로 작성 (한국어)"
    }

    ## 주의사항
    - event_type은 반드시 출력하세요. 정밀 분석과 같으면 그대로, 다르면 수정된 값을 출력하세요.
    - 8개 프레임의 연속된 흐름을 보고 어떤 행동인지 맥락을 파악하세요.

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
        # 백엔드 기본 URL (BACKEND_URL 환경변수로 오버라이드 가능)
        backend_base = os.getenv("BACKEND_URL", "http://localhost:8080")
        self._real_backend_create_endpoint = f"{backend_base}/internal/agent/events"
        self._real_backend_update_endpoint = f"{backend_base}/internal/agent/events/{{event_id}}"
        self._real_backend_clip_endpoint = f"{backend_base}/internal/agent/events/{{event_id}}/clip"
        self._real_backend_action_create_endpoint = f"{backend_base}/internal/agent/events/{{event_id}}/actions"
        self._real_backend_action_confirm_endpoint = f"{backend_base}/internal/agent/events/{{event_id}}/actions/{{action_id}}/pending"
        self._real_backend_action_update_endpoint = f"{backend_base}/internal/agent/events/{{event_id}}/actions/{{action_id}}"

        # VLM 엔드포인트 설정
        if self.real_vlm:
            self.vlm_endpoint = self._real_vlm_endpoint
            self.vlm_api_key = self._real_vlm_api_key
            self.vlm_model_id = self._real_vlm_model_id
        else:
            self.vlm_endpoint = f"http://localhost:{self.mock_vlm_port}/analyze"
            self.vlm_api_key = "mock-key"
            self.vlm_model_id = "mock-vlm"

        # 백엔드 엔드포인트 설정 (생성/갱신/클립 분리, 갱신 엔드포인트가 분석+보고서+상태 통합)
        if self.real_backend:
            # 전체 실제 서버 사용
            self.backend_create_endpoint = self._real_backend_create_endpoint
            self.backend_update_endpoint = self._real_backend_update_endpoint
            self.backend_clip_endpoint = self._real_backend_clip_endpoint
            # HITL 엔드포인트도 실제 서버 사용
            self.backend_action_create_endpoint = self._real_backend_action_create_endpoint
            self.backend_action_confirm_endpoint = self._real_backend_action_confirm_endpoint
            self.backend_action_update_endpoint = self._real_backend_action_update_endpoint
        else:
            # Mock 서버는 RESTful 규칙을 따르므로 기본 경로 설정
            base_url = f"http://localhost:{self.mock_backend_port}/api/vlm-results"
            self.backend_create_endpoint = base_url
            self.backend_update_endpoint = f"{base_url}/{{event_id}}"  # 통합된 갱신 엔드포인트
            self.backend_clip_endpoint = f"{base_url}/{{event_id}}/clip"
            # HITL 엔드포인트도 Mock 서버 경로 설정
            self.backend_action_create_endpoint = f"{base_url}/{{event_id}}/actions"
            self.backend_action_confirm_endpoint = f"{base_url}/{{event_id}}/actions/{{action_id}}/pending"
            self.backend_action_update_endpoint = f"{base_url}/{{event_id}}/actions/{{action_id}}"

        # AWS 모드에서는 비디오 버퍼를 120초로 확대 (분석 지연 대비)
        if self.agent_mode != "all":
            self.video_buffer_seconds = int(os.getenv("VIDEO_BUFFER_SECONDS", "120"))
