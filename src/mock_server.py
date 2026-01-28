"""
모의 FastAPI 서버 - VLM 트리거 + 정밀 분석
"""
import logging
import random
from typing import List, Union
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
import base64


# =========================
# VLM 트리거 서버 모델
# =========================

class VLMAnalysisRequest(BaseModel):
    camera_id: str
    frames: List[str]  # base64 인코딩 (저해상도)
    num_frames: int
    timestamp: str
    window_start: Union[int, str]
    window_end: Union[int, str]


class VLMAnalysisResponse(BaseModel):
    status: str
    camera_id: str
    frames_received: int
    total_bytes: int
    # VLM 분석 결과
    primary_category: str  # normal, abnormal, suspicious
    secondary_category: str  # theft, fall, assault, vandalism, dump
    confidence: float
    description: str
    message: str


# =========================
# 정밀 분석 서버 모델
# =========================

class PrecisionAnalysisRequest(BaseModel):
    camera_id: str
    frames: List[str]  # base64 인코딩 (고해상도)
    num_frames: int
    timestamp: str
    window_start: Union[int, str]
    window_end: Union[int, str]
    vlm_result: dict  # VLM 메타데이터


class PrecisionAnalysisResponse(BaseModel):
    status: str
    camera_id: str
    frames_received: int
    total_bytes: int
    vlm_category: str
    detailed_analysis: str
    message: str


# =========================
# VLM 트리거 모의 서버
# =========================

class MockVLMServer:
    """VLM 트리거 분석 모의 서버"""

    def __init__(self, port: int = 8001):
        """
        모의 VLM 서버 초기화

        Args:
            port: 서버 포트
        """
        self.port = port
        self.logger = logging.getLogger("aegis-agent.mock_vlm")
        self.app = FastAPI(title="AEGIS 모의 VLM 트리거 서버")

        # 통계
        self.total_requests = 0
        self.total_frames = 0
        self.total_bytes = 0
        self.total_abnormal = 0
        self.total_suspicious = 0
        self.total_normal = 0

        # 라우트 설정
        self._setup_routes()

    def _setup_routes(self):
        """FastAPI 라우트 설정"""

        @self.app.post("/analyze", response_model=VLMAnalysisResponse)
        async def analyze(request: VLMAnalysisRequest):
            """VLM 트리거 분석 엔드포인트"""
            self.total_requests += 1
            self.total_frames += request.num_frames

            # 데이터 크기 계산
            total_bytes = 0
            for frame_b64 in request.frames:
                try:
                    frame_bytes = base64.b64decode(frame_b64)
                    total_bytes += len(frame_bytes)
                except Exception as e:
                    self.logger.error(f"프레임 디코딩 오류: {e}")

            self.total_bytes += total_bytes

            # 모의 VLM 분석 결과 생성 (30% 확률로 이상/의심 반환)
            rand = random.random()

            if rand < 0.15:  # 15% 이상
                primary = "abnormal"
                secondary = random.choice(["theft", "assault", "fall"])
                self.total_abnormal += 1
            elif rand < 0.30:  # 15% 의심
                primary = "suspicious"
                secondary = random.choice(["vandalism", "dump"])
                self.total_suspicious += 1
            else:  # 70% 정상
                primary = "normal"
                secondary = ""
                self.total_normal += 1

            confidence = random.uniform(0.75, 0.95)
            description = f"모의 VLM 분석: {primary} 감지"

            # 로그 출력 - 트리거 발동 시에만
            if primary in ["abnormal", "suspicious"]:
                self.logger.info(
                    f"[트리거 활성화!] VLM이 {primary.upper()}/{secondary} 감지 "
                    f"- 카메라: {request.camera_id}, 신뢰도: {confidence:.2f}"
                )

            return VLMAnalysisResponse(
                status="success",
                camera_id=request.camera_id,
                frames_received=request.num_frames,
                total_bytes=total_bytes,
                primary_category=primary,
                secondary_category=secondary,
                confidence=confidence,
                description=description,
                message="모의 VLM 분석 완료",
            )

        @self.app.get("/health")
        async def health():
            """상태 체크 엔드포인트"""
            return {
                "status": "healthy",
                "server": "vlm_trigger",
                "total_requests": self.total_requests,
                "total_frames": self.total_frames,
                "total_bytes": self.total_bytes,
            }

        @self.app.get("/stats")
        async def stats():
            """통계 엔드포인트"""
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
        """모의 VLM 서버 실행"""
        self.logger.info(
            f"[시작] VLM 트리거 서버를 {self.port} 포트에서 시작합니다"
        )
        uvicorn.run(
            self.app,
            host="0.0.0.0",
            port=self.port,
            log_level="warning",
        )


