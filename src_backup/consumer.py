"""
VLM 분석 작업용 Consumer 스레드 풀 - 2단계 파이프라인
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
import time
from typing import Optional


class ConsumerPool:
    """
    큐에서 분석 작업을 소비하는 스레드 풀 (2단계 파이프라인)

    파이프라인:
    1단계: 저해상도 → VLM 트리거 분석 → 트리거 조건 판정
    2단계: 트리거 발동 시 → 고해상도 → 정밀 분석 API 전송
    """

    def __init__(
        self,
        config,
        queue_manager,
        vlm_client,
        pending_buffer_manager,
        trigger_analyzer,
        precision_client,
    ):
        """
        Consumer 풀 초기화 (2단계 파이프라인)

        인자:
            config: 시스템 설정
            queue_manager: 중앙 큐 관리자
            vlm_client: VLM API 클라이언트 (1단계 트리거)
            pending_buffer_manager: Pending 버퍼 관리자
            trigger_analyzer: 트리거 조건 분석기
            precision_client: 정밀 분석 클라이언트 (2단계)
        """
        self.config = config
        self.queue_manager = queue_manager
        self.vlm_client = vlm_client
        self.pending_buffer_manager = pending_buffer_manager
        self.trigger_analyzer = trigger_analyzer
        self.precision_client = precision_client
        self.logger = logging.getLogger("aegis-agent.consumer")

        self.num_workers = config.num_workers
        self.executor: Optional[ThreadPoolExecutor] = None
        self.shutdown_event = threading.Event()

        # 통계
        self.total_processed = 0  # VLM 분석 완료
        self.total_failed = 0  # VLM 분석 실패
        self.total_triggered = 0  # 트리거 발동 (정밀 분석 전송)
        self.total_skipped = 0  # 트리거 미발동 (정상)

    def start(self):
        """Consumer 스레드 풀 시작"""
        self.logger.info(
            f"Consumer 풀 시작 ({self.num_workers}개의 워커, 2단계 파이프라인)"
        )
        self.executor = ThreadPoolExecutor(
            max_workers=self.num_workers, thread_name_prefix="consumer"
        )

        # 워커 작업 제출
        for i in range(self.num_workers):
            self.executor.submit(self._worker_loop, i)

    def _worker_loop(self, worker_id: int):
        """
        메인 워커 루프 (2단계 파이프라인 처리)

        인자:
            worker_id: 워커 식별자
        """
        worker_logger = logging.getLogger(f"aegis-agent.consumer.worker-{worker_id}")
        worker_logger.info(f"워커 {worker_id} 시작됨")

        while not self.shutdown_event.is_set():
            try:
                # 큐에서 작업 가져오기 (종료 확인을 위한 타임아웃 포함)
                task = self.queue_manager.get(timeout=1.0)

                if task is None:
                    continue

                # 작업 정보 추출
                camera_id = task.get("camera_id", "unknown")
                low_res_frames = task.get("low_res_frames", [])  # VLM용
                high_res_frames = task.get("high_res_frames", [])  # 정밀 분석용

                worker_logger.debug(
                    f"작업 처리 시작 ({camera_id}, "
                    f"저해상도: {len(low_res_frames)} frames, "
                    f"고해상도: {len(high_res_frames)} frames)"
                )

                # 1단계: 고해상도 프레임을 pending buffer에 저장
                buffer_id = self.pending_buffer_manager.store(camera_id, high_res_frames)

                # 2단계: 저해상도 프레임으로 VLM 트리거 분석
                vlm_result = self.vlm_client.analyze_frames(
                    camera_id, low_res_frames, task
                )

                if vlm_result is None:
                    # VLM 분석 실패
                    self.total_failed += 1
                    worker_logger.warning(
                        f"VLM 분석 실패: {camera_id}"
                    )
                    # 버퍼 정리
                    self.pending_buffer_manager.drop(buffer_id)
                    continue

                self.total_processed += 1

                # 3단계: 트리거 조건 판정
                is_triggered = self.trigger_analyzer.should_trigger(vlm_result)

                if is_triggered:
                    # 4단계: 트리거 발동 - 정밀 분석 API로 전송
                    self.total_triggered += 1

                    # pending buffer에서 고해상도 프레임 가져오기
                    precision_frames = self.pending_buffer_manager.retrieve(buffer_id)

                    if precision_frames:
                        worker_logger.info(
                            f"[트리거] 정밀 분석으로 전송 - "
                            f"카메라: {camera_id}, "
                            f"프레임: {len(precision_frames)}"
                        )

                        # VLM 메타데이터 파싱
                        vlm_metadata = self.trigger_analyzer.parse_response(vlm_result)

                        # 정밀 분석 API 호출
                        precision_result = self.precision_client.send_for_analysis(
                            camera_id, precision_frames, vlm_metadata, task
                        )

                        if precision_result:
                            worker_logger.info(
                                f"[성공] 정밀 분석 완료 - "
                                f"카메라: {camera_id}"
                            )
                        else:
                            worker_logger.error(
                                f"[오류] 정밀 분석 실패 - "
                                f"카메라: {camera_id}"
                            )
                    else:
                        worker_logger.error(
                            f"[경고] 버퍼를 찾을 수 없음: {buffer_id} "
                            f"(타임아웃 또는 이미 사용됨)"
                        )
                else:
                    # 트리거 미발동 - 버퍼만 삭제
                    self.total_skipped += 1
                    self.pending_buffer_manager.drop(buffer_id)

                    worker_logger.debug(
                        f"[정상] 트리거 미발동 - {camera_id}"
                    )

                # 주기적 통계 로그
                if (self.total_processed + self.total_failed) % 10 == 0:
                    self.logger.info(
                        f"Consumer 통계 - "
                        f"처리: {self.total_processed}, "
                        f"실패: {self.total_failed}, "
                        f"트리거: {self.total_triggered}, "
                        f"정상: {self.total_skipped}, "
                        f"큐: {self.queue_manager.size()}"
                    )

            except Exception as e:
                worker_logger.error(
                    f"워커 루프에서 예상치 못한 오류 발생: {e}",
                    exc_info=True,
                )
                time.sleep(1)

        worker_logger.info(f"워커 {worker_id} 중지됨")

    def shutdown(self):
        """Consumer 풀 종료"""
        self.logger.info("Consumer 풀을 종료하는 중...")
        self.shutdown_event.set()

        if self.executor is not None:
            self.executor.shutdown(wait=True, cancel_futures=False)

        self.logger.info(
            f"Consumer 풀 중지됨 - "
            f"처리: {self.total_processed}, "
            f"실패: {self.total_failed}, "
            f"트리거: {self.total_triggered}, "
            f"정상: {self.total_skipped}"
        )

    def get_stats(self):
        """Consumer 통계 조회"""
        total = self.total_processed + self.total_failed
        trigger_rate = (
            100 * self.total_triggered / self.total_processed
            if self.total_processed > 0
            else 0
        )

        return {
            "num_workers": self.num_workers,
            "total_processed": self.total_processed,
            "total_failed": self.total_failed,
            "total_triggered": self.total_triggered,
            "total_skipped": self.total_skipped,
            "success_rate": 100 * self.total_processed / total if total > 0 else 0,
            "trigger_rate": trigger_rate,
        }
