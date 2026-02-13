"""
모의 FastAPI 서버 - VLM 트리거 + 정밀 분석 + 백엔드 (워크플로우에 맞게 수정됨)
"""
import logging
import random
import time
import uuid
from typing import List, Union, Literal, Optional
from fastapi import FastAPI, Response, status
from pydantic import BaseModel, Field
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
# 백엔드 서버 모델 (DATA-MODEL.md 기준)
# =========================
class EventCreationRequest(BaseModel):
    camera_id: str = Field(alias="cameraId")
    risk: RiskLevel
    type: str
    occurred_at: str = Field(alias="occurredAt")

class EventCreationResponse(BaseModel):
    event_id: str

class EventUpdateRequest(BaseModel):
    """
    이벤트 갱신 요청 모델

    [API 엔드포인트]
    PATCH /internal/agent/events/{eventId}

    모든 필드는 optional이며, 업데이트할 값만 전달합니다.
    """
    risk: Optional[str] = None      # normal | suspicious | abnormal
    type: Optional[str] = None      # assault | burglary | dump | swoon | vandalism
    summary: Optional[str] = None   # AI 분석 요약
    report: Optional[str] = None    # 상세 보고서 내용 (문자열)
    status: Optional[str] = None    # processing | analyzed


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

        # 2차 분석: 이벤트 갱신 (통합 API)
        @self.app.patch("/api/vlm-results/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
        async def update_event(event_id: str, payload: EventUpdateRequest):
            """
            이벤트 갱신 API (분석 결과 + 보고서 + 상태 통합)

            PATCH /internal/agent/events/{eventId}

            Request Body (모두 optional, 업데이트할 값만 전달):
            - risk: normal | suspicious | abnormal
            - type: assault | burglary | dump | swoon | vandalism
            - summary: AI 분석 요약
            - report: 상세 보고서 내용 (문자열)
            - status: processing | analyzed
            """
            self.logger.info(f"[백엔드 갱신] 이벤트 갱신 수신 (Event ID: {event_id})")

            # 업데이트된 필드만 출력
            if payload.risk:
                self.logger.info(f"  - risk: {payload.risk}")
            if payload.type:
                self.logger.info(f"  - type: {payload.type}")
            if payload.summary:
                summary_preview = payload.summary[:100] if len(payload.summary) > 100 else payload.summary
                self.logger.info(f"  - summary: {summary_preview}...")
            if payload.report:
                report_preview = payload.report[:200].replace("\n", " ") if len(payload.report) > 200 else payload.report.replace("\n", " ")
                self.logger.info(f"  - report: {report_preview}...")
            if payload.status:
                self.logger.info(f"  - status: {payload.status}")

            return Response(status_code=status.HTTP_204_NO_CONTENT)

        # 클립 업로드 URL 발급
        @self.app.get("/api/vlm-results/{event_id}/clip/upload-url")
        async def get_clip_upload_url(event_id: str):
            upload_url = f"http://localhost:{self.port}/api/vlm-results/{event_id}/clip/upload"
            self.logger.info(f"[클립 URL 발급] Event ID: {event_id}")
            return {"uploadUrl": upload_url}

        # 클립 업로드 수신
        @self.app.put("/api/vlm-results/{event_id}/clip/upload", status_code=status.HTTP_200_OK)
        async def upload_clip(event_id: str):
            self.logger.info(f"[클립 업로드 수신] Event ID: {event_id}")
            return {"status": "uploaded"}

        # 클립 업로드 확인
        @self.app.post("/api/vlm-results/{event_id}/clip/confirm", status_code=status.HTTP_200_OK)
        async def confirm_clip(event_id: str):
            self.logger.info(f"[클립 확정] Event ID: {event_id}")
            return {"status": "confirmed"}

        @self.app.get("/health")
        async def health():
            return {"status": "healthy", "server": "backend"}

    def run(self):
        self.logger.info(f"[시작] 백엔드 서버를 {self.port} 포트에서 시작합니다")
        uvicorn.run(self.app, host="0.0.0.0", port=self.port, log_level="warning")


# =========================
# 단독 실행용 진입점
# =========================
def main():
    """Mock 서버 단독 실행 (테스트/개발용)"""
    import argparse
    import threading

    # 로깅 설정
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    parser = argparse.ArgumentParser(description="AEGIS Mock 서버")
    parser.add_argument("--vlm", action="store_true", help="VLM Mock 서버 실행 (포트 8001)")
    parser.add_argument("--backend", action="store_true", help="Backend Mock 서버 실행 (포트 8088)")
    parser.add_argument("--all", action="store_true", help="모든 Mock 서버 실행")
    args = parser.parse_args()

    # 기본값: 아무 옵션도 없으면 모든 서버 실행
    if not (args.vlm or args.backend or args.all):
        args.all = True

    threads = []

    if args.vlm or args.all:
        vlm_server = MockVLMServer(port=8001)
        t = threading.Thread(target=vlm_server.run, daemon=True)
        t.start()
        threads.append(("VLM", t))

    if args.precision or args.all:
        precision_server = MockPrecisionServer(port=8002)
        t = threading.Thread(target=precision_server.run, daemon=True)
        t.start()
        threads.append(("Precision", t))

    if args.backend or args.all:
        backend_server = MockBackendServer(port=8088)
        # 메인 스레드에서 백엔드 실행 (마지막 서버)
        if not (args.vlm or args.precision or args.all):
            backend_server.run()
        else:
            t = threading.Thread(target=backend_server.run, daemon=True)
            t.start()
            threads.append(("Backend", t))

    if threads:
        print("\n" + "="*60)
        print("AEGIS Mock 서버 실행 중")
        print("="*60)
        for name, _ in threads:
            print(f"  - {name} Mock 서버 실행 중...")
        print("\n종료하려면 Ctrl+C를 누르세요.\n")

        try:
            # 모든 스레드가 종료될 때까지 대기
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n서버를 종료합니다...")


if __name__ == "__main__":
    main()

