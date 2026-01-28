"""
AEGIS AI Agent의 메인 진입점 - 2단계 트리거 분석 파이프라인
"""
import argparse
import sys
import threading
import time
from typing import List, Dict

from .config import Config
from .utils import setup_logging, setup_signal_handlers, get_camera_id
from .queue_manager import QueueManager
from .windowing import WindowManager
from .producer import FrameProducer
from .vlm_client import VLMClient
from .consumer import ConsumerPool
from .pending_buffer_manager import PendingBufferManager
from .trigger_analyzer import TriggerAnalyzer
from .precision_client import PrecisionClient
from .mock_server import MockVLMServer, MockPrecisionServer
from .redis_manager import RedisManager


class AegisAgent:
    """AEGIS AI Agent의 메인 오케스트레이터 - 2단계 파이프라인"""

    def __init__(self, config: Config):
        """
        AEGIS Agent를 초기화합니다.

        Args:
            config: 시스템 설정 객체
        """
        self.config = config
        self.logger = setup_logging(config.log_level)

        # 2단계 파이프라인을 위한 핵심 컴포넌트
        self.queue_manager = QueueManager(max_size=config.queue_max_size)
        self.window_manager = WindowManager(config, self.queue_manager)

        # 1단계: VLM 트리거 컴포넌트
        self.vlm_client = VLMClient(config)
        self.trigger_analyzer = TriggerAnalyzer(config)

        # 2단계: 정밀 분석 컴포넌트
        self.pending_buffer_manager = PendingBufferManager(config)
        self.precision_client = PrecisionClient(config)

        # 2단계 파이프라인을 포함한 컨슈머 풀
        self.consumer_pool = ConsumerPool(
            config=config,
            queue_manager=self.queue_manager,
            vlm_client=self.vlm_client,
            trigger_analyzer=self.trigger_analyzer,
            pending_buffer_manager=self.pending_buffer_manager,
            precision_client=self.precision_client,
        )

        # 동적 스트림 설정을 위한 Redis 매니저
        self.redis_manager = RedisManager(config, self._update_producers)

        # 프로듀서 관리
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
        self.logger.info("AEGIS AI Agent - 동적 2단계 트리거 분석 파이프라인")
        self.logger.info("=" * 80)
        # ... (설정 세부 정보 로깅)

        # 모의(mock) 모드가 활성화된 경우 모의 서버 시작
        if self.config.mock_mode:
            self._start_mock_servers()

        # 핵심 컴포넌트 시작
        self.consumer_pool.start()
        self.redis_manager.start()

        # Redis에서 초기 프로듀서 설정
        self.logger.info("Redis에서 초기 SRT 스트림 설정을 수행합니다...")
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
        Redis의 최신 SRT URL 목록을 기반으로 프로듀서를 업데이트하는 콜백 함수입니다.
        이 함수는 스레드에 안전합니다(thread-safe).
        """
        with self.producer_lock:
            self.logger.info("Redis 스트림 목록을 기반으로 프로듀서를 업데이트합니다...")
            try:
                target_urls = set(self.redis_manager.get_srt_urls())
                current_urls = set(self.producers.keys())

                urls_to_add = target_urls - current_urls
                urls_to_remove = current_urls - target_urls

                # 새로운 프로듀서 추가
                for url in urls_to_add:
                    if self.shutdown_event.is_set():
                        break
                    camera_id = get_camera_id(url, len(self.producers))
                    self.logger.info(f"새로운 프로듀서를 시작합니다: {url} (카메라 ID: {camera_id})")
                    producer = FrameProducer(
                        camera_id=camera_id,
                        srt_url=url,
                        config=self.config,
                        frame_callback=self.window_manager.add_frame,
                        shutdown_event=self.shutdown_event,
                    )
                    producer.start()
                    self.producers[url] = producer

                # 오래된 프로듀서 중지 및 제거
                for url in urls_to_remove:
                    self.logger.info(f"프로듀서를 중지합니다: {url}")
                    producer = self.producers.pop(url, None)
                    if producer:
                        # FrameProducer는 종료를 알리는 메서드가 필요합니다.
                        producer.stop() # producer에 stop() 메서드가 있다고 가정합니다.

                self.logger.info(
                    f"프로듀서 업데이트 완료. 총 프로듀서 수: {len(self.producers)}. "
                    f"추가: {len(urls_to_add)}, 제거: {len(urls_to_remove)}"
                )

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
        # ... (통계 로깅은 동일하게 유지)
        self.logger.info(f"실행 중인 프로듀서 수: {len(self.producers)}")


    def shutdown(self):
        """모든 컴포넌트를 정상적으로 종료합니다."""
        if self.shutdown_event.is_set():
            return
        self.logger.info("정상 종료를 시작합니다...")
        self.shutdown_event.set()

        # Redis 매니저 중지
        self.redis_manager.shutdown()

        # 모든 프로듀서 스레드 중지
        with self.producer_lock:
            self.logger.info(f"{len(self.producers)}개의 프로듀서를 중지합니다...")
            for url, producer in self.producers.items():
                if producer.is_alive():
                    producer.stop() # stop 메서드가 있다고 가정합니다.
                    producer.join(timeout=5)
            self.producers.clear()

        # 다른 컴포넌트 중지
        self.window_manager.shutdown()
        self.consumer_pool.shutdown()
        self.pending_buffer_manager.shutdown()

        self._log_stats()
        self.logger.info("종료 완료")


def parse_args():
    """커맨드 라인 인자를 파싱합니다."""
    parser = argparse.ArgumentParser(
        description="AEGIS AI Agent - 동적 2단계 트리거 분석 파이프라인"
    )
    # --urls 인자는 Redis에서 관리되므로 제거되었습니다.

    # config에서 가져온 선택적 인자들
    # ... (다른 모든 인자는 동일하게 유지)
    parser.add_argument(
        "--workers", type=int, default=4, help="컨슈머 워커 스레드 수"
    )
    # ... 필요에 따라 Config 필드와 일치하는 다른 인자 추가

    return parser.parse_args()


def main():
    """메인 진입점"""
    args = parse_args()

    # 설정 객체 생성, srt_urls는 RedisManager에 의해 채워집니다.
    config = Config()

    # 커맨드 라인 인자로 설정 오버라이드
    # 예:
    if args.workers:
        config.num_workers = args.workers
    # ... 다른 모든 인자에 대해 반복

    # 에이전트 생성 및 실행
    agent = AegisAgent(config)
    agent.run()


if __name__ == "__main__":
    main()
