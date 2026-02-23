"""
AEGIS AI Agent의 메인 진입점 - LangGraph 기반 분석 파이프라인 (FastAPI 기반)

AGENT_MODE에 따라 다른 컴포넌트를 시작합니다:
- all: Producer + Consumer (로컬 queue.Queue) - 기존과 100% 동일
- ingest: Producer만 (SQS로 태스크 전송, EFS에 패킷 덤프)
- worker: Consumer만 (SQS에서 태스크 수신, EFS에서 패킷 읽기)
"""
import argparse
import threading
import time
from typing import Dict, Optional, Set
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException

from .config import Config
from .utils import setup_logging
from .core.queue_manager import QueueManager
from .core.windowing import WindowManager
from .core.producer import FrameProducer
from .core.consumer import ConsumerPool
from .core.redis_manager import RedisManager
from .api.mock_server import MockVLMServer, MockBackendServer
from .adapters.queue_adapter import LocalQueueAdapter, SQSQueueAdapter


class AegisAgent:
    """AEGIS AI Agent의 메인 오케스트레이터 - AGENT_MODE=all (로컬 모드)"""

    def __init__(self, config: Config):
        """
        AEGIS Agent를 초기화합니다.

        Args:
            config: 시스템 설정 객체
        """
        self.config = config
        self.logger = setup_logging(config.log_level)

        # 핵심 컴포넌트
        self.queue_manager = QueueManager(max_size=config.queue_max_size)
        self.window_manager = WindowManager(config, self.queue_manager)

        # [신규] 카메라별 리소스 공유를 위한 딕셔너리
        self.packet_buffers = {}
        self.source_streams = {}

        # LangGraph 기반 컨슈머 풀
        self.consumer_pool = ConsumerPool(
            config=config,
            queue_manager=self.queue_manager,
            packet_buffers=self.packet_buffers,
            source_streams=self.source_streams
        )

        # 동적 스트림 설정을 위한 Redis 매니저
        self.redis_manager = RedisManager(config, self._update_producers)

        # 프로듀서 관리 (카메라 ID를 키로 사용)
        self.producers: Dict[str, FrameProducer] = {}
        self.producer_lock = threading.Lock()
        self.shutdown_event = threading.Event()

        # 모의 서버 스레드
        self.mock_vlm_server_thread = None
        self.mock_backend_server_thread = None

    def start(self):
        """모든 컴포넌트를 시작합니다."""
        self.logger.info("=" * 80)
        self.logger.info("AEGIS AI Agent - LangGraph 기반 분석 파이프라인 (mode=all)")
        real_components = [name for name, flag in [("VLM", self.config.real_vlm), ("Backend", self.config.real_backend)] if flag]
        self.logger.info(f"실제 서버: {', '.join(real_components) if real_components else '없음 (전체 Mock)'}")
        self.logger.info("=" * 80)

        self._start_mock_servers()

        self.consumer_pool.start()
        self.redis_manager.start()

        self.logger.info("Redis에서 초기 카메라 설정을 수행합니다...")
        self._update_producers()

        self.logger.info("시스템이 시작되었습니다.")

    def _start_mock_servers(self):
        """모의 모드에서 선택적으로 모의 서버를 시작합니다."""

        # VLM 모의 서버
        if not self.config.real_vlm:
            self.logger.info(f"모의 VLM 서버를 {self.config.mock_vlm_port} 포트에서 시작합니다.")
            mock_vlm_server = MockVLMServer(self.config.mock_vlm_port)
            self.mock_vlm_server_thread = threading.Thread(target=mock_vlm_server.run, daemon=True)
            self.mock_vlm_server_thread.start()
        else:
            self.logger.info("실제 VLM 서버를 사용합니다. (Mock VLM 서버 실행 안 함)")

        # 백엔드 모의 서버
        if not self.config.real_backend:
            self.logger.info(f"모의 백엔드 서버를 {self.config.mock_backend_port} 포트에서 시작합니다.")
            mock_backend_server = MockBackendServer(self.config.mock_backend_port)
            self.mock_backend_server_thread = threading.Thread(target=mock_backend_server.run, daemon=True)
            self.mock_backend_server_thread.start()
        else:
            self.logger.info("실제 백엔드 서버를 사용합니다. (Mock 백엔드 서버 실행 안 함)")

        time.sleep(2) # 서버가 시작될 때까지 잠시 대기

    def _update_producers(self):
        """
        Redis의 최신 카메라 목록을 기반으로 프로듀서를 업데이트하는 콜백 함수입니다.
        """
        with self.producer_lock:
            self.logger.info("Redis 카메라 목록을 기반으로 프로듀서를 업데이트합니다...")
            try:
                target_cameras_list = self.redis_manager.get_analysis_cameras()
                target_cameras = {cam['id']: cam for cam in target_cameras_list if 'id' in cam}

                current_camera_ids = set(self.producers.keys())
                target_camera_ids = set(target_cameras.keys())

                ids_to_add = target_camera_ids - current_camera_ids
                ids_to_remove = current_camera_ids - target_camera_ids

                for cam_id in ids_to_add:
                    if self.shutdown_event.is_set(): break
                    camera_info = target_cameras[cam_id]
                    self.logger.info(f"새로운 프로듀서를 시작합니다: {cam_id} (이름: {camera_info.get('name', 'unknown')})")
                    producer = FrameProducer(
                        camera_info=camera_info,
                        config=self.config,
                        frame_callback=self.window_manager.add_frame,
                        shutdown_event=self.shutdown_event,
                        source_streams_dict=self.source_streams # 공유 딕셔너리 전달
                    )

                    # PacketBuffer를 공유 딕셔너리에 등록
                    self.packet_buffers[cam_id] = producer.packet_buffer

                    producer.start()
                    self.producers[cam_id] = producer

                for cam_id in ids_to_remove:
                    self.logger.info(f"프로듀서를 중지합니다: {cam_id}")
                    producer = self.producers.pop(cam_id, None)
                    if producer:
                        producer.stop()
                    # 리소스 정리
                    self.packet_buffers.pop(cam_id, None)
                    self.source_streams.pop(cam_id, None)

                self.logger.info(f"프로듀서 업데이트 완료. 총 프로듀서 수: {len(self.producers)}")

            except Exception as e:
                self.logger.error(f"프로듀서 업데이트 중 오류 발생: {e}", exc_info=True)

    def shutdown(self):
        """모든 컴포넌트를 정상적으로 종료합니다."""
        if self.shutdown_event.is_set():
            return
        self.logger.info("정상 종료를 시작합니다...")
        self.shutdown_event.set()

        self.redis_manager.shutdown()

        with self.producer_lock:
            self.logger.info(f"{len(self.producers)}개의 프로듀서를 중지합니다...")
            for producer in self.producers.values():
                if producer.is_alive():
                    producer.stop()
                    producer.join(timeout=5)
            self.producers.clear()

        self.window_manager.shutdown()
        self.consumer_pool.shutdown()

        self.logger.info("종료 완료")

    def get_status(self) -> Dict:
        """에이전트의 현재 상태를 반환합니다."""
        return {
            "mode": "all",
            "producers": len(self.producers),
            "queue_size": self.queue_manager.size(),
            "consumer_stats": self.consumer_pool.get_stats(),
            "window_stats": self.window_manager.get_stats(),
        }


