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


class ConsumerPool:
    """
    큐에서 분석 작업을 소비하는 스레드 풀 (LangGraph 기반)

    이 클래스는 시스템의 Consumer 역할을 담당하며, Producer가 큐에 넣은
    비디오 분석 작업(Task)을 비동기적으로 처리합니다.

    주요 기능 및 특징:
    1. VLM 선행 처리: 모든 작업을 LangGraph로 보내지 않고, VLM 분석을 먼저 수행하여
       '이상/의심' 징후가 있을 때만 LangGraph 파이프라인을 실행합니다. 이를 통해 효율성을 극대화합니다.
    2. 스레드 풀 관리: 설정된 수(config.num_workers)만큼의 워커 스레드를 생성하여
       병렬로 작업을 처리합니다.
    3. LangGraph 통합: 정밀 분석 및 사후 처리는 LangGraph로 정의된 워크플로우를 통해 실행됩니다.
    """

    def __init__(
        self,
        config,
        queue_manager,
    ):
        """
        컨슈머 풀 초기화

        Args:
            config: 시스템 설정
            queue_manager: 중앙 큐 관리자
        """
        self.config = config
        self.queue_manager = queue_manager
        self.logger = logging.getLogger("aegis-agent.consumer")

        # VLM 클라이언트 초기화 (선행 분석용)
        self.vlm_client = VLMClient(config)
        
        # 백엔드 클라이언트 초기화 (1차 결과 즉시 전송용)
        self.backend_client = BackendClient(config)

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
                    vlm_result = self.vlm_client.analyze_frames(camera_id, frames, task_metadata)
                    
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
                    worker_logger.info(f"[{camera_id}] 이상 징후 감지 ({risk_level}): 백엔드 보고 후 LangGraph 실행")
                    
                    # 2-1. 백엔드에 1차 결과 즉시 보고
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
                        worker_logger.error(f"[{camera_id}] Event ID 생성 실패로 LangGraph 실행을 중단합니다.")
                        self.total_failed += 1
                        continue

                    # 2-2. 초기 상태 구성 (Event ID 포함)
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
        self.logger.info(
            f"컨슈머 통계 - 처리: {self.total_processed}, "
            f"실패: {self.total_failed}, 이상: {self.total_abnormal}, "
            f"정상: {self.total_normal}, 대기열: {self.queue_manager.size()}"
        )

    def get_stats(self):
        """컨슈머 통계 조회"""
        total = self.total_processed + self.total_failed
        abnormal_rate = (
            (100 * self.total_abnormal / self.total_processed)
            if self.total_processed > 0
            else 0
        )
        return {
            "num_workers": self.num_workers,
            "total_processed": self.total_processed,
            "total_failed": self.total_failed,
            "total_abnormal": self.total_abnormal,
            "total_normal": self.total_normal,
            "success_rate": (100 * self.total_processed / total) if total > 0 else 0,
            "abnormal_rate": abnormal_rate,
        }
