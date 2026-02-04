"""
VLM 분석 작업용 Consumer 스레드 풀 - LangGraph 기반 파이프라인
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
import time
from typing import Optional

# LangGraph 빌더 import
from ..graph.analysis_graph import build_graph
from ..clients.vlm_client import VLMClient
from ..clients.backend_client import BackendClient
from ..clients.storage_client import StorageClient
from ..core.muxer import mux_packets_to_mp4


class ConsumerPool:
    """
    큐에서 분석 작업을 소비하는 스레드 풀 (LangGraph 기반)
    """

    def __init__(
        self,
        config,
        queue_manager,
        packet_buffers=None, # 카메라별 PacketBuffer 딕셔너리 주입
        source_streams=None  # 카메라별 원본 스트림 정보 주입
    ):
        """
        컨슈머 풀 초기화

        Args:
            config: 시스템 설정
            queue_manager: 중앙 큐 관리자
            packet_buffers: {camera_id: PacketBuffer} 딕셔너리
            source_streams: {camera_id: av.VideoStream} 딕셔너리
        """
        self.config = config
        self.queue_manager = queue_manager
        # None일 때만 새 딕셔너리 생성 (빈 딕셔너리 {} 참조 유지)
        self.packet_buffers = packet_buffers if packet_buffers is not None else {}
        self.source_streams = source_streams if source_streams is not None else {}
        self.logger = logging.getLogger("aegis-agent.consumer")


        # 클라이언트 초기화
        self.vlm_client = VLMClient(config)
        self.backend_client = BackendClient(config)
        self.storage_client = StorageClient(config)

        # LangGraph 워크플로우 빌드
        self.logger.info("LangGraph 워크플로우를 빌드합니다...")
        self.graph = build_graph(config)

        self.num_workers = config.num_workers
        self.executor: Optional[ThreadPoolExecutor] = None
        self.shutdown_event = threading.Event()

        # 통계
        self.total_processed = 0
        self.total_failed = 0
        self.total_abnormal = 0
        self.total_normal = 0
        
        # VLM 분석 시간 통계
        self.total_vlm_time = 0.0
        self.vlm_count = 0
        self.stats_lock = threading.Lock()

    def start(self):
        """컨슈머 스레드 풀 시작"""
        self.logger.info(
            f"{self.num_workers}개의 워커로 컨슈머 풀을 시작합니다 (LangGraph 기반)"
        )
        self.executor = ThreadPoolExecutor(
            max_workers=self.num_workers, thread_name_prefix="consumer"
        )
        for i in range(self.num_workers):
            self.executor.submit(self._worker_loop, i)

    def _worker_loop(self, worker_id: int):
        """
        개별 워커 스레드의 메인 루프 (VLM 선행 분석 후 LangGraph 실행)

        각 워커는 다음과 같은 생명주기를 가집니다:
        1. 인출: 큐에서 작업(Task)을 하나 가져옵니다.
        2. VLM 분석: 가벼운 VLM 분석을 먼저 수행하여 위험도를 판별합니다.
        3. 조건부 실행:
           - NORMAL: 분석 종료 및 통계 갱신.
           - ABNORMAL/SUSPICIOUS: 
             1) 백엔드에 즉시 결과 전송 (Event ID 생성)
             2) LangGraph를 호출하여 정밀 분석 및 사후 처리 수행.

        Args:
            worker_id (int): 워커 식별자 (디버깅 및 로깅용)
        """
        worker_logger = logging.getLogger(f"aegis-agent.consumer.worker-{worker_id}")
        worker_logger.info(f"워커 {worker_id} 시작됨")

        while not self.shutdown_event.is_set():
            try:
                task = self.queue_manager.get(timeout=1.0)
                if task is None:
                    continue

                camera_info = task.get("camera_info", {})
                camera_id = camera_info.get("id", "unknown")
                frames = task.get("low_res_frames", [])
                frame_timestamps = task.get("frame_timestamps", [])
                
                # 이벤트 발생 시각을 윈도우의 첫 프레임 시간으로 설정
                occurred_at = frame_timestamps[0] if frame_timestamps else task.get("timestamp")

                worker_logger.debug(f"{camera_id}의 VLM 1차 분석을 수행합니다.")

                # 1. VLM 1차 분석 수행 (그래프 진입 전)
                risk_level = "NORMAL"
                vlm_result = {}
                
                try:
                    task_metadata = {"timestamp": occurred_at}
                    
                    # VLM 분석 시간 측정 시작
                    vlm_start_time = time.time()
                    vlm_result = self.vlm_client.analyze_frames(camera_id, frames, task_metadata)
                    # VLM 분석 시간 측정 종료 및 로깅
                    vlm_duration = time.time() - vlm_start_time
                    worker_logger.info(f"[{camera_id}] VLM 분석 소요 시간: {vlm_duration:.3f}초")
                    
                    # 통계 업데이트 (스레드 안전하게)
                    with self.stats_lock:
                        self.total_vlm_time += vlm_duration
                        self.vlm_count += 1
                    
                    if vlm_result and "risk_level" in vlm_result:
                        risk_level = vlm_result["risk_level"].upper()
                    else:
                        worker_logger.warning(f"[{camera_id}] VLM 분석 결과가 유효하지 않습니다. NORMAL로 처리합니다.")
                except Exception as e:
                    worker_logger.error(f"[{camera_id}] VLM 분석 중 오류: {e}")
                    # 분석 실패 시 안전을 위해 NORMAL 처리 (또는 에러 통계 증가)
                    self.total_failed += 1
                    continue

                # 2. 결과에 따른 분기 처리
                if risk_level == "NORMAL":
                    worker_logger.debug(f"[완료] {camera_id} 분석 완료: NORMAL (LangGraph 건너뜀)")
                    self.total_processed += 1
                    self.total_normal += 1
                else:
                    worker_logger.info(f"[{camera_id}] 이상 징후 감지 ({risk_level}): 백엔드 보고 후 영상 클립 생성")
                    
                    # [Step 1: 백엔드 이벤트 생성]
                    # 1차 VLM 결과를 즉시 전송하여 'Event ID'를 선제적으로 확보합니다.
                    event_id = None
                    try:
                        event_type = vlm_result.get("event_type", "")
                        event_id = self.backend_client.send_vlm_result(
                            camera_id=camera_id,
                            risk=risk_level,
                            type=event_type,
                            occurred_at=occurred_at
                        )
                    except Exception as e:
                        worker_logger.error(f"[{camera_id}] 백엔드 전송 중 오류: {e}")

                    if not event_id:
                        worker_logger.error(f"[{camera_id}] Event ID 생성 실패로 클립 생성을 중단합니다.")
                        self.total_failed += 1
                        continue

                    # [Step 2: 영상 클립 처리 파이프라인]
                    try:
                        buffer = self.packet_buffers.get(camera_id)
                        source_stream = self.source_streams.get(camera_id)

                        if buffer and source_stream:
                            # 2-1) PacketBuffer에서 30초 전체 패킷 추출 (고정 길이)
                            packets = buffer.get_full_buffer(clip_duration=self.config.video_buffer_seconds)
                            worker_logger.debug(f"[{camera_id}] 추출된 패킷 수: {len(packets)}")

                            # 2-2) Muxing: 패킷을 MP4 파일로 변환 (Keyframe 보정 포함)
                            mp4_file = mux_packets_to_mp4(packets, source_stream)
                            
                            # 파일 크기 검증: 0바이트 파일은 업로드하지 않음
                            file_size = mp4_file.getbuffer().nbytes
                            if file_size == 0:
                                worker_logger.warning(f"[{camera_id}] 클립 생성 실패: 0바이트 (패킷 수: {len(packets)})")
                            else:
                                # 2-3) S3 업로드: 생성된 MP4를 저장소에 저장
                                clip_url = self.storage_client.upload_clip(mp4_file, event_id)

                                # 2-4) 백엔드 알림: 클립 확정 API 호출
                                if clip_url:
                                    worker_logger.info(f"[{camera_id}] 클립 업로드 완료: {file_size} bytes")
                                    self.backend_client.confirm_event_clip(event_id)
                        else:
                            # 버퍼 또는 스트림 정보가 없는 경우 상세 로그
                            has_buffer = camera_id in self.packet_buffers
                            has_stream = camera_id in self.source_streams
                            worker_logger.warning(
                                f"[{camera_id}] 클립 생성 불가 - "
                                f"버퍼 등록: {has_buffer}, 스트림 등록: {has_stream}, "
                                f"등록된 카메라: {list(self.source_streams.keys())}"
                            )

                    except Exception as e:
                        worker_logger.error(f"[{camera_id}] 클립 생성/업로드 중 오류: {e}", exc_info=True)

                    # [Step 3: 정밀 분석 (LangGraph) 실행]
                    # 1차 분석 완료 후, 생성된 Event ID를 포함하여 LangGraph를 호출합니다.
                    initial_state = {
                        "camera_id": camera_id,
                        "camera_name": camera_info.get("name", "unknown"),
                        "camera_location": camera_info.get("location", "unknown"),
                        "occurred_at": occurred_at,
                        "frames": frames,
                        "vlm_result": vlm_result,
                        "risk_level": risk_level,
                        "event_type": vlm_result.get("event_type", ""),
                        "event_id": event_id, # 백엔드에서 받은 ID 주입
                        "window_start": task.get("window_start", ""),
                        "window_end": task.get("window_end", ""),
                        "errors": []
                    }

                    # 2-3. LangGraph 실행
                    try:
                        final_state = self.graph.invoke(initial_state)
                        
                        self.total_processed += 1
                        
                        # 최종 결과 확인 및 통계 업데이트
                        final_risk = final_state.get("risk_level", risk_level)
                        
                        if final_risk == "ABNORMAL":
                            self.total_abnormal += 1
                            worker_logger.info(f"[완료] {camera_id} 정밀 분석 완료: ABNORMAL (Event: {final_state.get('event_type')})")
                        elif final_risk == "SUSPICIOUS":
                            worker_logger.info(f"[완료] {camera_id} 정밀 분석 완료: SUSPICIOUS")
                        else:
                            self.total_normal += 1
                            worker_logger.debug(f"[완료] {camera_id} 정밀 분석 완료: NORMAL")
                            
                        if final_state.get("errors"):
                            worker_logger.warning(f"{camera_id} 처리 중 오류 발생: {final_state['errors']}")

                    except Exception as e:
                        self.total_failed += 1
                        worker_logger.error(f"{camera_id} 그래프 실행 중 오류: {e}", exc_info=True)

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
        avg_vlm_time = 0.0
        with self.stats_lock:
            if self.vlm_count > 0:
                avg_vlm_time = self.total_vlm_time / self.vlm_count

        self.logger.info(
            f"컨슈머 통계 - 처리: {self.total_processed}, "
            f"실패: {self.total_failed}, 이상: {self.total_abnormal}, "
            f"정상: {self.total_normal}, 대기열: {self.queue_manager.size()}, "
            f"평균 VLM 시간: {avg_vlm_time:.3f}초"
        )

    def get_stats(self):
        """컨슈머 통계 조회"""
        total = self.total_processed + self.total_failed
        abnormal_rate = (
            (100 * self.total_abnormal / self.total_processed)
            if self.total_processed > 0
            else 0
        )
        
        with self.stats_lock:
            avg_vlm_time = (self.total_vlm_time / self.vlm_count) if self.vlm_count > 0 else 0.0

        return {
            "num_workers": self.num_workers,
            "total_processed": self.total_processed,
            "total_failed": self.total_failed,
            "total_abnormal": self.total_abnormal,
            "total_normal": self.total_normal,
            "success_rate": (100 * self.total_processed / total) if total > 0 else 0,
            "abnormal_rate": abnormal_rate,
            "avg_vlm_time": avg_vlm_time,
        }
