"""
모의 FastAPI 서버 - VLM 트리거 + 정밀 분석 + 백엔드 (워크플로우에 맞게 수정됨)
"""
import logging
import random
import uuid
from typing import List, Union, Literal, Optional
from fastapi import FastAPI, Response, status
from pydantic import BaseModel
import uvicorn

# README.md 와 state.py 에 정의된 타입
RiskLevel = Literal["NORMAL", "SUSPICIOUS", "ABNORMAL"]
EventType = Literal["ASSAULT", "BURGLARY", "DUMP", "SWOON", "VANDALISM"]


# =========================
# VLM 트리거 서버 모델
# =========================
class VLMAnalysisRequest(BaseModel):
    camera_id: str
    frames: List[str]
    num_frames: int
    timestamp: str
    window_start: Union[int, str]
    window_end: Union[int, str]

class VLMAnalysisResponse(BaseModel):
    risk_level: RiskLevel
    event_type: EventType


# =========================
# 정밀 분석 서버 모델
# =========================
class PrecisionAnalysisRequest(BaseModel):
    camera_id: str
    frames: List[str]
    num_frames: int
    occurred_at: str # timestamp 대신 occurred_at 사용
    window_start: Union[int, str]
    window_end: Union[int, str]
    vlm_result: dict

class PrecisionAnalysisResponse(BaseModel):
    risk: RiskLevel
    event_type: EventType
    summary: str
    risk_score: float


# =========================
# 백엔드 서버 모델 (DATA-MODEL.md 기준)
# =========================
class EventCreationRequest(BaseModel):
    camera_id: str
    risk: RiskLevel
    type: str
    occurred_at: str

class EventCreationResponse(BaseModel):
    event_id: str

class EventUpdateRequest(BaseModel):
    risk: Optional[RiskLevel] = None
    type: Optional[EventType] = None
    summary: Optional[str] = None
    risk_score: Optional[str] = None # VARCHAR(10)


# =========================
# VLM 트리거 모의 서버
# =========================
class MockVLMServer:
    """VLM 트리거 분석 모의 서버"""
    def __init__(self, port: int = 8001):
        self.port = port
        self.logger = logging.getLogger("aegis-agent.mock_vlm")
        self.app = FastAPI(title="AEGIS 모의 VLM 트리거 서버")
        self._setup_routes()

    def _setup_routes(self):
        @self.app.post("/analyze", response_model=VLMAnalysisResponse)
        async def analyze(request: VLMAnalysisRequest):
            rand = random.random()
            if rand < 0.25: risk_level = "ABNORMAL"
            elif rand < 0.50: risk_level = "SUSPICIOUS"
            else: risk_level = "NORMAL"
            
            # NORMAL이 아닐 경우, 5가지 타입 중 하나를 무작위로 선택
            if risk_level != "NORMAL":
                event_type = random.choice(["ASSAULT", "BURGLARY", "DUMP", "SWOON", "VANDALISM"])
            else:
                # NORMAL일 때는 특정 타입이 의미 없으므로, 첫 번째 타입으로 설정
                event_type = "ASSAULT"

            if risk_level in ["ABNORMAL", "SUSPICIOUS"]:
                self.logger.info(f"[트리거 활성화!] VLM이 {risk_level} 감지 - 카메라: {request.camera_id}, 타입: {event_type}")
            
            return VLMAnalysisResponse(
                risk_level=risk_level,
                event_type=event_type,
            )

        @self.app.get("/health")
        async def health():
            return {"status": "healthy", "server": "vlm_trigger"}

    def run(self):
        self.logger.info(f"[시작] VLM 트리거 서버를 {self.port} 포트에서 시작합니다")
        uvicorn.run(self.app, host="0.0.0.0", port=self.port, log_level="warning")


