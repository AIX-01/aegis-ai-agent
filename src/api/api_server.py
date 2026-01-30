"""
FastAPI 서버 - AEGIS AI Agent
에이전트의 상태를 모니터링하고, 원격으로 시작/중지하는 API 서버입니다.
"""
import logging
import threading
import time
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# 상대 경로 임포트 오류를 방지하기 위해 경로 조작 (main.py가 아닌 api_server.py에서 직접 실행 시 필요)
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from app import AegisAgent
from utils import setup_logging


# =========================
# API 모델
# =========================

class StartRequest(BaseModel):
    """시작 요청 모델"""
    # API를 통해 시작 시 특정 설정을 오버라이드 할 수 있습니다.
    # 비워두면 config.py의 기본값을 사용합니다.
    mock_mode: Optional[bool] = None
    log_level: Optional[str] = None

class StatusResponse(BaseModel):
    """상태 응답 모델"""
    status: str
    running: bool
    mode: Optional[str] = None
    statistics: Optional[Dict[str, Any]] = None

# =========================
# API 서버
# =========================

class AegisAPIServer:
    """AEGIS Agent를 원격 제어하기 위한 API 서버"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8000):
        """
        API 서버 초기화
        Args:
            host: 서버가 바인딩할 호스트
            port: 서버가 리스닝할 포트
        """
        self.host = host
        self.port = port
        self.app = FastAPI(title="AEGIS AI Agent API", version="1.0.0")
        self.logger = logging.getLogger("aegis-agent.api")

        self.agent: Optional[AegisAgent] = None
        self.agent_thread: Optional[threading.Thread] = None
        
        self._setup_routes()

    def _setup_routes(self):
        """FastAPI 라우트 설정"""

        @self.app.post("/agent/start", response_model=StatusResponse)
        async def start_agent(request: StartRequest):
            """
            AEGIS Agent를 시작합니다.
            에이전트는 config.py에 정의된 설정을 기반으로 실행되며,
            Redis에 등록된 RTSP 스트림 정보를 바탕으로 분석을 시작합니다.
            """
            if self.agent and self.agent_thread and self.agent_thread.is_alive():
                raise HTTPException(status_code=400, detail="Agent가 이미 실행 중입니다.")

            try:
                # config.py를 기반으로 설정 객체 생성
                agent_config = Config()

                # API 요청으로 받은 값으로 설정 오버라이드
                if request.mock_mode is not None:
                    agent_config.mock_mode = request.mock_mode
                if request.log_level is not None:
                    agent_config.log_level = request.log_level.upper()
                
                # mock_mode 값에 따라 엔드포인트 동적 설정
                agent_config.__post_init__()

                self.agent = AegisAgent(agent_config)
                self.agent_thread = threading.Thread(target=self.agent.run, daemon=True)
                self.agent_thread.start()
                
                self.logger.info("AEGIS Agent 스레드를 시작했습니다.")
                time.sleep(3) # 에이전트가 초기화될 시간을 줍니다.

                return await get_status()

            except Exception as e:
                self.logger.error(f"Agent 시작 실패: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Agent 시작 실패: {str(e)}")

        @self.app.post("/agent/stop", response_model=StatusResponse)
        async def stop_agent():
            """
            실행 중인 AEGIS Agent를 정상적으로 종료합니다.
            """
            if not self.agent or not self.agent_thread or not self.agent_thread.is_alive():
                raise HTTPException(status_code=400, detail="실행 중인 Agent가 없습니다.")

            try:
                self.logger.info("Agent 종료 신호를 보냅니다...")
                self.agent.shutdown()
                self.agent_thread.join(timeout=10)

                self.agent = None
                self.agent_thread = None
                self.logger.info("Agent가 성공적으로 중지되었습니다.")
                
                return StatusResponse(status="stopped", running=False)

            except Exception as e:
                self.logger.error(f"Agent 중지 실패: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Agent 중지 실패: {str(e)}")

        @self.app.get("/agent/status", response_model=StatusResponse)
        async def get_status():
            """
            현재 Agent의 실행 상태와 통계를 조회합니다.
            """
            if not self.agent or not self.agent_thread or not self.agent_thread.is_alive():
                return StatusResponse(status="stopped", running=False)

            stats = {
                "producers": len(self.agent.producers),
                "queue_size": self.agent.queue_manager.size(),
                "consumer_stats": self.agent.consumer_pool.get_stats()
            }
            mode = "Mock" if self.agent.config.mock_mode else "Real"
            
            return StatusResponse(status="running", running=True, mode=mode, statistics=stats)

        @self.app.get("/health")
        async def health():
            return {"status": "healthy"}

    def run(self):
        """API 서버 실행"""
        import uvicorn
        self.logger.info(f"AEGIS API 서버를 {self.host}:{self.port}에서 시작합니다")
        uvicorn.run(self.app, host=self.host, port=self.port, log_level="info")


# =========================
# 진입점
# =========================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="AEGIS AI Agent API 서버")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="API 서버 호스트")
    parser.add_argument("--port", type=int, default=8000, help="API 서버 포트")
    parser.add_argument("--log-level", type=str, default="INFO", help="로깅 레벨")
    args = parser.parse_args()

    setup_logging(args.log_level)
    server = AegisAPIServer(host=args.host, port=args.port)
    server.run()

if __name__ == "__main__":
    main()