class AegisIngestAgent:
    """AEGIS Ingest Agent - AGENT_MODE=ingest (Producer만 실행, SQS/EFS로 전송)"""

    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_logging(config.log_level)

        # SQS 큐 어댑터 (Consumer 대신 SQS로 전송)
        self.queue_adapter = SQSQueueAdapter(
            queue_url=config.sqs_queue_url,
            s3_bucket=config.s3_bucket,
            region=config.aws_region,
        )

        # QueueManager + WindowManager (기존 흐름 유지, 큐 출력만 SQS로 전환)
        self.queue_manager = QueueManager(max_size=config.queue_max_size)
        self.window_manager = WindowManager(config, self.queue_manager)

        # EFS 패킷 덤프
        from .adapters.efs_buffer import EFSPacketWriter
        self.efs_writer = EFSPacketWriter(config.efs_buffer_path)

        # Redis 매니저 (카메라 관리)
        self.redis_manager = RedisManager(config, self._update_producers)

        # 프로듀서 관리
        self.producers: Dict[str, FrameProducer] = {}
        self.packet_buffers = {}
        self.source_streams = {}
        self.producer_lock = threading.Lock()
        self.shutdown_event = threading.Event()

        # SQS 전송 스레드 (QueueManager → SQS)
        self._sqs_forwarder_thread = None

    def start(self):
        """Ingest 컴포넌트를 시작합니다."""
        self.logger.info("=" * 80)
        self.logger.info("AEGIS AI Agent - Ingest 모드 (Producer + SQS 전송)")
        self.logger.info(f"SQS Queue: {self.config.sqs_queue_url}")
        self.logger.info(f"EFS Path: {self.config.efs_buffer_path}")
        self.logger.info("=" * 80)

        # SQS 포워더 시작 (QueueManager에서 꺼내서 SQS로 전송)
        self._sqs_forwarder_thread = threading.Thread(
            target=self._sqs_forwarder_loop, daemon=True, name="sqs-forwarder"
        )
        self._sqs_forwarder_thread.start()

        self.redis_manager.start()
        self.logger.info("Redis에서 초기 카메라 설정을 수행합니다...")
        self._update_producers()

        self.logger.info("Ingest 모드 시작 완료.")

    def _sqs_forwarder_loop(self):
        """QueueManager에서 태스크를 꺼내 SQS로 전송하는 루프"""
        while not self.shutdown_event.is_set():
            task = self.queue_manager.get(timeout=1.0)
            if task is None:
                continue
            if not self.queue_adapter.put(task):
                self.logger.error("SQS 전송 실패, 태스크 드롭")

    def _update_producers(self):
        """Redis 카메라 목록 기반 프로듀서 업데이트"""
        with self.producer_lock:
            self.logger.info("Redis 카메라 목록을 기반으로 프로듀서를 업데이트합니다...")
            try:
                target_cameras_list = self.redis_manager.get_analysis_cameras()
                target_cameras = {cam['id']: cam for cam in target_cameras_list if 'id' in cam}

                current_camera_ids = set(self.producers.keys())
                target_camera_ids = set(target_cameras.keys())

                ids_to_add = target_camera_ids - current_camera_ids
                ids_to_remove = current_camera_ids - target_camera_ids

                for cam_id in ids_to_add:
                    if self.shutdown_event.is_set(): break
                    camera_info = target_cameras[cam_id]
                    self.logger.info(f"새로운 프로듀서를 시작합니다: {cam_id}")
                    producer = FrameProducer(
                        camera_info=camera_info,
                        config=self.config,
                        frame_callback=self.window_manager.add_frame,
                        shutdown_event=self.shutdown_event,
                        source_streams_dict=self.source_streams,
                        efs_writer=self.efs_writer,  # EFS 덤프용
                    )

                    self.packet_buffers[cam_id] = producer.packet_buffer
                    producer.start()
                    self.producers[cam_id] = producer

                for cam_id in ids_to_remove:
                    self.logger.info(f"프로듀서를 중지합니다: {cam_id}")
                    producer = self.producers.pop(cam_id, None)
                    if producer:
                        producer.stop()
                    self.packet_buffers.pop(cam_id, None)
                    self.source_streams.pop(cam_id, None)

                # 비활성 카메라의 EFS 데이터 정리
                self.efs_writer.cleanup_old_cameras(set(self.producers.keys()))

                self.logger.info(f"프로듀서 업데이트 완료. 총 프로듀서 수: {len(self.producers)}")

            except Exception as e:
                self.logger.error(f"프로듀서 업데이트 중 오류 발생: {e}", exc_info=True)

    def shutdown(self):
        """Ingest 컴포넌트를 종료합니다."""
        if self.shutdown_event.is_set():
            return
        self.logger.info("Ingest 모드 종료를 시작합니다...")
        self.shutdown_event.set()

        self.redis_manager.shutdown()

        with self.producer_lock:
            for producer in self.producers.values():
                if producer.is_alive():
                    producer.stop()
                    producer.join(timeout=5)
            self.producers.clear()

        self.window_manager.shutdown()
        self.logger.info("Ingest 모드 종료 완료")

    def get_status(self) -> Dict:
        return {
            "mode": "ingest",
            "producers": len(self.producers),
            "queue_size": self.queue_manager.size(),
            "sqs_queue_size": self.queue_adapter.size(),
        }


