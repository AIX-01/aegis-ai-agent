"""
VLM 분석 작업용 Consumer 스레드 풀 - LangGraph 기반 파이프라인
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
import time
from typing import Optional

# LangGraph 빌더 및 핵심 클라이언트 import
from ..graph.analysis_graph import build_graph
from ..clients.vlm_client import VLMClient
from ..clients.backend_client import BackendClient
from ..core.muxer import mux_packets_to_mp4


class ConsumerPool:
    """
    큐에서 분석 작업을 소비하고 VLM 분석 및 사후 처리를 관리하는 스레드 풀
    """

    def __init__(
        self,
        config,
        queue_manager,
        packet_buffers=None, # 카메라별 영상 패킷 버퍼
        source_streams=None, # 카메라별 원본 RTSP 스트림 정보
        efs_reader=None,     # EFS 패킷 리더 (worker 모드용)
    ):
        """컨슈머 풀 초기화"""
        self.config = config
        self.queue_manager = queue_manager
        self.packet_buffers = packet_buffers if packet_buffers is not None else {}
        self.source_streams = source_streams if source_streams is not None else {}
        self.efs_reader = efs_reader
        self.logger = logging.getLogger("aegis-agent.consumer")

        # 분석용 클라이언트 초기화
        self.vlm_client = VLMClient(config)
        self.backend_client = BackendClient(config)

        # LangGraph 워크플로우 빌드 (정밀 분석용)
        self.logger.info("LangGraph 워크플로우를 빌드합니다...")
        self.graph = build_graph(config)

        self.num_workers = config.num_workers
        self.executor: Optional[ThreadPoolExecutor] = None
        self.shutdown_event = threading.Event()

        # 분석 통계 데이터
        self.total_processed = 0
        self.total_failed = 0
        self.total_abnormal = 0
        self.total_normal = 0
        self.total_vlm_time = 0.0
        self.vlm_count = 0
        self.stats_lock = threading.Lock()

    def start(self):
        """컨슈머 스레드 풀 시작"""
        self.logger.info(f"{self.num_workers}개의 워커로 컨슈머 풀을 시작합니다.")
        self.executor = ThreadPoolExecutor(
            max_workers=self.num_workers, thread_name_prefix="consumer"
        )
        for i in range(self.num_workers):
            self.executor.submit(self._worker_loop, i)

    def _worker_loop(self, worker_id: int):
        """개별 워커 스레드의 분석 루프"""
        worker_logger = logging.getLogger(f"aegis-agent.consumer.worker-{worker_id}")
        worker_logger.info(f"워커 {worker_id} 가동 시작")

        while not self.shutdown_event.is_set():
            try:
                # 1. 큐에서 분석 대상 윈도우 인출
                task = self.queue_manager.get(timeout=1.0)
                if task is None:
                    continue

                camera_info = task.get("camera_info", {})
                camera_id = camera_info.get("id", "unknown")
                frames = task.get("low_res_frames", [])
                frame_timestamps = task.get("frame_timestamps", [])
                occurred_at = frame_timestamps[0] if frame_timestamps else task.get("timestamp")

                # 2. VLM 1차 분석 수행
                risk_level = "NORMAL" # 기본값 설정
                event_type = "NONE"   # 기본값 설정
                vlm_result = {}
                
                try:
                    # 메타데이터 구성 (카메라 ID 및 윈도우 시간 정보)
                    task_metadata = {
                        "timestamp": occurred_at, 
                        "window_start": task.get("window_start"), 
                        "window_end": task.get("window_end")
                    }
                    
                    vlm_start_time = time.time()
                    # VLM 서버 호출 (class1, class2 응답 기대)
                    vlm_result = self.vlm_client.analyze_frames(camera_id, frames, task_metadata)
                    vlm_duration = time.time() - vlm_start_time
                    
                    # 통계 기록
                    with self.stats_lock:
                        self.total_vlm_time += vlm_duration
                        self.vlm_count += 1

                    # VLM 출력값 매핑 (class1 -> risk_level, class2 -> event_type)
                    if vlm_result:
                        # VLMClient에서 보정한 risk_level이 있으면 사용, 없으면 class1 사용
                        risk_level = vlm_result.get("risk_level") or vlm_result.get("class1", "normal")
                        risk_level = risk_level.upper()

                        # VLMClient에서 보정한 event_type이 있으면 사용, 없으면 class2 사용
                        # event_type과 class2 둘 다 없으면 ValueError 발생 -> except 블록에서 처리 후 다음 작업으로 넘어감
                        event_type = vlm_result.get("event_type") or vlm_result.get("class2")
                        if not event_type:
                            raise ValueError("VLM 응답에 event_type 또는 class2 값이 없습니다.")
                        event_type = event_type.upper()

                    else:
                        worker_logger.warning(f"[{camera_id}] VLM 응답이 비어있어 NORMAL로 간주합니다.")

                except Exception as e:
                    worker_logger.error(f"[{camera_id}] VLM 분석 실패: {e}")
                    self.total_failed += 1
                    continue

                # 3. 분석 결과에 따른 후속 조치 분기
                if risk_level == "NORMAL":
                    # 정상 상황이면 로그만 남기고 종료
                    worker_logger.debug(f"[정상] {camera_id} 분석 완료")
                    self.total_processed += 1
                    self.total_normal += 1
                else:
                    # 의심(SUSPICIOUS) 또는 이상(ABNORMAL) 상황 발생 시
                    worker_logger.info(f"[{camera_id}] 이벤트 감지! 등급: {risk_level}, 유형: {event_type}")
                    
                    # [Step 1: 백엔드에 이벤트 생성 요청 및 ID 확보]
                    event_id = None
                    try:
                        event_id = self.backend_client.send_vlm_result(
                            camera_id=camera_id,
                            risk=risk_level,   # VLM의 class1
                            type=event_type,   # VLM의 class2
                            occurred_at=occurred_at
                        )
                    except Exception as e:
                        worker_logger.error(f"[{camera_id}] 백엔드 이벤트 생성 실패: {e}")

                    if not event_id:
                        worker_logger.error(f"[{camera_id}] Event ID 미발급으로 클립 생성을 중단합니다.")
                        self.total_failed += 1
                        continue

                    # [Step 2: 영상 클립(MP4) 생성 및 업로드]
                    try:
                        mp4_file = None

                        if self.config.agent_mode == "all":
                            # 로컬 모드: PacketBuffer에서 직접 추출 (기존 로직)
                            buffer = self.packet_buffers.get(camera_id)
                            source_stream = self.source_streams.get(camera_id)

                            if buffer and source_stream:
                                packets = buffer.get_full_buffer(clip_duration=self.config.video_buffer_seconds)
                                mp4_file = mux_packets_to_mp4(packets, source_stream)
                            else:
                                worker_logger.warning(f"[{camera_id}] 영상 버퍼 정보를 찾을 수 없습니다.")
                        else:
                            # AWS 모드: EFS에서 패킷 읽기 → muxing
                            if self.efs_reader:
                                mp4_file = self.efs_reader.read_and_mux(
                                    camera_id, clip_duration=self.config.video_buffer_seconds
                                )
                            else:
                                worker_logger.warning(f"[{camera_id}] EFS 리더가 설정되지 않았습니다.")

                        if mp4_file and mp4_file.getbuffer().nbytes > 0:
                            # 백엔드에서 제공하는 업로드 경로로 영상 전송
                            upload_url = self.backend_client.get_clip_upload_url(event_id)
                            if upload_url and self.backend_client.upload_clip(upload_url, mp4_file.getvalue()):
                                # 업로드 완료 보고
                                self.backend_client.confirm_event_clip(event_id)
                                worker_logger.info(f"[{camera_id}] 영상 클립 업로드 성공")

                    except Exception as e:
                        worker_logger.error(f"[{camera_id}] 클립 처리 중 오류: {e}")

                    # [Step 3: 정밀 분석 그래프 실행]
                    try:
                        initial_state = {
                            "camera_id": camera_id,
                            "camera_name": camera_info.get("name", "unknown"),
                            "camera_location": camera_info.get("location", "unknown"),
                            "occurred_at": occurred_at,
                            "frames": frames,
                            "frame_timestamps": frame_timestamps,  # 프레임별 타임스탬프 추가
                            "vlm_result": vlm_result,
                            "risk_level": risk_level,
                            "event_type": event_type,
                            "event_id": event_id,
                            "window_start": task.get("window_start", ""),
                            "window_end": task.get("window_end", ""),
                            "errors": []
                        }

                        # LangGraph 실행 (정밀 분석 서버 연동 등)
                        final_state = self.graph.invoke(initial_state)

                        # run config 적용 예시(아래 코드 사용 시 위 final_state 주석 처리 필요)
                        # run_config = {
                        #     "run_name": f"{camera_id}-{risk_level}",
                        #     "tags": [camera_id, risk_level, event_type],
                        #     "metadata": {
                        #         "camera_id": camera_id,
                        #         "event_id": event_id,
                        #         "risk_level": risk_level,
                        #         "event_type": event_type,
                        #     },
                        # }
                        # final_state = self.graph.invoke(initial_state, config=run_config)
                        self.total_processed += 1
                        
                        # 최종 결과 통계 업데이트
                        final_risk = final_state.get("risk_level", risk_level)
                        if final_risk == "ABNORMAL":
                            self.total_abnormal += 1
                        else:
                            self.total_normal += 1
                            
                    except Exception as e:
                        worker_logger.error(f"[{camera_id}] 정밀 분석 그래프 실행 오류: {e}")
                        self.total_failed += 1

                # 10건 단위로 분석 통계 출력
                if (self.total_processed + self.total_failed) % 10 == 0:
                    self._log_stats()

            except Exception as e:
                worker_logger.error(f"워커 루프 치명적 오류: {e}", exc_info=True)
                time.sleep(1)

        worker_logger.info(f"워커 {worker_id} 종료")

    def shutdown(self):
        """컨슈머 풀의 모든 워커 스레드를 정상 종료합니다."""
        self.logger.info("컨슈머 풀 종료 중...")
        self.shutdown_event.set()
        if self.executor:
            self.executor.shutdown(wait=True)
        self.logger.info("컨슈머 풀 종료 완료")
        self._log_stats()

    def _log_stats(self):
        """현재까지의 분석 통계를 로그로 출력합니다."""
        avg_vlm_time = 0.0
        with self.stats_lock:
            if self.vlm_count > 0:
                avg_vlm_time = self.total_vlm_time / self.vlm_count

        self.logger.info(
            f"분석 현황 - 총 처리: {self.total_processed}, "
            f"실패: {self.total_failed}, 이상 감지: {self.total_abnormal}, "
            f"정상 판정: {self.total_normal}, 평균 VLM 소요시간: {avg_vlm_time:.3f}초"
        )

    def get_stats(self):
        """외부에서 통계 데이터를 조회할 때 사용합니다."""
        total = self.total_processed + self.total_failed
        abnormal_rate = (100 * self.total_abnormal / self.total_processed) if self.total_processed > 0 else 0
        
        with self.stats_lock:
            avg_vlm_time = (self.total_vlm_time / self.vlm_count) if self.vlm_count > 0 else 0.0

        return {
            "total_processed": self.total_processed,
            "total_failed": self.total_failed,
            "total_abnormal": self.total_abnormal,
            "total_normal": self.total_normal,
            "success_rate": (100 * self.total_processed / total) if total > 0 else 0,
            "abnormal_rate": abnormal_rate,
            "avg_vlm_time": avg_vlm_time,
        }
