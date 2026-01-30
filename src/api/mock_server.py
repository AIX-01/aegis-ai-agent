"""
모의 FastAPI 서버 - VLM 트리거 + 정밀 분석 + 백엔드 (워크플로우에 맞게 수정됨)
"""
import logging
import random
import uuid
from typing import List, Union, Literal, Optional
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

# Agent_Workflow.md 와 state.py 에 정의된 타입
RiskLevel = Literal["NORMAL", "SUSPICIOUS", "ABNORMAL"]
EventType = Literal["ASSAULT", "BURGLARY", "DUMP", "SWOON", "VANDALISM", "UNKNOWN"]


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
    status: str
    camera_id: str
    risk_level: RiskLevel
    confidence: float
    description: str


# =========================
# 정밀 분석 서버 모델
# =========================
class PrecisionAnalysisRequest(BaseModel):
    camera_id: str
    frames: List[str]
    num_frames: int
    timestamp: str
    window_start: Union[int, str]
    window_end: Union[int, str]
    vlm_result: dict

class PrecisionAnalysisResponse(BaseModel):
    status: str
    camera_id: str
    event_type: EventType
    summary: str
    risk_score: float


# =========================
# 백엔드 서버 모델 (신규 추가)
# =========================
class VLMResultPayload(BaseModel):
    cameraId: str
    timestamp: str
    windowStart: str
    windowEnd: str
    primaryCategory: str
    secondaryCategory: Optional[str] = ""
    confidence: float
    description: str

class BackendInitialResponse(BaseModel):
    eventId: str
    message: str

class EventUpdatePayload(BaseModel):
    eventId: str
    eventType: Optional[str] = None
    summary: Optional[str] = None
    riskScore: Optional[float] = None


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
            if rand < 0.15: risk_level = "ABNORMAL"
            elif rand < 0.30: risk_level = "SUSPICIOUS"
            else: risk_level = "NORMAL"
            confidence = random.uniform(0.75, 0.95)
            description = f"모의 VLM 분석: {risk_level} 감지"
            if risk_level in ["ABNORMAL", "SUSPICIOUS"]:
                self.logger.info(f"[트리거 활성화!] VLM이 {risk_level} 감지 - 카메라: {request.camera_id}, 신뢰도: {confidence:.2f}")
            return VLMAnalysisResponse(status="success", camera_id=request.camera_id, risk_level=risk_level, confidence=confidence, description=description)

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
            vlm_risk_level = request.vlm_result.get("primary_category", "UNKNOWN")
            if vlm_risk_level.upper() in ["ABNORMAL", "SUSPICIOUS"]:
                event_type = random.choice(["ASSAULT", "BURGLARY", "DUMP", "SWOON", "VANDALISM"])
                summary = f"모의 정밀 분석 결과: {event_type} 이벤트가 감지되었습니다."
                risk_score = random.uniform(0.8, 1.0)
            else:
                event_type = "UNKNOWN"
                summary = "정상 상황으로 판단되어 정밀 분석을 수행하지 않았습니다."
                risk_score = random.uniform(0.0, 0.2)
            self.logger.info(f"\n{'='*80}\n[정밀 분석 결과] 카메라: {request.camera_id}, VLM 트리거: {vlm_risk_level.upper()}, 분석 결과: {event_type} (점수: {risk_score:.2f})\n{'='*80}\n")
            return PrecisionAnalysisResponse(status="success", camera_id=request.camera_id, event_type=event_type, summary=summary, risk_score=risk_score)

        @self.app.get("/health")
        async def health():
            return {"status": "healthy", "server": "precision_analysis"}

    def run(self):
        self.logger.info(f"[시작] 정밀 분석 서버를 {self.port} 포트에서 시작합니다")
        uvicorn.run(self.app, host="0.0.0.0", port=self.port, log_level="warning")


# =========================
# 백엔드 모의 서버 (신규 추가)
# =========================
class MockBackendServer:
    """스프링부트 백엔드 모의 서버"""
    def __init__(self, port: int = 8080):
        self.port = port
        self.logger = logging.getLogger("aegis-agent.mock_backend")
        self.app = FastAPI(title="AEGIS 모의 백엔드 서버")
        self._setup_routes()

    def _setup_routes(self):
        # 1차 VLM 결과 보고 및 eventId 생성
        @self.app.post("/api/vlm-results", response_model=BackendInitialResponse)
        async def create_event(payload: VLMResultPayload):
            event_id = str(uuid.uuid4())
            self.logger.info(f"[백엔드 수신] 1차 VLM 결과 수신 (카메라: {payload.cameraId}). Event ID: {event_id} 생성.")
            return BackendInitialResponse(eventId=event_id, message="Event created successfully")

        # 2차 정밀 분석 결과 갱신
        @self.app.put("/api/vlm-results/{event_id}")
        async def update_event(event_id: str, payload: EventUpdatePayload):
            risk_score_str = f"{payload.riskScore:.2f}" if payload.riskScore is not None else "N/A"
            self.logger.info(f"[백엔드 갱신] 정밀 분석 결과 수신 (Event ID: {event_id}). EventType: {payload.eventType}, RiskScore: {risk_score_str}")
            return {"message": f"Event {event_id} updated successfully"}

        @self.app.get("/health")
        async def health():
            return {"status": "healthy", "server": "backend"}

    def run(self):
        self.logger.info(f"[시작] 백엔드 서버를 {self.port} 포트에서 시작합니다")
        uvicorn.run(self.app, host="0.0.0.0", port=self.port, log_level="warning")
