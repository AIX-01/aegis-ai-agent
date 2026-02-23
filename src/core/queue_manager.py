"""
중앙 작업 큐를 위한 오버플로우 보호 기능이 있는 큐 관리자
"""
import logging
import queue
from typing import Dict, Any, Optional
from datetime import datetime


class QueueManager:
    """오버플로우 보호 기능이 있는 스레드 안전 큐"""

    def __init__(self, max_size: int = 20):
        """
        큐 관리자 초기화

        인자:
            max_size: 오버플로우 보호가 작동하기 전 최대 큐 크기
        """
        self.max_size = max_size
        self.queue = queue.Queue()
        self.logger = logging.getLogger("aegis-agent.queue")
        self.total_enqueued = 0
        self.total_dequeued = 0
        self.total_dropped = 0

    def put(self, task: Dict[str, Any], timeout: float = 1.0) -> bool:
        """
        오버플로우 보호 기능으로 큐에 작업 추가

        큐가 가득 차면 가장 오래된 작업 제거 (FIFO 방식)

        인자:
            task: camera_id, 프레임, 타임스탬프 등을 포함하는 작업 딕셔너리
            timeout: 큐 작업에 대한 타임아웃

        반환값:
            작업이 성공적으로 추가되면 True
        """
        try:
            # 큐가 용량에 도달했는지 확인
            if self.queue.qsize() >= self.max_size:
                # 가장 오래된 작업 제거
                try:
                    dropped_task = self.queue.get_nowait()
                    self.total_dropped += 1
                    self.logger.warning(
                        f"큐 오버플로우: 카메라 "
                        f"{dropped_task.get('camera_id', 'unknown')}의 가장 오래된 작업 삭제됨 "
                        f"(윈도우 {dropped_task.get('window_start', 0)}-"
                        f"{dropped_task.get('window_end', 0)}s). "
                        f"총 삭제됨: {self.total_dropped}"
                    )
                except queue.Empty:
                    pass

            # 새 작업 추가
            self.queue.put(task, timeout=timeout)
            self.total_enqueued += 1

            if self.total_enqueued % 10 == 0:
                self.logger.debug(
                    f"큐 통계 - 크기: {self.queue.qsize()}, "
                    f"큐에 추가됨: {self.total_enqueued}, "
                    f"큐에서 제거됨: {self.total_dequeued}, "
                    f"삭제됨: {self.total_dropped}"
                )

            return True

        except queue.Full:
            self.logger.error(
                f"카메라 {task.get('camera_id', 'unknown')}에서 작업 큐에 추가 실패"
            )
            return False
        except Exception as e:
            self.logger.error(f"작업 큐 추가 중 오류 발생: {e}", exc_info=True)
            return False

    def get(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """
        큐에서 작업 가져오기

        인자:
            timeout: 큐 작업에 대한 타임아웃 (None = 무기한 블록)

        반환값:
            작업 딕셔너리 또는 타임아웃/비어있으면 None
        """
        try:
            task = self.queue.get(timeout=timeout)
            self.total_dequeued += 1
            return task
        except queue.Empty:
            return None
        except Exception as e:
            self.logger.error(f"작업 큐 제거 중 오류 발생: {e}", exc_info=True)
            return None

    def size(self) -> int:
        """현재 큐 크기 가져오기"""
        return self.queue.qsize()

    def get_stats(self) -> Dict[str, int]:
        """큐 통계 가져오기"""
        return {
            "current_size": self.queue.qsize(),
            "total_enqueued": self.total_enqueued,
            "total_dequeued": self.total_dequeued,
            "total_dropped": self.total_dropped,
            "in_flight": self.total_enqueued - self.total_dequeued - self.total_dropped,
        }
