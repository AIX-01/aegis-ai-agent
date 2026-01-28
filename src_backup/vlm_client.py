"""
재시도 및 타임아웃 처리를 포함한 VLM API 클라이언트
"""
import logging
import time
import base64
from typing import List, Dict, Any, Optional
import requests
from requests.exceptions import RequestException, Timeout

from .utils import exponential_backoff


class VLMClient:
    """VLM(Vision Language Model) API와 통신하기 위한 클라이언트"""

    def __init__(self, config):
        """
        VLM 클라이언트 초기화

        인자:
            config: 시스템 설정
        """
        self.config = config
        self.logger = logging.getLogger("aegis-agent.vlm_client")

        self.endpoint = config.vlm_endpoint
        self.timeout = config.vlm_timeout
        self.max_retries = config.vlm_max_retries
        self.retry_delay = config.vlm_retry_delay

        self.total_requests = 0
        self.total_success = 0
        self.total_failures = 0

    def analyze_frames(
        self, camera_id: str, frames: List[bytes], task_metadata: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        분석을 위해 VLM API로 프레임 전송

        인자:
            camera_id: 카메라 식별자
            frames: JPEG으로 인코딩된 프레임 바이트 리스트
            task_metadata: 추가 작업 정보 (타임스탬프, 윈도우 정보)

        반환값:
            API 응답 딕셔너리 또는 실패 시 None
        """
        self.total_requests += 1

        # 페이로드 준비
        payload = self._prepare_payload(camera_id, frames, task_metadata)

        # 재시도 루프
        for attempt in range(self.max_retries):
            try:
                # 요청 전송
                response = requests.post(
                    self.endpoint,
                    json=payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )

                # 응답 상태 확인
                response.raise_for_status()

                # 응답 파싱
                result = response.json()
                self.total_success += 1

                self.logger.debug(
                    f"VLM 분석 성공: {camera_id} "
                    f"(윈도우 {task_metadata.get('window_start', 0)}-"
                    f"{task_metadata.get('window_end', 0)}s)"
                )

                return result

            except Timeout:
                self.logger.warning(
                    f"VLM 요청 타임아웃: {camera_id} (시도 {attempt + 1}/{self.max_retries})"
                )

            except RequestException as e:
                self.logger.warning(
                    f"VLM 요청 실패: {camera_id}: {e} "
                    f"(시도 {attempt + 1}/{self.max_retries})"
                )

            except Exception as e:
                self.logger.error(
                    f"VLM 요청 중 예상치 못한 오류 발생: {camera_id}: {e}",
                    exc_info=True,
                )

            # 재시도 전 지수 백오프
            if attempt < self.max_retries - 1:
                delay = exponential_backoff(attempt, self.retry_delay)
                self.logger.debug(f"{delay:.1f}초 후 재시도합니다...")
                time.sleep(delay)

        # 모든 재시도 실패
        self.total_failures += 1
        self.logger.error(
            f"{self.max_retries}번의 시도 후 VLM 분석 실패: {camera_id}. "
            f"성공률: {self.total_success}/{self.total_requests} "
            f"({100 * self.total_success / self.total_requests:.1f}%)"
        )
        return None

    def _prepare_payload(
        self, camera_id: str, frames: List[bytes], metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        VLM API를 위한 JSON 페이로드 준비

        인자:
            camera_id: 카메라 식별자
            frames: JPEG 프레임 바이트 리스트
            metadata: 작업 메타데이터

        반환값:
            JSON으로 직렬화 가능한 페이로드 딕셔너리
        """
        # 프레임을 base64로 인코딩
        encoded_frames = [base64.b64encode(frame).decode("utf-8") for frame in frames]

        payload = {
            "camera_id": camera_id,
            "frames": encoded_frames,
            "num_frames": len(frames),
            "timestamp": metadata.get("timestamp", "").isoformat()
            if hasattr(metadata.get("timestamp", ""), "isoformat")
            else str(metadata.get("timestamp", "")),
            "window_start": metadata.get("window_start", 0),
            "window_end": metadata.get("window_end", 0),
        }

        return payload

    def get_stats(self) -> Dict[str, int]:
        """클라이언트 통계 조회"""
        return {
            "total_requests": self.total_requests,
            "total_success": self.total_success,
            "total_failures": self.total_failures,
            "success_rate": (
                100 * self.total_success / self.total_requests
                if self.total_requests > 0
                else 0
            ),
        }
