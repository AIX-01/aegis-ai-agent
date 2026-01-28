"""
Mock FastAPI 서버 - VLM 트리거 + 정밀 분석
Mock FastAPI servers - VLM Trigger + Precision Analysis
"""
import logging
import random
from typing import List
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
import base64


# =========================
# VLM 트리거 서버 모델
# VLM Trigger Server Models
# =========================

class VLMAnalysisRequest(BaseModel):
    camera_id: str
    frames: List[str]  # base64 encoded (저해상도 / low-res)
    num_frames: int
    timestamp: str
    window_start: int
    window_end: int


class VLMAnalysisResponse(BaseModel):
    status: str
    camera_id: str
    frames_received: int
    total_bytes: int
    # VLM 분석 결과 / VLM analysis result
    primary_category: str  # normal, abnormal, suspicious
    secondary_category: str  # theft, fall, assault, vandalism, dump
    confidence: float
    description: str
    message: str


# =========================
# 정밀 분석 서버 모델
# Precision Analysis Server Models
# =========================

class PrecisionAnalysisRequest(BaseModel):
    camera_id: str
    frames: List[str]  # base64 encoded (고해상도 / high-res)
    num_frames: int
    timestamp: str
    window_start: int
    window_end: int
    vlm_result: dict  # VLM 메타데이터 / VLM metadata


class PrecisionAnalysisResponse(BaseModel):
    status: str
    camera_id: str
    frames_received: int
    total_bytes: int
    vlm_category: str
    detailed_analysis: str
    message: str


# =========================
# VLM 트리거 Mock 서버
# VLM Trigger Mock Server
# =========================

class MockVLMServer:
    """VLM 트리거 분석 Mock 서버 / Mock VLM Trigger Analysis Server"""

    def __init__(self, port: int = 8001):
        """
        Initialize mock VLM server

        Args:
            port: Server port
        """
        self.port = port
        self.logger = logging.getLogger("aegis-agent.mock_vlm")
        self.app = FastAPI(title="AEGIS Mock VLM Trigger Server")

        # 통계 / Statistics
        self.total_requests = 0
        self.total_frames = 0
        self.total_bytes = 0
        self.total_abnormal = 0
        self.total_suspicious = 0
        self.total_normal = 0

        # Setup routes
        self._setup_routes()

    def _setup_routes(self):
        """Setup FastAPI routes"""

        @self.app.post("/analyze", response_model=VLMAnalysisResponse)
        async def analyze(request: VLMAnalysisRequest):
            """VLM 트리거 분석 엔드포인트 / VLM trigger analysis endpoint"""
            self.total_requests += 1
            self.total_frames += request.num_frames

            # 데이터 크기 계산 / Calculate total bytes
            total_bytes = 0
            for frame_b64 in request.frames:
                try:
                    frame_bytes = base64.b64decode(frame_b64)
                    total_bytes += len(frame_bytes)
                except Exception as e:
                    self.logger.error(f"프레임 디코딩 에러 / Error decoding frame: {e}")

            self.total_bytes += total_bytes

            # Mock VLM 분석 결과 생성 (30% 확률로 이상/의심 반환)
            # Generate mock VLM result (30% chance of abnormal/suspicious)
            rand = random.random()

            if rand < 0.15:  # 15% 이상 / abnormal
                primary = "abnormal"
                secondary = random.choice(["theft", "assault", "fall"])
                self.total_abnormal += 1
            elif rand < 0.30:  # 15% 의심 / suspicious
                primary = "suspicious"
                secondary = random.choice(["vandalism", "dump"])
                self.total_suspicious += 1
            else:  # 70% 정상 / normal
                primary = "normal"
                secondary = ""
                self.total_normal += 1

            confidence = random.uniform(0.75, 0.95)
            description = f"Mock VLM analysis: detected {primary}"

            # 로그 출력 / Log request - 트리거 발동 시에만 출력
            if primary in ["abnormal", "suspicious"]:
                self.logger.info(
                    f"[TRIGGER ACTIVATED!] VLM detected {primary.upper()}/{secondary} "
                    f"- Camera: {request.camera_id}, Confidence: {confidence:.2f}"
                )
            # else:
            #     # 정상일 때는 로그 출력 안함
            #     pass

            # # 주기적 통계 / Periodic stats - 주석 처리
            # if self.total_requests % 10 == 0:
            #     trigger_rate = 100 * (self.total_abnormal + self.total_suspicious) / self.total_requests
            #     self.logger.info(
            #         f"[VLM Server Stats] "
            #         f"Requests: {self.total_requests}, "
            #         f"Trigger rate: {trigger_rate:.1f}% "
            #         f"(Abnormal: {self.total_abnormal}, "
            #         f"Suspicious: {self.total_suspicious}, "
            #         f"Normal: {self.total_normal})"
            #     )

            return VLMAnalysisResponse(
                status="success",
                camera_id=request.camera_id,
                frames_received=request.num_frames,
                total_bytes=total_bytes,
                primary_category=primary,
                secondary_category=secondary,
                confidence=confidence,
                description=description,
                message="Mock VLM analysis completed",
            )

        @self.app.get("/health")
        async def health():
            """Health check endpoint"""
            return {
                "status": "healthy",
                "server": "vlm_trigger",
                "total_requests": self.total_requests,
                "total_frames": self.total_frames,
                "total_bytes": self.total_bytes,
            }

        @self.app.get("/stats")
        async def stats():
            """Statistics endpoint"""
            trigger_rate = (
                100 * (self.total_abnormal + self.total_suspicious) / self.total_requests
                if self.total_requests > 0
                else 0
            )

            return {
                "total_requests": self.total_requests,
                "total_frames": self.total_frames,
                "total_bytes": self.total_bytes,
                "total_abnormal": self.total_abnormal,
                "total_suspicious": self.total_suspicious,
                "total_normal": self.total_normal,
                "trigger_rate": trigger_rate,
            }

    def run(self):
        """Run mock VLM server"""
        self.logger.info(
            f"[START] VLM Trigger Server starting on port {self.port}"
        )
        uvicorn.run(
            self.app,
            host="0.0.0.0",
            port=self.port,
            log_level="warning",
        )


