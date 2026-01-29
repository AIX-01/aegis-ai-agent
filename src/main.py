"""
AEGIS AI Agent의 메인 진입점 - 간소화된 트리거 분석 파이프라인
"""
import argparse
import sys
import threading
import time
from typing import List, Dict

from .config import Config
from .utils import setup_logging, setup_signal_handlers
from .queue_manager import QueueManager
from .windowing import WindowManager
from .producer import FrameProducer
from .vlm_client import VLMClient
from .consumer import ConsumerPool
from .precision_client import PrecisionClient
from .backend_client import BackendClient
from .mock_server import MockVLMServer, MockPrecisionServer
from .redis_manager import RedisManager


class AegisAgent:
    """AEGIS AI Agent의 메인 오케스트레이터 - 간소화된 파이프라인"""

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
        self.vlm_client = VLMClient(config)
        self.precision_client = PrecisionClient(config)
        self.backend_client = BackendClient(config) # 백엔드 클라이언트 추가

        # 간소화된 파이프라인을 사용하는 컨슈머 풀
        self.consumer_pool = ConsumerPool(
            config=config,
            queue_manager=self.queue_manager,
            vlm_client=self.vlm_client,
            precision_client=self.precision_client,
            backend_client=self.backend_client, # 컨슈머에 백엔드 클라이언트 주입
        )

        # 동적 스트림 설정을 위한 Redis 매니저
        self.redis_manager = RedisManager(config, self._update_producers)

        # 프로듀서 관리 (카메라 ID를 키로 사용)
        self.producers: Dict[str, FrameProducer] = {}
        self.producer_lock = threading.Lock()
        self.shutdown_event = threading.Event()

        # 정상 종료(graceful shutdown) 설정
        setup_signal_handlers(self.shutdown)

        # 모의 서버 스레드
        self.mock_vlm_server_thread = None
        self.mock_precision_server_thread = None

    def start(self):
        """모든 컴포넌트를 시작합니다."""
        self.logger.info("=" * 80)
        self.logger.info("AEGIS AI Agent - 간소화된 트리거 분석 파이프라인")
        self.logger.info("=" * 80)

        if self.config.mock_mode:
            self._start_mock_servers()

        self.consumer_pool.start()
        self.redis_manager.start()

        self.logger.info("Redis에서 초기 카메라 설정을 수행합니다...")
        self._update_producers()

        self.logger.info("시스템이 실행 중입니다. Redis 업데이트를 수신 대기합니다. 중지하려면 Ctrl+C를 누르세요.")

    def _start_mock_servers(self):
        """모의 모드에서 모의 VLM 및 정밀 분석 서버를 시작합니다."""
        self.logger.info(f"모의 VLM 서버를 {self.config.mock_vlm_port} 포트에서 시작합니다.")
        mock_vlm_server = MockVLMServer(self.config.mock_vlm_port)
        self.mock_vlm_server_thread = threading.Thread(target=mock_vlm_server.run, daemon=True)
        self.mock_vlm_server_thread.start()

        self.logger.info(f"모의 정밀 분석 서버를 {self.config.mock_precision_port} 포트에서 시작합니다.")
        mock_precision_server = MockPrecisionServer(self.config.mock_precision_port)
        self.mock_precision_server_thread = threading.Thread(target=mock_precision_server.run, daemon=True)
        self.mock_precision_server_thread.start()
        time.sleep(2)

    def _update_producers(self):
        """
        Redis의 최신 카메라 목록을 기반으로 프로듀서를 업데이트하는 콜백 함수입니다.
        """
        with self.producer_lock:
            self.logger.info("Redis 카메라 목록을 기반으로 프로듀서를 업데이트합니다...")
            try:
                # Redis에서 가져온 카메라 정보를 {id: {id, name, location}} 형태의 딕셔너리로 변환
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
                    )
                    producer.start()
                    self.producers[cam_id] = producer

                for cam_id in ids_to_remove:
                    self.logger.info(f"프로듀서를 중지합니다: {cam_id}")
                    producer = self.producers.pop(cam_id, None)
                    if producer:
                        producer.stop()

                self.logger.info(f"프로듀서 업데이트 완료. 총 프로듀서 수: {len(self.producers)}")

            except Exception as e:
                self.logger.error(f"프로듀서 업데이트 중 오류 발생: {e}", exc_info=True)

    def run(self):
        """메인 실행 루프"""
        try:
            self.start()
            while not self.shutdown_event.is_set():
                time.sleep(10)
                self._log_stats()
        except KeyboardInterrupt:
            self.logger.info("키보드 인터럽트를 수신했습니다.")
        finally:
            self.shutdown()

    def _log_stats(self):
        """시스템 통계를 기록합니다."""
        self.logger.info("=" * 20 + " 시스템 통계 " + "=" * 20)
        self.logger.info(f"실행 중인 프로듀서 수: {len(self.producers)}")
        # 필요한 경우 여기에 다른 통계 로깅 추가 (예: 컨슈머, 큐)
        self.logger.info("=" * 50)


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

        self._log_stats()
        self.logger.info("종료 완료")


def parse_args():
    """커맨드 라인 인자를 파싱합니다."""
    parser = argparse.ArgumentParser(description="AEGIS AI Agent - 간소화된 파이프라인")
    parser.add_argument("--workers", type=int, help="컨슈머 워커 스레드 수")
    # CLI에서 오버라이드해야 하는 다른 관련 인자를 Config에서 추가
    parser.add_argument("--mock", action="store_true", help="모의 서버 활성화")
    parser.add_argument("--log-level", type=str, default="INFO", help="로깅 레벨")
    return parser.parse_args()


def main():
    """메인 진입점"""
    args = parse_args()
    config = Config()

    # 제공된 경우 CLI 인자로 설정 오버라이드
    if args.workers:
        config.num_workers = args.workers
    if args.mock:
        config.mock_mode = True
    config.log_level = args.log_level

    agent = AegisAgent(config)
    agent.run()


if __name__ == "__main__":
    main()