class AegisWorkerAgent:
    """AEGIS Worker Agent - AGENT_MODE=worker (Consumer만 실행, SQS에서 수신)"""

    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_logging(config.log_level)

        # SQS 큐 어댑터
        self.queue_adapter = SQSQueueAdapter(
            queue_url=config.sqs_queue_url,
            s3_bucket=config.s3_bucket,
            region=config.aws_region,
        )

        # EFS 패킷 리더 (클립 생성용)
        from .adapters.efs_buffer import EFSPacketReader
        self.efs_reader = EFSPacketReader(config.efs_buffer_path)

        # 로컬 QueueManager (SQS → 로컬 큐 → ConsumerPool)
        self.queue_manager = QueueManager(max_size=config.queue_max_size)

        # ConsumerPool (기존 로직 재사용, EFS 리더 전달)
        self.consumer_pool = ConsumerPool(
            config=config,
            queue_manager=self.queue_manager,
            efs_reader=self.efs_reader,
        )

        self.shutdown_event = threading.Event()
        self._sqs_poller_thread = None

    def start(self):
        """Worker 컴포넌트를 시작합니다."""
        self.logger.info("=" * 80)
        self.logger.info("AEGIS AI Agent - Worker 모드 (SQS Consumer + LangGraph)")
        self.logger.info(f"SQS Queue: {self.config.sqs_queue_url}")
        self.logger.info(f"EFS Path: {self.config.efs_buffer_path}")
        self.logger.info("=" * 80)

        # ConsumerPool 시작
        self.consumer_pool.start()

        # SQS 폴러 시작 (SQS → 로컬 QueueManager)
        self._sqs_poller_thread = threading.Thread(
            target=self._sqs_poller_loop, daemon=True, name="sqs-poller"
        )
        self._sqs_poller_thread.start()

        self.logger.info("Worker 모드 시작 완료.")

    def _sqs_poller_loop(self):
        """SQS에서 태스크를 폴링하여 로컬 QueueManager에 넣는 루프"""
        while not self.shutdown_event.is_set():
            task = self.queue_adapter.get(timeout=20.0)
            if task is None:
                continue
            self.queue_manager.put(task)

    def shutdown(self):
        """Worker 컴포넌트를 종료합니다."""
        if self.shutdown_event.is_set():
            return
        self.logger.info("Worker 모드 종료를 시작합니다...")
        self.shutdown_event.set()
        self.consumer_pool.shutdown()
        self.logger.info("Worker 모드 종료 완료")

    def get_status(self) -> Dict:
        return {
            "mode": "worker",
            "queue_size": self.queue_manager.size(),
            "sqs_queue_size": self.queue_adapter.size(),
            "consumer_stats": self.consumer_pool.get_stats(),
        }


