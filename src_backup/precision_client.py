"""
정밀 분석 API를 위한 클라이언트
"""
import logging
import time
import base64
from typing import List, Dict, Any, Optional
import requests
from requests.exceptions import RequestException, Timeout

from .utils import exponential_backoff


class PrecisionClient:
    """정밀 분석 API 클라이언트"""

    def __init__(self, config):
        """
        정밀 분석 클라이언트 초기화

        인자:
            config: 시스템 설정
        """
        self.config = config
        self.logger = logging.getLogger("aegis-agent.precision")

        self.endpoint = config.precision_endpoint
        self.timeout = config.precision_timeout
        self.max_retries = config.precision_max_retries
        self.retry_delay = config.precision_retry_delay

        # 통계
        self.total_requests = 0
        self.total_success = 0
        self.total_failures = 0
        self.total_bytes_sent = 0

    def send_for_analysis(
        self,
        camera_id: str,
        high_res_frames: List[bytes],
        vlm_metadata: Dict[str, Any],
        task_metadata: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        고해상도 프레임을 정밀 분석 API로 전송

        인자:
            camera_id: 카메라 식별자
            high_res_frames: 고해상도 JPEG 프레임 바이트 리스트
            vlm_metadata: VLM 분석 결과 메타데이터
            task_metadata: 추가 작업 정보

        반환값:
            API 응답 딕셔너리 또는 실패 시 None
        """
        self.total_requests += 1

        # 페이로드 준비
        payload = self._prepare_payload(
            camera_id, high_res_frames, vlm_metadata, task_metadata
        )

        # 전송 데이터 크기 계산
        frame_bytes = sum(len(frame) for frame in high_res_frames)
        self.total_bytes_sent += frame_bytes

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

                # 상태 확인
                response.raise_for_status()

                # 응답 파싱
                result = response.json()
                self.total_success += 1

                self.logger.info(
                    f"[성공] 정밀 분석 완료 - "
                    f"카메라: {camera_id}, "
                    f"윈도우: {task_metadata.get('window_start', 0)}-"
                    f"{task_metadata.get('window_end', 0)}s"
                )

                return result

            except Timeout:
                self.logger.warning(
                    f"⏱️ 정밀 분석 타임아웃 - "
                    f"카메라: {camera_id}, "
                    f"시도: {attempt + 1}/{self.max_retries}"
                )

            except RequestException as e:
                self.logger.warning(
                    f"❌ 정밀 분석 요청 실패 - "
                    f"카메라: {camera_id}: {e}, "
                    f"시도: {attempt + 1}/{self.max_retries}"
                )

            except Exception as e:
                self.logger.error(
                    f"💥 정밀 분석 예외 - "
                    f"카메라: {camera_id}: {e}",
                    exc_info=True,
                )

            # 지수 백오프
            if attempt < self.max_retries - 1:
                delay = exponential_backoff(attempt, self.retry_delay)
                self.logger.debug(f"{delay:.1f}초 후 재시도합니다...")
                time.sleep(delay)

        # 모든 재시도 실패
        self.total_failures += 1
        self.logger.error(
            f"🚫 정밀 분석 최종 실패 - "
            f"카메라: {camera_id}, "
            f"재시도 횟수: {self.max_retries}, "
            f"성공률: {self.total_success}/{self.total_requests} "
            f"({100 * self.total_success / self.total_requests:.1f}%)"
        )
        return None

    def _prepare_payload(
        self,
        camera_id: str,
        frames: List[bytes],
        vlm_metadata: Dict[str, Any],
        task_metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        정밀 분석 API용 페이로드 준비

        인자:
            camera_id: 카메라 식별자
            frames: 고해상도 JPEG 프레임 바이트 리스트
            vlm_metadata: VLM 결과 메타데이터
            task_metadata: 작업 메타데이터

        반환값:
            JSON으로 직렬화 가능한 페이로드 딕셔너리
        """
        # 프레임 base64 인코딩
        encoded_frames = [base64.b64encode(frame).decode("utf-8") for frame in frames]

        payload = {
            "camera_id": camera_id,
            "frames": encoded_frames,
            "num_frames": len(frames),
            "timestamp": task_metadata.get("timestamp", "").isoformat()
            if hasattr(task_metadata.get("timestamp", ""), "isoformat")
            else str(task_metadata.get("timestamp", "")),
            "window_start": task_metadata.get("window_start", 0),
            "window_end": task_metadata.get("window_end", 0),
            # VLM 메타데이터 포함
            "vlm_result": {
                "primary_category": vlm_metadata.get("primary_category", "unknown"),
                "secondary_category": vlm_metadata.get("secondary_category", ""),
                "confidence": vlm_metadata.get("confidence", 0.0),
                "description": vlm_metadata.get("description", ""),
            },
        }

        return payload

    def get_stats(self) -> Dict[str, Any]:
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
            "total_bytes_sent": self.total_bytes_sent,
            "total_mb_sent": self.total_bytes_sent / (1024 * 1024),
        }
