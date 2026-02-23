"""
RTSP 스트림 패킷 수신 및 버퍼링 Producer 스레드 (PyAV 기반)
"""
import logging
import os
import threading
import time
from typing import Optional, Dict
import av
import cv2
import numpy as np
from datetime import datetime

from ..config import Config
from ..utils import exponential_backoff
from .packet_buffer import PacketBuffer


class FrameProducer(threading.Thread):
    """
    RTSP 스트림을 PyAV로 수신하여 두 가지 경로로 처리하는 하이브리드 Producer입니다.

    [경로 A: 실시간 분석 (Analysis Path)]
    - 패킷을 비디오 프레임으로 디코딩합니다.
    - 설정된 FPS에 맞춰 분석용 저해상도 JPG 이미지를 생성합니다.
    - Consumer 큐(WindowManager)로 전달되어 VLM 분석의 입력값이 됩니다.

    [경로 B: 영상 저장 (Storage Path)]
    - 수신된 '원본 패킷'을 디코딩 없이 그대로 PacketBuffer에 저장합니다.
    - VLM에서 이상 행동이 감지되었을 때, 이 버퍼에서 패킷을 꺼내 MP4 클립을 만듭니다.
    - 재인코딩이 없으므로 CPU 부하가 매우 적고 원본 화질을 유지합니다.
    """

    def __init__(
        self,
        camera_info: Dict,
        config: Config,
        frame_callback,
        shutdown_event: threading.Event,
        source_streams_dict: Optional[Dict] = None, # 스트림 정보 공유용
        efs_writer=None,  # EFS 패킷 덤프 (ingest 모드용)
    ):
        """
        프레임 프로듀서 초기화

        Args:
            camera_info: 카메라 정보
            config: 시스템 설정
            frame_callback: 분석용 프레임 콜백 (camera_info, frame_data, timestamp)
            shutdown_event: 종료 시그널
            source_streams_dict: 스트림 정보를 등록할 딕셔너리
            efs_writer: EFSPacketWriter 인스턴스 (ingest 모드에서만 사용)
        """
        super().__init__(daemon=True)
        self.camera_info = camera_info
        self.camera_id = camera_info.get('id', 'unknown')
        self.camera_name = camera_info.get('name', 'unknown')
        self.rtsp_url = f"rtsp://{config.rtsp_host}:{config.rtsp_port}/{self.camera_name}"
        self.config = config
        self.frame_callback = frame_callback
        self.global_shutdown_event = shutdown_event
        self.local_shutdown_event = threading.Event()
        self.logger = logging.getLogger(f"aegis-agent.producer.{self.camera_id}")

        self.source_streams_dict = source_streams_dict
        self.efs_writer = efs_writer

        # PyAV 컨테이너
        self.container = None

        # 패킷 버퍼 초기화 (30초 저장)
        self.packet_buffer = PacketBuffer(buffer_duration=config.video_buffer_seconds)

        self.reconnect_attempt = 0
        self.total_packets_received = 0
        self.total_frames_decoded = 0

        # EFS 덤프 주기 (5초마다)
        self._last_efs_dump_time = 0
        self._efs_dump_interval = 5.0

        self.is_local_file = self._is_local_file(self.rtsp_url)
        if self.is_local_file:
            self.logger.info(f"로컬 파일 모드 활성화 (반복 재생)")

    def stop(self):
        """중지 신호"""
        self.logger.info("중지 신호 수신.")
        self.local_shutdown_event.set()

    def _should_shutdown(self) -> bool:
        return self.global_shutdown_event.is_set() or self.local_shutdown_event.is_set()

    def _is_local_file(self, url: str) -> bool:
        if url.startswith(("rtsp://", "http://", "https://")):
            return False
        return os.path.exists(url)

    def _open_stream(self):
        """PyAV를 사용하여 스트림 열기"""
        try:
            options = {}
            if self.rtsp_url.startswith("rtsp"):
                # TCP 강제 사용 (안정성)
                options["rtsp_transport"] = "tcp"
                # 지연 시간 최소화 옵션
                options["stimeout"] = "5000000" # 5초 타임아웃
            
            self.logger.info(f"스트림 연결 중: {self.rtsp_url}")
            if self.container:
                self.container.close()
                
            self.container = av.open(self.rtsp_url, options=options)
            self.reconnect_attempt = 0
            
            # 스트림 메타데이터 저장 (Muxing 시 사용)
            # stream 객체 자체는 컨테이너 재연결 시 무효화되므로 메타데이터만 복사
            if self.source_streams_dict is not None and self.container.streams.video:
                video_stream = self.container.streams.video[0]
                self.source_streams_dict[self.camera_id] = {
                    'codec_name': video_stream.codec_context.name,
                    'width': video_stream.width,
                    'height': video_stream.height,
                    'pix_fmt': video_stream.pix_fmt,
                    'time_base': video_stream.time_base,
                    'average_rate': video_stream.average_rate,
                    'extradata': bytes(video_stream.codec_context.extradata) if video_stream.codec_context.extradata else None,
                }

            self.logger.info("스트림 연결 성공.")
            return True
            
        except Exception as e:
            self.logger.error(f"스트림 연결 실패: {e}")
            return False

    def _reconnect(self):
        """재연결 로직"""
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
            if self._open_stream():
                self.logger.info("재연결 성공.")
            else:
                self.logger.error("재연결 실패.")

    def _preprocess_frame(self, frame_array: np.ndarray) -> Optional[bytes]:
        """이미지 리사이징 및 인코딩 (VLM 분석용)"""
        try:
            # PyAV 프레임은 RGB일 수 있으므로 BGR로 변환 필요할 수 있음
            # frame.to_ndarray(format='bgr24')를 쓰면 BGR로 나옴.
            low_res = cv2.resize(frame_array, (self.config.frame_width, self.config.frame_height), interpolation=cv2.INTER_LINEAR)
            _, encoded_low = cv2.imencode(".jpg", low_res, [int(cv2.IMWRITE_JPEG_QUALITY), self.config.jpeg_quality])
            return encoded_low.tobytes()
        except Exception as e:
            self.logger.error(f"프레임 전처리 오류: {e}")
            return None

    def run(self):
        """메인 루프 (패킷 수신 -> 버퍼 저장 -> 디코딩 -> 분석)"""
        self.logger.info(f"'{self.camera_name}' Producer 시작 (PyAV)")

        while not self._should_shutdown():
            if self._open_stream():
                break
            self._reconnect()

        last_analysis_time = 0
        analysis_interval = 1.0 / self.config.fps

        while not self._should_shutdown():
            try:
                if not self.container:
                    self._reconnect()
                    continue

                # demux()는 패킷을 순차적으로 생성
                # 에러 발생 시 av.AVError 등을 던질 수 있음
                stream = self.container.streams.video[0] # 첫 번째 비디오 스트림만 사용
                
                for packet in self.container.demux(stream):
                    if self._should_shutdown():
                        break
                    
                    if packet.dts is None:
                        continue

                    # ==========================================
                    # 경로 B: 패킷 버퍼링 (저장용)
                    # ==========================================
                    # 패킷 데이터를 복사하여 저장 (원본 패킷은 demux 루프에서 재사용됨)
                    packet_copy = av.Packet(bytes(packet))
                    packet_copy.pts = packet.pts
                    packet_copy.dts = packet.dts
                    packet_copy.time_base = packet.time_base
                    packet_copy.is_keyframe = packet.is_keyframe
                    self.packet_buffer.add_packet(packet_copy)
                    self.total_packets_received += 1

                    # ==========================================
                    # 경로 B-2: EFS 덤프 (ingest 모드만)
                    # ==========================================
                    if self.efs_writer and self.config.agent_mode != "all":
                        now_efs = time.time()
                        if now_efs - self._last_efs_dump_time >= self._efs_dump_interval:
                            source_info = self.source_streams_dict.get(self.camera_id) if self.source_streams_dict else None
                            self.efs_writer.dump_buffer(self.camera_id, self.packet_buffer, source_info)
                            self._last_efs_dump_time = now_efs

                    # ==========================================
                    # 경로 A: 디코딩 및 분석 (분석용)
                    # ==========================================
                    current_time = time.time()
                    
                    # FPS 제어: 분석 주기가 되었을 때만 디코딩 시도
                    # (패킷이 I-Frame이 아니어도 디코딩은 해야 순서가 맞지만,
                    #  PyAV는 필요한 만큼 내부적으로 처리하거나, decode()가 프레임을 리스트로 반환함)
                    
                    # 성능 최적화: 모든 패킷을 decode()하면 CPU 부하가 큼.
                    # 하지만 P-Frame을 디코딩하려면 앞선 I-Frame부터 순차적으로 해야 함.
                    # 따라서 일반적으로는 '모든 패킷을 디코딩'하되, '결과 프레임 처리'만 스킵하는 게 안전함.
                    # 또는, 코덱 컨텍스트가 유지되므로 decode() 호출은 필수.
                    
                    try:
                        frames = packet.decode() # 리스트 반환 (0개 이상)
                    except Exception as e:
                        self.logger.warning(f"패킷 디코딩 실패: {e}")
                        continue

                    for frame in frames:
                        # 분석 주기 체크
                        if current_time - last_analysis_time >= analysis_interval:
                            # ndarray 변환 (BGR 포맷)
                            img_array = frame.to_ndarray(format='bgr24')
                            
                            # 전처리 (리사이즈, JPG 인코딩)
                            jpg_bytes = self._preprocess_frame(img_array)
                            
                            if jpg_bytes:
                                # 분석 파이프라인으로 전달 (Consumer)
                                self.frame_callback(self.camera_info, jpg_bytes, datetime.now())
                                self.total_frames_decoded += 1
                                last_analysis_time = current_time
                
                # demux 루프가 끝나면 (스트림 종료/끊김)
                self.logger.warning("스트림이 종료되었습니다. 재연결 시도...")
                if self.is_local_file:
                     # 파일 반복 재생 로직은 PyAV에서 seek로 구현 복잡 -> 간단히 재오픈
                    pass 
                
                self._reconnect()

            except (av.AVError, Exception) as e:
                self.logger.error(f"Producer 루프 에러: {e}")
                self._reconnect()

        if self.container:
            self.container.close()
        self.logger.info("Producer 종료됨.")