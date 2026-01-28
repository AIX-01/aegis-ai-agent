"""
VLM 분석 작업용 Consumer 스레드 풀 - 간소화된 파이프라인
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
import time
from typing import Optional
from .config import TRIGGER_CATEGORIES


class ConsumerPool:
    """
    큐에서 분석 작업을 소비하는 스레드 풀 (간소화된 파이프라인)

    파이프라인:
    1. 저해상도 → VLM 분석
    2. VLM 결과가 '이상'이면 → 고해상도 → 정밀 분석 API 전송
    """

    def __init__(
        self,
        config,
        queue_manager,
        vlm_client,
        precision_client,
    ):
        """
        컨슈머 풀 초기화 (간소화된 파이프라인)

        Args:
            config: 시스템 설정
            queue_manager: 중앙 큐 관리자
            vlm_client: VLM API 클라이언트 (1단계)
            precision_client: 정밀 분석 클라이언트 (2단계)
        """
        self.config = config
        self.queue_manager = queue_manager
        self.vlm_client = vlm_client
        self.precision_client = precision_client
        self.logger = logging.getLogger("aegis-agent.consumer")

        self.num_workers = config.num_workers
        self.executor: Optional[ThreadPoolExecutor] = None
        self.shutdown_event = threading.Event()

        # 통계
        self.total_processed = 0
        self.total_failed = 0
        self.total_triggered = 0
        self.total_skipped = 0

    def start(self):
        """컨슈머 스레드 풀 시작"""
        self.logger.info(
            f"{self.num_workers}개의 워커로 컨슈머 풀을 시작합니다 (간소화된 파이프라인)"
        )
        self.executor = ThreadPoolExecutor(
            max_workers=self.num_workers, thread_name_prefix="consumer"
        )
        for i in range(self.num_workers):
            self.executor.submit(self._worker_loop, i)

    def _worker_loop(self, worker_id: int):
        """
        메인 워커 루프 (간소화된 파이프라인 처리)
        """
        worker_logger = logging.getLogger(f"aegis-agent.consumer.worker-{worker_id}")
        worker_logger.info(f"워커 {worker_id} 시작됨")

        while not self.shutdown_event.is_set():
            try:
                task = self.queue_manager.get(timeout=1.0)
                if task is None:
                    continue

                camera_id = task.get("camera_id", "unknown")
                low_res_frames = task.get("low_res_frames", [])
                high_res_frames = task.get("high_res_frames", [])

                worker_logger.debug(f"{camera_id}의 작업을 처리합니다")

                # === 1단계: 저해상도 프레임으로 VLM 분석 ===
                vlm_result = self.vlm_client.analyze_frames(
                    camera_id, low_res_frames, task
                )

                if vlm_result is None:
                    self.total_failed += 1
                    worker_logger.warning(f"{camera_id}의 VLM 분석 실패")
                    continue

                self.total_processed += 1

                # === 2단계: 트리거 조건 확인 및 정밀 분석 전송 ===
                primary_category = vlm_result.get("primary_category", "").lower()
                is_triggered = any(cat in primary_category for cat in TRIGGER_CATEGORIES)

                if is_triggered:
                    self.total_triggered += 1
                    worker_logger.info(
                        f"[트리거] {camera_id}의 조건 충족. 정밀 분석으로 전송합니다."
                    )

                    if high_res_frames:
                        precision_result = self.precision_client.send_for_analysis(
                            camera_id, high_res_frames, vlm_result, task
                        )
                        if precision_result:
                            worker_logger.info(f"[성공] {camera_id}의 정밀 분석 완료")
                        else:
                            worker_logger.error(f"[실패] {camera_id}의 정밀 분석 실패")
                    else:
                        worker_logger.warning(f"{camera_id}에 전송할 고해상도 프레임이 없습니다")
                else:
                    self.total_skipped += 1
                    worker_logger.debug(f"[정상] {camera_id} - 트리거되지 않음")

                if (self.total_processed + self.total_failed) % 10 == 0:
                    self._log_stats()

            except Exception as e:
                worker_logger.error(f"워커 루프에서 예상치 못한 오류 발생: {e}", exc_info=True)
                time.sleep(1)

        worker_logger.info(f"워커 {worker_id} 중지됨")

    def shutdown(self):
        """컨슈머 풀 종료"""
        self.logger.info("컨슈머 풀을 종료합니다...")
        self.shutdown_event.set()
        if self.executor:
            self.executor.shutdown(wait=True)
        self.logger.info("컨슈머 풀이 중지되었습니다.")
        self._log_stats()

    def _log_stats(self):
        self.logger.info(
            f"컨슈머 통계 - 처리: {self.total_processed}, "
            f"실패: {self.total_failed}, 트리거: {self.total_triggered}, "
            f"건너뜀: {self.total_skipped}, 큐: {self.queue_manager.size()}"
        )

    def get_stats(self):
        """컨슈머 통계 조회"""
        total = self.total_processed + self.total_failed
        trigger_rate = (
            (100 * self.total_triggered / self.total_processed)
            if self.total_processed > 0
            else 0
        )
        return {
            "num_workers": self.num_workers,
            "total_processed": self.total_processed,
            "total_failed": self.total_failed,
            "total_triggered": self.total_triggered,
            "total_skipped": self.total_skipped,
            "success_rate": (100 * self.total_processed / total) if total > 0 else 0,
            "trigger_rate": trigger_rate,
        }