# =========================
# 정밀 분석 모의 서버
# =========================

class MockPrecisionServer:
    """정밀 분석 모의 서버"""

    def __init__(self, port: int = 8002):
        """
        모의 정밀 분석 서버 초기화

        Args:
            port: 서버 포트
        """
        self.port = port
        self.logger = logging.getLogger("aegis-agent.mock_precision")
        self.app = FastAPI(title="AEGIS 모의 정밀 분석 서버")

        # 통계
        self.total_requests = 0
        self.total_frames = 0
        self.total_bytes = 0

        # 라우트 설정
        self._setup_routes()

    def _setup_routes(self):
        """FastAPI 라우트 설정"""

        @self.app.post("/precision_analyze", response_model=PrecisionAnalysisResponse)
        async def precision_analyze(request: PrecisionAnalysisRequest):
            """정밀 분석 엔드포인트"""
            self.total_requests += 1
            self.total_frames += request.num_frames

            # 데이터 크기 계산
            total_bytes = 0
            for frame_b64 in request.frames:
                try:
                    frame_bytes = base64.b64decode(frame_b64)
                    total_bytes += len(frame_bytes)
                except Exception as e:
                    self.logger.error(f"프레임 디코딩 오류: {e}")

            self.total_bytes += total_bytes

            # VLM 결과 추출
            vlm_primary = request.vlm_result.get("primary_category", "unknown")
            vlm_secondary = request.vlm_result.get("secondary_category", "")
            vlm_confidence = request.vlm_result.get("confidence", 0.0)

            # 모의 정밀 분석 결과
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

            # 로그 출력 - 정밀 분석 결과 항상 출력
            self.logger.info(
                f"\n{'='*80}\n"
                f"[정밀 분석 결과]\n"
                f"카메라: {request.camera_id}\n"
                f"VLM 트리거: {vlm_primary.upper()}/{vlm_secondary} (신뢰도: {vlm_confidence:.2f})\n"
                f"윈도우: {request.window_start}-{request.window_end}\n"
                f"분석된 프레임: {request.num_frames} (고해상도: {total_bytes / 1024 / 1024:.2f} MB)\n"
                f"---\n"
                f"분석 결과: {detailed_analysis}\n"
                f"{'='*80}\n"
            )

            return PrecisionAnalysisResponse(
                status="success",
                camera_id=request.camera_id,
                frames_received=request.num_frames,
                total_bytes=total_bytes,
                vlm_category=f"{vlm_primary}/{vlm_secondary}",
                detailed_analysis=detailed_analysis,
                message="모의 정밀 분석 완료",
            )

        @self.app.get("/health")
        async def health():
            """상태 체크 엔드포인트"""
            return {
                "status": "healthy",
                "server": "precision_analysis",
                "total_requests": self.total_requests,
                "total_frames": self.total_frames,
                "total_bytes": self.total_bytes,
            }

        @self.app.get("/stats")
        async def stats():
            """통계 엔드포인트"""
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
        """모의 정밀 분석 서버 실행"""
        self.logger.info(
            f"[시작] 정밀 분석 서버를 {self.port} 포트에서 시작합니다"
        )
        uvicorn.run(
            self.app,
            host="0.0.0.0",
            port=self.port,
            log_level="warning",
        )


# =========================
# 편의 함수
# =========================

def start_mock_vlm_server(port: int = 8001):
    """
    모의 VLM 트리거 서버 시작

    Args:
        port: 서버 포트
    """
    server = MockVLMServer(port)
    server.run()


def start_mock_precision_server(port: int = 8002):
    """
    모의 정밀 분석 서버 시작

    Args:
        port: 서버 포트
    """
    server = MockPrecisionServer(port)
    server.run()
