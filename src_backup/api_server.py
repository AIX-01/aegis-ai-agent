"""
FastAPI Server for AEGIS AI Agent
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
    """스트림 설정 / Stream configuration"""
    srt_urls: Optional[List[str]] = None  # SRT 스트림 URL 목록 (Optional, Redis에서 가져올 수 있음)
    workers: Optional[int] = 4
    vlm_endpoint: Optional[str] = "http://localhost:8001/analyze"
    precision_endpoint: Optional[str] = "http://localhost:8002/precision_analyze"
    mock_mode: Optional[bool] = False
    log_level: Optional[str] = "INFO"
    # Redis 설정 (Optional, 서버 기본값 사용 가능)
    redis_host: Optional[str] = None
    redis_port: Optional[int] = None
    redis_db: Optional[int] = None
    redis_password: Optional[str] = None


class StartResponse(BaseModel):
    """시작 응답 / Start response"""
    status: str
    message: str
    stream_count: int
    worker_count: int


class StatusResponse(BaseModel):
    """상태 응답 / Status response"""
    status: str
    running: bool
    stream_count: int
    statistics: dict


# =========================
# API 서버
# =========================

class AegisAPIServer:
    """AEGIS Agent API Server"""

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
        Initialize API server

        Args:
            host: Server host
            port: Server port
            redis_host: Redis host
            redis_port: Redis port
            redis_db: Redis DB index
            redis_password: Redis password
        """
        self.host = host
        self.port = port
        self.app = FastAPI(title="AEGIS AI Agent API", version="1.0.0")
        self.logger = logging.getLogger("aegis-agent.api")

        # Redis config
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self.redis_password = redis_password

        # Agent instance
        self.agent: Optional[AegisAgent] = None
        self.agent_thread: Optional[threading.Thread] = None
        
        # Redis client
        self.redis_client: Optional[redis.Redis] = None
        self.redis_monitor_thread: Optional[threading.Thread] = None
        self.redis_monitor_running = False

        # Initialize Redis connection
        self._connect_redis()

        # Setup routes
        self._setup_routes()

    def _connect_redis(self):
        """Connect to Redis"""
        try:
            self.redis_client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                password=self.redis_password,
                decode_responses=True
            )
            self.redis_client.ping()
            self.logger.info(f"Connected to Redis at {self.redis_host}:{self.redis_port}")
        except Exception as e:
            self.logger.warning(f"Failed to connect to Redis at startup: {e}")
            # Don't crash, retry later or allow running without Redis

    def _setup_routes(self):
        """Setup FastAPI routes"""

        @self.app.post("/api/streams/start", response_model=StartResponse)
        async def start_streams(config: StreamConfig):
            """
            스트림 분석 시작
            Start stream analysis
            """
            if self.agent is not None and self.agent_thread and self.agent_thread.is_alive():
                raise HTTPException(
                    status_code=400,
                    detail="Agent is already running. Stop it first."
                )

            # 요청에 Redis 설정이 있으면 재연결 시도 (옵션)
            if config.redis_host:
                self.logger.info("Reconnecting to Redis with request config")
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
                            self.logger.info(f"Loaded {len(target_srt_urls)} streams from Redis")
                    except Exception as e:
                        self.logger.error(f"Failed to load streams from Redis: {e}")

            if not target_srt_urls:
                raise HTTPException(
                    status_code=400,
                    detail="srt_urls cannot be empty (not found in request or Redis)"
                )

            try:
                # Create configuration
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

                # Create agent
                self.agent = AegisAgent(agent_config)

                # Start agent in separate thread
                self.agent_thread = threading.Thread(
                    target=self.agent.run,
                    daemon=False
                )
                self.agent_thread.start()
                
                # Start Redis status updater if connected
                if self.redis_client:
                    self.redis_monitor_running = True
                    self.redis_monitor_thread = threading.Thread(
                        target=self._redis_status_updater,
                        daemon=True
                    )
                    self.redis_monitor_thread.start()

                self.logger.info(
                    f"Agent started with {len(target_srt_urls)} streams"
                )

                return StartResponse(
                    status="success",
                    message="Agent started successfully",
                    stream_count=len(target_srt_urls),
                    worker_count=config.workers,
                )

            except Exception as e:
                self.logger.error(f"Failed to start agent: {e}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to start agent: {str(e)}"
                )

        @self.app.post("/api/streams/stop")
        async def stop_streams():
            """
            스트림 분석 중지
            Stop stream analysis
            """
            if self.agent is None:
                raise HTTPException(
                    status_code=400,
                    detail="No agent is running"
                )

            try:
                self.logger.info("Stopping agent...")
                
                # Stop Redis monitor
                self.redis_monitor_running = False
                if self.redis_monitor_thread:
                    self.redis_monitor_thread.join(timeout=2)
                
                self.agent.shutdown()

                # Wait for thread to finish
                if self.agent_thread:
                    self.agent_thread.join(timeout=10)

                self.agent = None
                self.agent_thread = None
                
                # Update status to stopped in Redis
                if self.redis_client:
                    try:
                        self.redis_client.set("aegis:agent:status", json.dumps({
                            "status": "stopped",
                            "running": False,
                            "timestamp": time.time()
                        }))
                    except Exception as e:
                        self.logger.error(f"Failed to update Redis status: {e}")

                self.logger.info("Agent stopped successfully")

                return {
                    "status": "success",
                    "message": "Agent stopped successfully"
                }

            except Exception as e:
                self.logger.error(f"Failed to stop agent: {e}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to stop agent: {str(e)}"
                )

        @self.app.get("/api/streams/status", response_model=StatusResponse)
        async def get_status():
            """
            현재 상태 조회
            Get current status
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
                self.logger.error(f"Failed to get status: {e}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to get status: {str(e)}"
                )

        @self.app.get("/health")
        async def health():
            """Health check"""
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
        """Collect statistics from agent"""
        if not self.agent:
            return {}
            
        return {
            "queue": self.agent.queue_manager.get_stats(),
            "windowing": self.agent.window_manager.get_stats(),
            "consumer": self.agent.consumer_pool.get_stats(),
            "trigger_analyzer": self.agent.trigger_analyzer.get_stats(),
            "pending_buffer": self.agent.pending_buffer_manager.get_stats(),
            "vlm_client": self.agent.vlm_client.get_stats(),
            "precision_client": self.agent.precision_client.get_stats(),
            "producers": {
                producer.camera_id: {
                    "frames": producer.total_frames_captured,
                    "is_local_file": producer.is_local_file
                }
                for producer in self.agent.producers
            }
        }

    def _redis_status_updater(self):
        """Background thread to update status in Redis"""
        self.logger.info("Starting Redis status updater")
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
                self.logger.error(f"Error updating Redis status: {e}")
                time.sleep(5)

    def run(self):
        """Run API server"""
        import uvicorn
        self.logger.info(f"Starting AEGIS API Server on {self.host}:{self.port}")
        uvicorn.run(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info"
        )


# =========================
# Entry point
# =========================

def main():
    """Main entry point for API server"""
    import argparse
    from .utils import setup_logging

    parser = argparse.ArgumentParser(
        description="AEGIS AI Agent API Server"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="API server host (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="API server port (default: 8080)"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)"
    )
    parser.add_argument(
        "--redis-host",
        type=str,
        default="localhost",
        help="Redis host (default: localhost)"
    )
    parser.add_argument(
        "--redis-port",
        type=int,
        default=6379,
        help="Redis port (default: 6379)"
    )
    parser.add_argument(
        "--redis-db",
        type=int,
        default=0,
        help="Redis DB index (default: 0)"
    )
    parser.add_argument(
        "--redis-password",
        type=str,
        default=None,
        help="Redis password"
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level)

    # Start API server
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
