"""
VLM 응답을 기다리는 고해상도 프레임 버퍼를 관리합니다.
"""
import logging
import threading
import time
import uuid
from typing import Dict, List, Optional, Tuple


class PendingBufferManager:
    """VLM 응답 대기 버퍼 관리자"""

    def __init__(self, config):
        """
        대기 버퍼 관리자 초기화

        인자:
            config: 시스템 설정
        """
        self.config = config
        self.logger = logging.getLogger("aegis-agent.pending_buffer")

        # 버퍼: {버퍼_id: (프레임들, 타임스탬프, 카메라_id)}
        self.buffers: Dict[str, Tuple[List[bytes], float, str]] = {}
        self.lock = threading.Lock()

        # 통계
        self.total_stored = 0
        self.total_retrieved = 0
        self.total_expired = 0
        self.total_dropped = 0

        # 자동 정리 스레드
        self.shutdown_event = threading.Event()
        self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.cleanup_thread.start()

    def store(self, camera_id: str, frames: List[bytes]) -> str:
        """
        고해상도 프레임 버퍼 저장

        인자:
            camera_id: 카메라 식별자
            frames: 고해상도 JPEG 프레임 바이트 리스트

        반환값:
            buffer_id: 고유 버퍼 식별자
        """
        buffer_id = f"{camera_id}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"

        with self.lock:
            self.buffers[buffer_id] = (frames, time.time(), camera_id)
            self.total_stored += 1

        self.logger.debug(
            f"버퍼 저장됨: {buffer_id} "
            f"({len(frames)} frames, 카메라: {camera_id})"
        )

        return buffer_id

    def retrieve(self, buffer_id: str) -> Optional[List[bytes]]:
        """
        버퍼에서 프레임 가져오기 및 삭제

        인자:
            buffer_id: 버퍼 식별자

        반환값:
            프레임 바이트 리스트 또는 찾지 못한 경우 None
        """
        with self.lock:
            if buffer_id in self.buffers:
                frames, _, camera_id = self.buffers.pop(buffer_id)
                self.total_retrieved += 1

                self.logger.debug(
                    f"버퍼 검색 성공: {buffer_id} "
                    f"({len(frames)} frames, 카메라: {camera_id})"
                )

                return frames
            else:
                self.logger.warning(
                    f"버퍼 없음: {buffer_id} (만료되었거나 이미 사용됨)"
                )
                return None

    def drop(self, buffer_id: str) -> bool:
        """
        트리거 미발생 시 버퍼만 삭제

        인자:
            buffer_id: 버퍼 식별자

        반환값:
            버퍼가 삭제된 경우 True
        """
        with self.lock:
            if buffer_id in self.buffers:
                _, _, camera_id = self.buffers.pop(buffer_id)
                self.total_dropped += 1

                self.logger.debug(
                    f"버퍼 삭제됨: {buffer_id} "
                    f"(트리거 미발생, 카메라: {camera_id})"
                )
                return True
            return False

    def _cleanup_loop(self):
        """자동 정리 스레드"""
        self.logger.info("버퍼 정리 스레드 시작됨")

        while not self.shutdown_event.is_set():
            try:
                time.sleep(10)  # 10초마다 체크
                self._cleanup_expired_buffers()
            except Exception as e:
                self.logger.error(f"정리 루프 오류: {e}", exc_info=True)

        self.logger.info("버퍼 정리 스레드 중지됨")

    def _cleanup_expired_buffers(self):
        """60초 지난 버퍼 자동 삭제"""
        current_time = time.time()
        timeout = self.config.buffer_timeout

        with self.lock:
            expired = [
                buffer_id
                for buffer_id, (_, timestamp, _) in self.buffers.items()
                if current_time - timestamp > timeout
            ]

            for buffer_id in expired:
                frames, timestamp, camera_id = self.buffers.pop(buffer_id)
                self.total_expired += 1

                age = current_time - timestamp
                self.logger.warning(
                    f"버퍼 타임아웃: {buffer_id} "
                    f"(경과 시간: {age:.1f}s, 카메라: {camera_id}, "
                    f"프레임: {len(frames)})"
                )

        if expired:
            self.logger.info(
                f"{len(expired)}개 버퍼 타임아웃으로 삭제됨 "
                f"(총 만료: {self.total_expired})"
            )

    def get_stats(self) -> Dict:
        """버퍼 통계 조회"""
        with self.lock:
            current_count = len(self.buffers)
            total_memory = sum(
                sum(len(frame) for frame in frames) for frames, _, _ in self.buffers.values()
            )

        return {
            "current_buffers": current_count,
            "total_stored": self.total_stored,
            "total_retrieved": self.total_retrieved,
            "total_expired": self.total_expired,
            "total_dropped": self.total_dropped,
            "memory_bytes": total_memory,
            "memory_mb": total_memory / (1024 * 1024),
        }

    def shutdown(self):
        """관리자 종료"""
        self.logger.info("Pending buffer 관리자 종료 중...")
        self.shutdown_event.set()

        if self.cleanup_thread.is_alive():
            self.cleanup_thread.join(timeout=5)

        with self.lock:
            remaining = len(self.buffers)

        stats = self.get_stats()
        self.logger.info(
            f"Pending buffer 관리자 중지됨 - "
            f"남은 버퍼: {remaining}, "
            f"저장: {stats['total_stored']}, "
            f"검색: {stats['total_retrieved']}, "
            f"만료: {stats['total_expired']}, "
            f"삭제: {stats['total_dropped']}"
        )