# =========================
# 정밀 분석 모의 서버
# =========================
class MockPrecisionServer:
    """정밀 분석 모의 서버"""
    def __init__(self, port: int = 8002):
        self.port = port
        self.logger = logging.getLogger("aegis-agent.mock_precision")
        self.app = FastAPI(title="AEGIS 모의 정밀 분석 서버")
        self._setup_routes()

    def _setup_routes(self):
        @self.app.post("/precision_analyze", response_model=PrecisionAnalysisResponse)
        async def precision_analyze(request: PrecisionAnalysisRequest):
            # 허용된 공식 이벤트 타입 목록
            valid_types = ["ASSAULT", "BURGLARY", "DUMP", "SWOON", "VANDALISM"]
            
            vlm_risk_level = request.vlm_result.get("risk_level", "NORMAL")
            
            # 클라이언트로부터 받은 타입을 확인하되, 유효하지 않으면 기본값(DUMP) 또는 랜덤 선택합니다.
            # 이 로직은 Pydantic 검증 오류(500 Error)를 방지하는 핵심 장치입니다.
            raw_event_type = request.vlm_result.get("event_type", "DUMP").upper()
            vlm_event_type = raw_event_type if raw_event_type in valid_types else random.choice(valid_types)

            if vlm_risk_level.upper() in ["ABNORMAL", "SUSPICIOUS"]:
                # 정밀 분석 모의 결과: 무조건 유효한 5종 중 하나를 반환합니다.
                event_type = random.choice(valid_types)
                summary = f"모의 정밀 분석 결과: {event_type} 이벤트가 감지되었습니다."
                risk_score = random.uniform(0.8, 1.0)
                risk = "ABNORMAL"
            else:
                # NORMAL 상황에서도 무조건 유효한 타입 규격을 준수합니다.
                event_type = vlm_event_type
                summary = "정상 상황으로 판단되어 정밀 분석을 수행하지 않았습니다."
                risk_score = random.uniform(0.0, 0.2)
                risk = "NORMAL"
            
            self.logger.info(f"\n{'='*80}\n[정밀 분석 결과] 카메라: {request.camera_id}, VLM 트리거: {vlm_risk_level.upper()} ({vlm_event_type}), 분석 결과: {event_type} (점수: {risk_score:.2f})\n{'='*80}\n")
            
            return PrecisionAnalysisResponse(
                risk=risk,
                event_type=event_type,
                summary=summary,
                risk_score=risk_score,
            )

        @self.app.get("/health")
        async def health():
            return {"status": "healthy", "server": "precision_analysis"}

    def run(self):
        self.logger.info(f"[시작] 정밀 분석 서버를 {self.port} 포트에서 시작합니다")
        uvicorn.run(self.app, host="0.0.0.0", port=self.port, log_level="warning")


# =========================
# 백엔드 모의 서버 (DATA-MODEL.md 기준)
# =========================
class MockBackendServer:
    """스프링부트 백엔드 모의 서버"""
    def __init__(self, port: int = 8088):
        self.port = port
        self.logger = logging.getLogger("aegis-agent.mock_backend")
        self.app = FastAPI(title="AEGIS 모의 백엔드 서버")
        self._setup_routes()

    def _setup_routes(self):
        # 1차 분석: 이벤트 생성
        @self.app.post("/api/vlm-results", response_model=EventCreationResponse, status_code=status.HTTP_201_CREATED)
        async def create_event(payload: EventCreationRequest):
            event_id = str(uuid.uuid4())
            self.logger.info(f"[백엔드 수신] 1차 분석 결과 수신 (카메라: {payload.camera_id}). Event ID: {event_id} 생성.")
            self.logger.info(f"  - 데이터: risk='{payload.risk}', type='{payload.type}', occurred_at='{payload.occurred_at}'")
            return EventCreationResponse(event_id=event_id)

        # 2차 분석: 이벤트 갱신
        @self.app.put("/api/vlm-results/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
        async def update_event(event_id: str, payload: EventUpdateRequest):
            self.logger.info(f"[백엔드 갱신] 2차 분석 결과 수신 (Event ID: {event_id}).")
            self.logger.info(f"  - 데이터: {payload.model_dump_json(exclude_unset=True)}")
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        @self.app.get("/health")
        async def health():
            return {"status": "healthy", "server": "backend"}

    def run(self):
        self.logger.info(f"[시작] 백엔드 서버를 {self.port} 포트에서 시작합니다")
        uvicorn.run(self.app, host="0.0.0.0", port=self.port, log_level="warning")