# 전역 변수로 agent 인스턴스 관리 (FastAPI에서 접근하기 위함)
agent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 앱의 수명 주기 관리 (시작 및 종료 시 실행)"""
    global agent

    # 설정 로드 및 에이전트 초기화
    args = parse_args()
    config = Config()
    if args.workers:
        config.num_workers = args.workers

    if args.real_vlm:
        config.real_vlm = True
    if args.real_backend:
        config.real_backend = True

    if args.log_level:
        config.log_level = args.log_level.upper()

    config.__post_init__()

    logger = setup_logging(config.log_level)
    logger.info(f"AGENT_MODE: {config.agent_mode}")

    # AGENT_MODE에 따라 적절한 에이전트 생성
    if config.agent_mode == "all":
        agent = AegisAgent(config)
    elif config.agent_mode == "ingest":
        agent = AegisIngestAgent(config)
    elif config.agent_mode == "worker":
        agent = AegisWorkerAgent(config)
    else:
        raise ValueError(f"Unknown AGENT_MODE: {config.agent_mode}")

    agent.start()

    yield

    # 종료 시 실행
    if agent:
        agent.shutdown()


# FastAPI 앱 생성
app = FastAPI(title="AEGIS AI Agent API", lifespan=lifespan)


@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy"}


@app.get("/status")
async def get_agent_status():
    """에이전트 상태 조회 엔드포인트"""
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    return agent.get_status()



def parse_args():
    """커맨드 라인 인자를 파싱합니다."""
    parser = argparse.ArgumentParser(description="AEGIS AI Agent - LangGraph 기반 분석 파이프라인")
    parser.add_argument("--workers", type=int, help="컨슈머 워커 스레드 수")
    parser.add_argument("--real-vlm", action="store_true", help="VLM 실제 서버 사용")
    parser.add_argument("--real-backend", action="store_true", help="백엔드 실제 서버 사용")
    parser.add_argument("--log-level", type=str, help="로깅 레벨 (DEBUG, INFO, WARNING, ERROR)")
    return parser.parse_args()


def main():
    """메인 진입점"""
    # Uvicorn을 사용하여 FastAPI 앱 실행
    # 주의: uvicorn.run은 블로킹 호출이므로, 에이전트 로직은 lifespan에서 백그라운드로 실행됨

    # 인자 파싱은 lifespan 내부에서 다시 수행하거나,
    # 여기서 파싱한 후 환경 변수 등을 통해 전달해야 하지만,
    # 간단하게 lifespan 내부에서 다시 파싱하도록 구현함.
    # (uvicorn 실행 시 인자를 직접 전달받기 어려움)

    # Config에서 포트 설정 가져오기 (기본값 사용)
    config = Config()

    print(f"AEGIS AI Agent API 서버를 {config.agent_api_port} 포트에서 시작합니다.")
    uvicorn.run("src.app:app", host=config.agent_api_host, port=config.agent_api_port, reload=False)


if __name__ == "__main__":
    main()
