"""
VLM 분석용 슬라이딩 윈도우 생성기
"""
import logging
import threading
import time
from collections import deque
from datetime import datetime
from typing import Dict, Deque


class WindowManager:
    """카메라별 슬라이딩 윈도우를 관리"""

    def __init__(self, config, queue_manager):
        """
        윈도우 관리자 초기화

        Args:
            config: 시스템 설정
            queue_manager: 중앙 큐 관리자 인스턴스
        """
        self.config = config
        self.queue_manager = queue_manager
        self.logger = logging.getLogger("aegis-agent.windowing")

        # 이중 버퍼: 저해상도(VLM용) + 고해상도(정밀 분석용)
        # {카메라_id: deque((저해상도_프레임, 고해상도_프레임, 타임스탬프))}
        self.buffers: Dict[str, Deque] = {}
        self.locks: Dict[str, threading.Lock] = {}

        # 윈도우 생성 추적
        self.last_window_time: Dict[str, float] = {}
        self.total_windows_generated = 0

        # 윈도우 생성을 위한 백그라운드 스레드
        self.shutdown_event = threading.Event()
        self.window_thread = threading.Thread(target=self._window_loop, daemon=True)
        self.window_thread.start()

    def add_frame(
        self,
        camera_id: str,
        low_res_frame: bytes,
        high_res_frame: bytes,
        timestamp: datetime,
    ):
        """
        카메라 버퍼에 프레임 추가 (저해상도 + 고해상도)

        Args:
            camera_id: 카메라 식별자
            low_res_frame: 저해상도 JPEG 프레임 바이트 (VLM용)
            high_res_frame: 고해상도 JPEG 프레임 바이트 (정밀 분석용)
            timestamp: 프레임 캡처 타임스탬프
        """
        # 새 카메라에 대한 버퍼 초기화
        if camera_id not in self.buffers:
            self.buffers[camera_id] = deque(maxlen=self.config.window_size + 1)
            self.locks[camera_id] = threading.Lock()
            self.last_window_time[camera_id] = time.time()
            self.logger.info(
                f"카메라 버퍼 초기화: {camera_id}"
            )

        # 버퍼에 프레임 추가 (이중 해상도 저장)
        with self.locks[camera_id]:
            self.buffers[camera_id].append((low_res_frame, high_res_frame, timestamp))

    def _window_loop(self):
        """슬라이딩 윈도우를 생성하는 백그라운드 스레드"""
        self.logger.info("윈도우 생성 스레드 시작됨")

        while not self.shutdown_event.is_set():
            try:
                current_time = time.time()

                # 각 카메라의 윈도우 생성 확인
                for camera_id in list(self.buffers.keys()):
                    # 새 윈도우를 생성할 시간인지 확인
                    time_since_last = current_time - self.last_window_time[camera_id]

                    if time_since_last >= self.config.window_slide:
                        self._generate_window(camera_id)
                        self.last_window_time[camera_id] = current_time

                # Busy-waiting을 방지하기 위한 짧은 대기
                time.sleep(0.1)

            except Exception as e:
                self.logger.error(
                    f"윈도우 생성 루프에서 오류 발생: {e}", exc_info=True
                )
                time.sleep(1)

        self.logger.info("윈도우 생성 스레드 중지됨")

    def _generate_window(self, camera_id: str):
        """
        카메라 버퍼에서 슬라이딩 윈도우 생성 (저해상도 + 고해상도)

        Args:
            camera_id: 카메라 식별자
        """
        with self.locks[camera_id]:
            buffer = self.buffers[camera_id]

            # 프레임이 충분한지 확인
            if len(buffer) < self.config.window_size:
                self.logger.debug(
                    f"프레임 부족: {camera_id}: "
                    f"{len(buffer)}/{self.config.window_size}"
                )
                return

            # 마지막 N개 프레임 추출
            frames = list(buffer)[-self.config.window_size :]

            # 작업 생성 (이중 해상도 분리)
            frame_timestamps = [ts for _, _, ts in frames]
            start_time_str = frame_timestamps[0].strftime("%H:%M:%S")
            end_time_str = frame_timestamps[-1].strftime("%H:%M:%S")

            task = {
                "camera_id": camera_id,
                "low_res_frames": [low_res for low_res, _, _ in frames],  # VLM용
                "high_res_frames": [high_res for _, high_res, _ in frames],  # 정밀 분석용
                "timestamp": datetime.now(),
                "window_start": start_time_str,
                "window_end": end_time_str,
                "frame_timestamps": frame_timestamps,
            }

            # 작업 큐에 추가
            success = self.queue_manager.put(task)

            if success:
                self.total_windows_generated += 1
                self.logger.debug(
                    f"윈도우 생성: {camera_id} "
                    f"({len(frames)} frames, window #{self.total_windows_generated})"
                )
            else:
                self.logger.warning(
                    f"윈도우 큐 추가 실패: {camera_id}"
                )

    def shutdown(self):
        """윈도우 관리자 종료"""
        self.logger.info("윈도우 관리자를 종료합니다...")
        self.shutdown_event.set()
        if self.window_thread.is_alive():
            self.window_thread.join(timeout=5)
        self.logger.info(
            f"윈도우 관리자가 중지되었습니다. 총 생성된 윈도우: {self.total_windows_generated}"
        )

    def get_stats(self) -> Dict:
        """윈도우 통계 가져오기"""
        return {
            "total_cameras": len(self.buffers),
            "total_windows_generated": self.total_windows_generated,
            "buffer_sizes": {
                camera_id: len(self.buffers[camera_id])
                for camera_id in self.buffers.keys()
            },
        }
