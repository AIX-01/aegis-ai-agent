"""
RTSP 스트림 프레임 추출 Producer 스레드
"""
import logging
import os
import threading
import time
from typing import Optional
import cv2
import numpy as np
from datetime import datetime

from .config import Config
from .utils import exponential_backoff


class FrameProducer(threading.Thread):
    """RTSP 스트림에서 프레임을 추출하는 Producer 스레드"""

    def __init__(
        self,
        camera_name: str,
        camera_alias: str,
        config: Config,
        frame_callback,
        shutdown_event: threading.Event,
    ):
        """
        프레임 프로듀서 초기화

        Args:
            camera_name: 카메라 이름 (URL 생성에 사용)
            camera_alias: 카메라 별칭 (로깅 및 식별에 사용)
            config: 시스템 설정
            frame_callback: 콜백 함수(camera_id, frame_data, timestamp)
            shutdown_event: 전체 에이전트의 종료를 알리는 이벤트
        """
        super().__init__(daemon=True)
        self.camera_id = camera_alias  # 로깅 및 표시에 사용할 ID
        self.camera_name = camera_name
        self.rtsp_url = f"rtsp://{config.rtsp_host}:{config.rtsp_port}/{camera_name}"
        self.config = config
        self.frame_callback = frame_callback
        self.global_shutdown_event = shutdown_event
        self.local_shutdown_event = threading.Event() # 이 특정 프로듀서만 중지하기 위함
        self.logger = logging.getLogger(f"aegis-agent.producer.{self.camera_id}")

        self.capture: Optional[cv2.VideoCapture] = None
        self.reconnect_attempt = 0
        self.total_frames_captured = 0

        self.is_local_file = self._is_local_file(self.rtsp_url)
        if self.is_local_file:
            self.logger.info(f"로컬 파일 모드 활성화 (반복 재생)")

    def stop(self):
        """이 특정 프로듀서 스레드에 중지 신호를 보냅니다."""
        self.logger.info("중지 신호 수신.")
        self.local_shutdown_event.set()

    def _should_shutdown(self) -> bool:
        """전역 또는 지역 종료 이벤트가 설정되었는지 확인합니다."""
        return self.global_shutdown_event.is_set() or self.local_shutdown_event.is_set()

    def _is_local_file(self, url: str) -> bool:
        """
        URL이 로컬 파일인지 네트워크 스트림인지 확인합니다.
        - 네트워크 스트림(RTSP, HTTP 등)은 재생 종료 시 재연결을 시도합니다.
        - 로컬 파일은 재생 종료 시 처음부터 다시 반복 재생합니다. (테스트 및 데모용)
        """
        if url.startswith(("rtsp://", "http://", "https://")):
            return False
        return os.path.exists(url)

    def _connect(self) -> bool:
        """RTSP 스트림에 연결합니다."""
        try:
            self.logger.info(f"스트림에 연결 중: {self.rtsp_url}")
            if self.capture is not None:
                self.capture.release()

            # [수정] RTSP 스트림에 TCP 프로토콜을 사용하도록 환경 변수 설정
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
            self.capture = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)

            if not self.capture.isOpened():
                self.logger.error("스트림을 열지 못했습니다.")
                return False

            ret, frame = self.capture.read()
            if not ret or frame is None:
                self.logger.error("초기 프레임을 읽지 못했습니다.")
                self.capture.release()
                self.capture = None
                return False

            self.logger.info("스트림에 성공적으로 연결되었습니다.")
            self.reconnect_attempt = 0
            return True
        except Exception as e:
            self.logger.error(f"스트림 연결 중 오류 발생: {e}", exc_info=True)
            return False

    def _reconnect(self):
        """종료 신호를 확인하며 지수 백오프로 재연결합니다."""
        delay = exponential_backoff(
            self.reconnect_attempt,
            self.config.reconnect_delay,
            self.config.max_reconnect_delay,
        )
        self.logger.warning(f"{delay:.1f}초 후 재연결합니다 (시도 {self.reconnect_attempt + 1})...")
        
        wait_start = time.time()
        while time.time() - wait_start < delay:
            if self._should_shutdown():
                return
            time.sleep(0.1)

        self.reconnect_attempt += 1
        if not self._should_shutdown():
            if self._connect():
                self.logger.info("재연결 성공.")
            else:
                self.logger.error("재연결 실패, 다시 시도합니다...")

    def _preprocess_frame(self, frame: np.ndarray) -> Optional[bytes]:
        """프레임 전처리: 저해상도(VLM용) 버전을 생성합니다."""
        try:
            low_res = cv2.resize(frame, (self.config.frame_width, self.config.frame_height), interpolation=cv2.INTER_LINEAR)
            _, encoded_low = cv2.imencode(".jpg", low_res, [int(cv2.IMWRITE_JPEG_QUALITY), self.config.jpeg_quality])
            return encoded_low.tobytes()
        except Exception as e:
            self.logger.error(f"프레임 전처리 중 오류 발생: {e}", exc_info=True)
            return None

    def run(self):
        """메인 프로듀서 루프."""
        self.logger.info(f"'{self.camera_id}'의 프로듀서를 시작합니다")

        while not self._should_shutdown():
            if self._connect():
                break
            self._reconnect()

        last_capture_time = time.time()
        while not self._should_shutdown():
            try:
                if not self.capture or not self.capture.isOpened():
                    self.logger.warning("캡처가 열려있지 않습니다. 재연결을 시도합니다.")
                    self._reconnect()
                    continue

                current_time = time.time()
                if current_time - last_capture_time < (1.0 / self.config.fps):
                    time.sleep(0.01)
                    continue

                ret, frame = self.capture.read()
                if not ret or frame is None:
                    if self.is_local_file:
                        self.logger.info("파일 끝에 도달하여, 반복 재생합니다.")
                        self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    else:
                        self.logger.warning("프레임을 읽지 못했습니다, 재연결합니다...")
                        self._reconnect()
                    last_capture_time = time.time()
                    continue

                low_res_frame = self._preprocess_frame(frame)
                if low_res_frame is None:
                    continue

                self.frame_callback(self.camera_id, low_res_frame, datetime.now())
                self.total_frames_captured += 1
                last_capture_time = current_time

            except Exception as e:
                self.logger.error(f"캡처 루프에서 예상치 못한 오류 발생: {e}", exc_info=True)
                if not self.is_local_file:
                    self._reconnect()
                else:
                    time.sleep(1)

        if self.capture:
            self.capture.release()
        self.logger.info(f"'{self.camera_id}'의 프로듀서가 중지되었습니다. 총 프레임: {self.total_frames_captured}")