# =========================
# 정밀 분석 Mock 서버
# Precision Analysis Mock Server
# =========================

class MockPrecisionServer:
    """정밀 분석 Mock 서버 / Mock Precision Analysis Server"""

    def __init__(self, port: int = 8002):
        """
        Initialize mock precision server

        Args:
            port: Server port
        """
        self.port = port
        self.logger = logging.getLogger("aegis-agent.mock_precision")
        self.app = FastAPI(title="AEGIS Mock Precision Analysis Server")

        # 통계 / Statistics
        self.total_requests = 0
        self.total_frames = 0
        self.total_bytes = 0

        # Setup routes
        self._setup_routes()

    def _setup_routes(self):
        """Setup FastAPI routes"""

        @self.app.post("/precision_analyze", response_model=PrecisionAnalysisResponse)
        async def precision_analyze(request: PrecisionAnalysisRequest):
            """정밀 분석 엔드포인트 / Precision analysis endpoint"""
            self.total_requests += 1
            self.total_frames += request.num_frames

            # 데이터 크기 계산 / Calculate total bytes
            total_bytes = 0
            for frame_b64 in request.frames:
                try:
                    frame_bytes = base64.b64decode(frame_b64)
                    total_bytes += len(frame_bytes)
                except Exception as e:
                    self.logger.error(f"프레임 디코딩 에러 / Error decoding frame: {e}")

            self.total_bytes += total_bytes

            # VLM 결과 추출 / Extract VLM result
            vlm_primary = request.vlm_result.get("primary_category", "unknown")
            vlm_secondary = request.vlm_result.get("secondary_category", "")
            vlm_confidence = request.vlm_result.get("confidence", 0.0)

            # Mock 정밀 분석 결과 / Mock precision analysis result
            # 여기를 원하는 대로 수정하세요!
            if vlm_primary == "abnormal":
                if vlm_secondary == "theft":
                    detailed_analysis = "도난 의심: 비정상적인 물건 이동 감지됨. 손에 물건을 들고 있는 사람 확인."
                elif vlm_secondary == "assault":
                    detailed_analysis = "폭력 의심: 공격적인 몸짓이 감지됨. 2명 이상 신체 접촉."
                elif vlm_secondary == "fall":
                    detailed_analysis = "낙상 감지: 사람이 바닥에 쓰러진 상태. 즉시 조치 필요."
                else:
                    detailed_analysis = f"이상 행동 감지: {vlm_secondary}"
            elif vlm_primary == "suspicious":
                detailed_analysis = f"의심스러운 활동: {vlm_secondary}. 지속 모니터링 권장."
            else:
                detailed_analysis = "정상: 특이사항 없음."

            # 로그 출력 / Log request - 정밀 분석 결과 항상 출력
            self.logger.info(
                f"\n{'='*80}\n"
                f"[PRECISION ANALYSIS RESULT]\n"
                f"Camera: {request.camera_id}\n"
                f"VLM Trigger: {vlm_primary.upper()}/{vlm_secondary} (confidence: {vlm_confidence:.2f})\n"
                f"Window: {request.window_start}-{request.window_end}s\n"
                f"Frames analyzed: {request.num_frames} (High-res: {total_bytes / 1024 / 1024:.2f} MB)\n"
                f"---\n"
                f"Analysis Result: {detailed_analysis}\n"
                f"{'='*80}\n"
            )

            # # 주기적 통계 / Periodic stats - 주석 처리
            # if self.total_requests % 5 == 0:
            #     avg_bytes = self.total_bytes / self.total_requests
            #     avg_mb = avg_bytes / (1024 * 1024)
            #     self.logger.info(
            #         f"[Precision Server Stats] "
            #         f"Requests: {self.total_requests}, "
            #         f"Frames: {self.total_frames}, "
            #         f"Avg: {avg_mb:.2f} MB/request"
            #     )

            return PrecisionAnalysisResponse(
                status="success",
                camera_id=request.camera_id,
                frames_received=request.num_frames,
                total_bytes=total_bytes,
                vlm_category=f"{vlm_primary}/{vlm_secondary}",
                detailed_analysis=detailed_analysis,
                message="Mock precision analysis completed",
            )

        @self.app.get("/health")
        async def health():
            """Health check endpoint"""
            return {
                "status": "healthy",
                "server": "precision_analysis",
                "total_requests": self.total_requests,
                "total_frames": self.total_frames,
                "total_bytes": self.total_bytes,
            }

        @self.app.get("/stats")
        async def stats():
            """Statistics endpoint"""
            avg_bytes = (
                self.total_bytes / self.total_requests
                if self.total_requests > 0
                else 0
            )

            return {
                "total_requests": self.total_requests,
                "total_frames": self.total_frames,
                "total_bytes": self.total_bytes,
                "avg_bytes_per_request": avg_bytes,
                "avg_mb_per_request": avg_bytes / (1024 * 1024),
            }

    def run(self):
        """Run mock precision server"""
        self.logger.info(
            f"[START] Precision Analysis Server starting on port {self.port}"
        )
        uvicorn.run(
            self.app,
            host="0.0.0.0",
            port=self.port,
            log_level="warning",
        )


# =========================
# 편의 함수 / Convenience functions
# =========================

def start_mock_vlm_server(port: int = 8001):
    """
    Start mock VLM trigger server

    Args:
        port: Server port
    """
    server = MockVLMServer(port)
    server.run()


def start_mock_precision_server(port: int = 8002):
    """
    Start mock precision analysis server

    Args:
        port: Server port
    """
    server = MockPrecisionServer(port)
    server.run()
