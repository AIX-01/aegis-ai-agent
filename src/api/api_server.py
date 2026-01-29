"""
FastAPI 서버 - AEGIS AI Agent
스프링부트로부터 SRT URL을 받아서 처리하는 API 서버
"""
import logging
import json
import threading
import time
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import redis

from .config import Config
from .main import AegisAgent


# =========================
# API 모델
# =========================

class StreamConfig(BaseModel):
    """스트림 설정"""
    srt_urls: Optional[List[str]] = None  # SRT 스트림 URL 목록 (선택 사항, Redis에서 가져올 수 있음)
    workers: Optional[int] = 4
    vlm_endpoint: Optional[str] = "http://localhost:8001/analyze"
    precision_endpoint: Optional[str] = "http://localhost:8002/precision_analyze"
    mock_mode: Optional[bool] = False
    log_level: Optional[str] = "INFO"
    # Redis 설정 (선택 사항, 서버 기본값 사용 가능)
    redis_host: Optional[str] = None
    redis_port: Optional[int] = None
    redis_db: Optional[int] = None
    redis_password: Optional[str] = None


class StartResponse(BaseModel):
    """시작 응답"""
    status: str
    message: str
    stream_count: int
    worker_count: int


class StatusResponse(BaseModel):
    """상태 응답"""
    status: str
    running: bool
    stream_count: int
    statistics: dict


# =========================
# API 서버
# =========================

