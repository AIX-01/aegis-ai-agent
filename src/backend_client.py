"""
스프링부트 백엔드 API 클라이언트
"""
import logging
import time
from typing import Dict, Any, Optional
import requests
from requests.exceptions import RequestException, Timeout

from .utils import exponential_backoff


class BackendClient:
    """VLM 분석 결과를 백엔드로 전송하는 클라이언트"""

    def __init__(self, config):
        """
        백엔드 클라이언트 초기화

        Args:
            config: 시스템 설정
        """
        self.config = config
        self.logger = logging.getLogger("aegis-agent.backend")

        self.endpoint = config.backend_endpoint
        self.timeout = config.backend_timeout
        self.max_retries = config.backend_max_retries
        self.retry_delay = config.backend_retry_delay

    def send_vlm_result(
        self,
        camera_id: str,
        vlm_result: Dict[str, Any],
        task_metadata: Dict[str, Any],
    ) -> Optional[str]:
        """
        VLM 분석 결과를 백엔드 API로 전송하고 event_id를 받습니다.

        Args:
            camera_id: 카메라 식별자
            vlm_result: VLM 분석 결과 딕셔너리
            task_metadata: 추가 작업 정보 (타임스탬프 등)

        Returns:
            전송 성공 시 event_id, 실패 시 None
        """
        payload = self._prepare_payload(camera_id, vlm_result, task_metadata)

        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    self.endpoint,
                    json=payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()

                # 응답에서 event_id 추출
                response_data = response.json()
                event_id = response_data.get("eventId")

                if not event_id:
                    self.logger.error(f"🚫 [백엔드 응답 오류] {camera_id}의 응답에 eventId가 없습니다.")
                    return None

                self.logger.info(f"[백엔드 전송 성공] {camera_id}의 VLM 결과를 전송하고 eventId {event_id}를 받았습니다.")
                return event_id

            except Timeout:
                self.logger.warning(
                    f"⏱️ [백엔드 전송 타임아웃] {camera_id}, 시도: {attempt + 1}/{self.max_retries}"
                )
            except RequestException as e:
                self.logger.warning(
                    f"❌ [백엔드 전송 실패] {camera_id}: {e}, 시도: {attempt + 1}/{self.max_retries}"
                )
            except Exception as e:
                self.logger.error(f"💥 [백엔드 전송 예외] {camera_id}: {e}", exc_info=True)
                # 예기치 않은 오류는 즉시 실패 처리
                break

            if attempt < self.max_retries - 1:
                delay = exponential_backoff(attempt, self.retry_delay)
                time.sleep(delay)

        self.logger.error(f"🚫 [백엔드 전송 최종 실패] {camera_id}의 VLM 결과 전송에 실패했습니다.")
        return None

    def _prepare_payload(
        self,
        camera_id: str,
        vlm_result: Dict[str, Any],
        task_metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """백엔드 API용 페이로드 준비"""
        timestamp = task_metadata.get("timestamp", "")
        
        payload = {
            "cameraId": camera_id,
            "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
            "windowStart": task_metadata.get("window_start", ""),
            "windowEnd": task_metadata.get("window_end", ""),
            "primaryCategory": vlm_result.get("primary_category", "unknown"),
            "secondaryCategory": vlm_result.get("secondary_category", ""),
            "confidence": vlm_result.get("confidence", 0.0),
            "description": vlm_result.get("description", ""),
        }
        return payload
