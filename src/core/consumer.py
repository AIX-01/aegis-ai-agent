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


class ConsumerPool:
    """
    큐에서 분석 작업을 소비하는 스레드 풀 (LangGraph 기반)

    이 클래스는 시스템의 Consumer 역할을 담당하며, Producer가 큐에 넣은
    비디오 분석 작업(Task)을 비동기적으로 처리합니다.

    주요 기능 및 특징:
    1. 스레드 풀 관리: 설정된 수(config.num_workers)만큼의 워커 스레드를 생성하여
       병렬로 작업을 처리합니다. 이를 통해 다수의 카메라 피드를 동시에 분석할 수 있습니다.
    2. LangGraph 통합: 각 분석 작업은 LangGraph로 정의된 워크플로우(build_graph)를
       통해 실행됩니다. 이는 분석 단계(VLM 분석, 검증, 리포트 생성 등)를 유연하게 관리하게 해줍니다.
    3. 작업 소비 및 처리:
       - 큐에서 대기 중인 작업을 가져옵니다 (FIFO).
       - 작업 데이터(프레임, 카메라 정보)를 LangGraph의 초기 상태로 변환합니다.
       - 그래프를 실행하고 결과를 받아 통계를 업데이트합니다.
    4. 오류 처리 및 통계: 작업 처리 중 발생하는 예외를 포착하여 로깅하고,
       전체 처리량, 성공/실패 횟수 등의 통계 지표를 유지합니다.
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
        개별 워커 스레드의 메인 루프 (LangGraph 실행)

        각 워커는 독립적인 스레드에서 실행되며 다음과 같은 생명주기를 가집니다:
        1. 대기: 큐에서 새로운 작업이 들어올 때까지 대기합니다.
        2. 인출: 큐에서 작업(Task)을 하나 가져옵니다.
        3. 준비: 작업 데이터를 LangGraph가 이해할 수 있는 상태 객체(State)로 변환합니다.
        4. 실행: 정의된 분석 그래프(self.graph)를 실행(invoke)합니다.
        5. 결과 처리: 그래프 실행 결과를 분석하여 위험도(Normal/Suspicious/Abnormal)를 판별하고
           로그를 남기거나 통계를 갱신합니다.

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
                
                worker_logger.debug(f"{camera_id}의 작업을 처리합니다 (LangGraph)")

                # 초기 상태 구성
                initial_state = {
                    "camera_id": camera_id,
                    "camera_name": camera_info.get("name", "unknown"),
                    "camera_location": camera_info.get("location", "unknown"),
                    "occurred_at": task.get("timestamp"),
                    "frames": task.get("low_res_frames", []),
                    "errors": []
                }

                # LangGraph 실행
                try:
                    final_state = self.graph.invoke(initial_state)
                    
                    self.total_processed += 1
                    
                    # 결과 확인 및 통계 업데이트
                    risk_level = final_state.get("risk_level", "UNKNOWN")
                    
                    if risk_level == "ABNORMAL":
                        self.total_abnormal += 1
                        worker_logger.info(f"[완료] {camera_id} 분석 완료: ABNORMAL (Event: {final_state.get('event_type')})")
                    elif risk_level == "SUSPICIOUS":
                        # 최종 상태가 SUSPICIOUS인 경우는 검증 후 NORMAL이 되지 않고 끝난 경우 등
                        worker_logger.info(f"[완료] {camera_id} 분석 완료: SUSPICIOUS")
                    else:
                        self.total_normal += 1
                        worker_logger.debug(f"[완료] {camera_id} 분석 완료: NORMAL")
                        
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