class AegisAPIServer:
    """AEGIS Agent API 서버"""

    def __init__(
        self, 
        host: str = "0.0.0.0", 
        port: int = 8080,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_db: int = 0,
        redis_password: Optional[str] = None
    ):
        """
        API 서버 초기화

        Args:
            host: 서버 호스트
            port: 서버 포트
            redis_host: Redis 호스트
            redis_port: Redis 포트
            redis_db: Redis DB 인덱스
            redis_password: Redis 비밀번호
        """
        self.host = host
        self.port = port
        self.app = FastAPI(title="AEGIS AI Agent API", version="1.0.0")
        self.logger = logging.getLogger("aegis-agent.api")

        # Redis 설정
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self.redis_password = redis_password

        # Agent 인스턴스
        self.agent: Optional[AegisAgent] = None
        self.agent_thread: Optional[threading.Thread] = None
        
        # Redis 클라이언트
        self.redis_client: Optional[redis.Redis] = None
        self.redis_monitor_thread: Optional[threading.Thread] = None
        self.redis_monitor_running = False

        # Redis 연결 초기화
        self._connect_redis()

        # 라우트 설정
        self._setup_routes()

    def _connect_redis(self):
        """Redis에 연결"""
        try:
            self.redis_client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                password=self.redis_password,
                decode_responses=True
            )
            self.redis_client.ping()
            self.logger.info(f"Redis에 연결되었습니다: {self.redis_host}:{self.redis_port}")
        except Exception as e:
            self.logger.warning(f"시작 시 Redis 연결 실패: {e}")
            # 충돌하지 않고, 나중에 재시도하거나 Redis 없이 실행 허용

    def _setup_routes(self):
        """FastAPI 라우트 설정"""

        @self.app.post("/api/streams/start", response_model=StartResponse)
        async def start_streams(config: StreamConfig):
            """
            스트림 분석 시작
            """
            if self.agent is not None and self.agent_thread and self.agent_thread.is_alive():
                raise HTTPException(
                    status_code=400,
                    detail="Agent가 이미 실행 중입니다. 먼저 중지하세요."
                )

            # 요청에 Redis 설정이 있으면 재연결 시도 (선택 사항)
            if config.redis_host:
                self.logger.info("요청 설정으로 Redis에 재연결합니다")
                self.redis_host = config.redis_host
                self.redis_port = config.redis_port or self.redis_port
                self.redis_db = config.redis_db if config.redis_db is not None else self.redis_db
                self.redis_password = config.redis_password or self.redis_password
                self._connect_redis()

            # srt_urls가 없으면 Redis에서 조회
            target_srt_urls = config.srt_urls
            if not target_srt_urls:
                if self.redis_client:
                    try:
                        cached_streams = self.redis_client.get("aegis:streams:config")
                        if cached_streams:
                            target_srt_urls = json.loads(cached_streams)
                            self.logger.info(f"Redis에서 {len(target_srt_urls)}개의 스트림을 로드했습니다")
                    except Exception as e:
                        self.logger.error(f"Redis에서 스트림 로드 실패: {e}")

            if not target_srt_urls:
                raise HTTPException(
                    status_code=400,
                    detail="srt_urls는 비워둘 수 없습니다 (요청 또는 Redis에서 찾을 수 없음)"
                )

            try:
                # 설정 생성
                agent_config = Config(
                    srt_urls=target_srt_urls,
                    num_workers=config.workers,
                    vlm_endpoint=config.vlm_endpoint,
                    precision_endpoint=config.precision_endpoint,
                    mock_mode=config.mock_mode,
                    log_level=config.log_level,
                    redis_host=self.redis_host,
                    redis_port=self.redis_port,
                    redis_db=self.redis_db,
                    redis_password=self.redis_password
                )

                # Agent 생성
                self.agent = AegisAgent(agent_config)

                # 별도 스레드에서 Agent 시작
                self.agent_thread = threading.Thread(
                    target=self.agent.run,
                    daemon=False
                )
                self.agent_thread.start()
                
                # 연결된 경우 Redis 상태 업데이터 시작
                if self.redis_client:
                    self.redis_monitor_running = True
                    self.redis_monitor_thread = threading.Thread(
                        target=self._redis_status_updater,
                        daemon=True
                    )
                    self.redis_monitor_thread.start()

                self.logger.info(
                    f"{len(target_srt_urls)}개의 스트림으로 Agent를 시작했습니다"
                )

                return StartResponse(
                    status="success",
                    message="Agent가 성공적으로 시작되었습니다",
                    stream_count=len(target_srt_urls),
                    worker_count=config.workers,
                )

            except Exception as e:
                self.logger.error(f"Agent 시작 실패: {e}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"Agent 시작 실패: {str(e)}"
                )

        @self.app.post("/api/streams/stop")
        async def stop_streams():
            """
            스트림 분석 중지
            """
            if self.agent is None:
                raise HTTPException(
                    status_code=400,
                    detail="실행 중인 Agent가 없습니다"
                )

            try:
                self.logger.info("Agent를 중지합니다...")
                
                # Redis 모니터 중지
                self.redis_monitor_running = False
                if self.redis_monitor_thread:
                    self.redis_monitor_thread.join(timeout=2)
                
                self.agent.shutdown()

                # 스레드가 끝날 때까지 대기
                if self.agent_thread:
                    self.agent_thread.join(timeout=10)

                self.agent = None
                self.agent_thread = None
                
                # Redis에서 상태를 '중지됨'으로 업데이트
                if self.redis_client:
                    try:
                        self.redis_client.set("aegis:agent:status", json.dumps({
                            "status": "stopped",
                            "running": False,
                            "timestamp": time.time()
                        }))
                    except Exception as e:
                        self.logger.error(f"Redis 상태 업데이트 실패: {e}")

                self.logger.info("Agent가 성공적으로 중지되었습니다")

                return {
                    "status": "success",
                    "message": "Agent가 성공적으로 중지되었습니다"
                }

            except Exception as e:
                self.logger.error(f"Agent 중지 실패: {e}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"Agent 중지 실패: {str(e)}"
                )

        @self.app.get("/api/streams/status", response_model=StatusResponse)
        async def get_status():
            """
            현재 상태 조회
            """
            if self.agent is None:
                return StatusResponse(
                    status="stopped",
                    running=False,
                    stream_count=0,
                    statistics={}
                )

            try:
                stats = self._collect_stats()
                return StatusResponse(
                    status="running",
                    running=True,
                    stream_count=len(self.agent.producers),
                    statistics=stats
                )

            except Exception as e:
                self.logger.error(f"상태 조회 실패: {e}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"상태 조회 실패: {str(e)}"
                )

        @self.app.get("/health")
        async def health():
            """상태 체크"""
            redis_status = "disconnected"
            if self.redis_client:
                try:
                    if self.redis_client.ping():
                        redis_status = "connected"
                except:
                    pass
                    
            return {
                "status": "healthy",
                "agent_running": self.agent is not None,
                "redis_status": redis_status
            }

    def _collect_stats(self):
        """Agent에서 통계 수집"""
        if not self.agent:
            return {}
            
        return {
            "queue": self.agent.queue_manager.get_stats(),
            "windowing": self.agent.window_manager.get_stats(),
            "consumer": self.agent.consumer_pool.get_stats(),
            "vlm_client": self.agent.vlm_client.get_stats(),
            "precision_client": self.agent.precision_client.get_stats(),
            "producers": {
                producer.camera_id: {
                    "frames": producer.total_frames_captured,
                    "is_local_file": producer.is_local_file
                }
                for producer in self.agent.producers.values()
            }
        }

    def _redis_status_updater(self):
        """Redis에 상태를 업데이트하는 백그라운드 스레드"""
        self.logger.info("Redis 상태 업데이터 시작")
        while self.redis_monitor_running and self.agent:
            try:
                stats = self._collect_stats()
                status_data = {
                    "status": "running",
                    "running": True,
                    "stream_count": len(self.agent.producers),
                    "statistics": stats,
                    "timestamp": time.time()
                }
                self.redis_client.set("aegis:agent:status", json.dumps(status_data))
                # 5초마다 업데이트
                time.sleep(5)
            except Exception as e:
                self.logger.error(f"Redis 상태 업데이트 중 오류 발생: {e}")
                time.sleep(5)

    def run(self):
        """API 서버 실행"""
        import uvicorn
        self.logger.info(f"AEGIS API 서버를 {self.host}:{self.port}에서 시작합니다")
        uvicorn.run(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info"
        )


# =========================
# 진입점
# =========================

def main():
    """API 서버의 메인 진입점"""
    import argparse
    from .utils import setup_logging

    parser = argparse.ArgumentParser(
        description="AEGIS AI Agent API 서버"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="API 서버 호스트 (기본값: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="API 서버 포트 (기본값: 8080)"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="로깅 레벨 (기본값: INFO)"
    )
    parser.add_argument(
        "--redis-host",
        type=str,
        default="localhost",
        help="Redis 호스트 (기본값: localhost)"
    )
    parser.add_argument(
        "--redis-port",
        type=int,
        default=6379,
        help="Redis 포트 (기본값: 6379)"
    )
    parser.add_argument(
        "--redis-db",
        type=int,
        default=0,
        help="Redis DB 인덱스 (기본값: 0)"
    )
    parser.add_argument(
        "--redis-password",
        type=str,
        default=None,
        help="Redis 비밀번호"
    )

    args = parser.parse_args()

    # 로깅 설정
    setup_logging(args.log_level)

    # API 서버 시작
    server = AegisAPIServer(
        host=args.host, 
        port=args.port,
        redis_host=args.redis_host,
        redis_port=args.redis_port,
        redis_db=args.redis_db,
        redis_password=args.redis_password
    )
    server.run()


if __name__ == "__main__":
    main()
