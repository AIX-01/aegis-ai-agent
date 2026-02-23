"""
VLM 분석용 슬라이딩 윈도우 생성기
"""
import logging
import threading
import time
from collections import deque
from datetime import datetime
from typing import Dict, Deque, List, Tuple


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

        # {카메라_id: deque((프레임, 타임스탬프, 카메라정보))}
        self.buffers: Dict[str, Deque] = {}
        self.locks: Dict[str, threading.Lock] = {}

        # 윈도우 생성 및 타임아웃 추적
        self.last_window_time: Dict[str, float] = {}
        self.last_frame_time: Dict[str, float] = {}  # 마지막 프레임 도착 시간
        self.total_windows_generated = 0

        # 윈도우 생성을 위한 백그라운드 스레드
        self.shutdown_event = threading.Event()
        self.window_thread = threading.Thread(target=self._window_loop, daemon=True)
        self.window_thread.start()

    def add_frame(
        self,
        camera_info: Dict,
        frame: bytes,
        timestamp: datetime,
    ):
        """
        카메라 버퍼에 프레임 추가

        Args:
            camera_info: 카메라 정보 딕셔너리
            frame: JPEG 프레임 바이트
            timestamp: 프레임 캡처 타임스탬프
        """
        camera_id = camera_info.get('id', 'unknown')
        current_time = time.time()
        if camera_id not in self.buffers:
            # 새 카메라에 대한 버퍼 및 시간 추적 초기화
            self.buffers[camera_id] = deque()
            self.locks[camera_id] = threading.Lock()
            self.last_window_time[camera_id] = current_time
            self.logger.info(f"카메라 버퍼 초기화: {camera_id}")

        with self.locks[camera_id]:
            self.buffers[camera_id].append((frame, timestamp, camera_info))
            self.last_frame_time[camera_id] = current_time # 마지막 프레임 도착 시간 기록

    def _window_loop(self):
        """슬라이딩 윈도우 및 타임아웃을 처리하는 백그라운드 스레드"""
        self.logger.info("윈도우 생성 스레드 시작됨")

        while not self.shutdown_event.is_set():
            try:
                current_time = time.time()
                camera_ids = list(self.buffers.keys())

                for camera_id in camera_ids:
                    with self.locks[camera_id]:
                        # 1. 일반적인 슬라이딩 윈도우 생성 확인
                        time_since_last_window = current_time - self.last_window_time.get(camera_id, current_time)
                        if time_since_last_window >= self.config.window_slide:
                            if self._generate_window(camera_id):
                                self.last_window_time[camera_id] = current_time

                        # 2. 타임아웃으로 인한 강제 처리(flush) 확인
                        time_since_last_frame = current_time - self.last_frame_time.get(camera_id, current_time)
                        if time_since_last_frame >= self.config.flush_timeout:
                            self._flush_buffer(camera_id)
                            # 강제 처리 후에는 마지막 프레임 시간을 현재로 리셋하여 반복 처리를 방지
                            self.last_frame_time[camera_id] = current_time

                time.sleep(0.1)

            except Exception as e:
                self.logger.error(f"윈도우 생성 루프에서 오류 발생: {e}", exc_info=True)
                time.sleep(1)

        self.logger.info("윈도우 생성 스레드 중지됨")

    def _generate_window(self, camera_id: str) -> bool:
        """
        카메라 버퍼에서 슬라이딩 윈도우를 생성 (버퍼를 비우지 않음).
        성공 시 True, 실패 시 False 반환.
        """
        buffer = self.buffers[camera_id]
        if len(buffer) < self.config.window_size:
            self.logger.debug(f"프레임 부족 (일반): {camera_id}: {len(buffer)}/{self.config.window_size}")
            return False

        # 슬라이딩 윈도우이므로 버퍼의 마지막 N개 프레임만 사용
        window_frames = list(buffer)[-self.config.window_size:]
        self._create_and_queue_task(camera_id, window_frames, "일반")
        
        # 슬라이딩 윈도우를 위해 오래된 프레임 제거
        while len(buffer) > self.config.window_size:
            buffer.popleft()
            
        return True

    def _flush_buffer(self, camera_id: str):
        """
        타임아웃 시 버퍼에 남은 프레임으로 윈도우를 강제 생성 (버퍼를 비움).
        """
        buffer = self.buffers[camera_id]
        if len(buffer) < self.config.min_flush_size:
            if len(buffer) > 0:
                self.logger.warning(f"타임아웃 강제 처리 건너뜀 (프레임 부족): {camera_id}: {len(buffer)}/{self.config.min_flush_size}. 버퍼를 비웁니다.")
                buffer.clear()
            return

        self.logger.warning(f"타임아웃 발생! {camera_id}의 버퍼를 강제 처리합니다. ({len(buffer)} 프레임)")
        flush_frames = list(buffer)
        self._create_and_queue_task(camera_id, flush_frames, "강제 처리")
        buffer.clear() # 강제 처리 후에는 버퍼를 완전히 비움

    def _create_and_queue_task(self, camera_id: str, frames: List[Tuple[bytes, datetime, Dict]], reason: str):
        """주어진 프레임들로 작업을 생성하고 큐에 넣습니다."""
        if not frames:
            return

        frame_timestamps = [ts for _, ts, _ in frames]
        start_time_str = frame_timestamps[0].strftime("%H:%M:%S")
        end_time_str = frame_timestamps[-1].strftime("%H:%M:%S")
        
        # 첫 번째 프레임의 카메라 정보를 사용
        camera_info = frames[0][2]

        task = {
            "camera_info": camera_info,
            "low_res_frames": [frame for frame, _, _ in frames],
            "timestamp": datetime.now(),
            "window_start": start_time_str,
            "window_end": end_time_str,
            "frame_timestamps": frame_timestamps,
        }

        success = self.queue_manager.put(task)
        if success:
            self.total_windows_generated += 1
            self.logger.info(f"윈도우 생성 ({reason}): {camera_id} ({len(frames)} frames, window #{self.total_windows_generated})")
        else:
            self.logger.warning(f"윈도우 큐 추가 실패 ({reason}): {camera_id}")

    def shutdown(self):
        """윈도우 관리자 종료"""
        self.logger.info("윈도우 관리자를 종료합니다...")
        self.shutdown_event.set()
        if self.window_thread.is_alive():
            self.window_thread.join(timeout=5)
        self.logger.info(f"윈도우 관리자가 중지되었습니다. 총 생성된 윈도우: {self.total_windows_generated}")

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
