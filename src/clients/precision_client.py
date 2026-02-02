"""
정밀 분석 API 클라이언트
"""
import logging
import time
import base64
import json
from typing import List, Dict, Any, Optional
import requests
from requests.exceptions import RequestException, Timeout
from datetime import datetime

from ..utils import exponential_backoff


def json_serializer(obj: Any) -> str:
    """datetime 객체를 포함한 JSON 직렬화를 위한 헬퍼 함수"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class PrecisionClient:
    """정밀 분석 API 클라이언트"""

    def __init__(self, config):
        """
        정밀 분석 클라이언트 초기화

        Args:
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
        frames: List[bytes],
        vlm_metadata: Dict[str, Any],
        task_metadata: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        프레임을 정밀 분석 API로 전송

        Args:
            camera_id: 카메라 식별자
            frames: JPEG 프레임 바이트 리스트 (VLM용 저해상도 프레임 사용)
            vlm_metadata: VLM 분석 결과 메타데이터
            task_metadata: 추가 작업 정보

        Returns:
            API 응답 딕셔너리 또는 실패 시 None
        """
        self.total_requests += 1

        # 페이로드 준비
        payload = self._prepare_payload(
            camera_id, frames, vlm_metadata, task_metadata
        )

        # 전송 데이터 크기 계산
        frame_bytes = sum(len(frame) for frame in frames)
        self.total_bytes_sent += frame_bytes

        # 재시도 루프
        for attempt in range(self.max_retries):
            try:
                # 커스텀 직렬화 함수를 사용하여 JSON 문자열 생성
                json_payload = json.dumps(payload, default=json_serializer)

                # 요청 전송 (json= 대신 data= 사용)
                response = requests.post(
                    self.endpoint,
                    data=json_payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )

                # 상태 확인
                if not response.ok:
                    # 4xx, 5xx 에러 발생 시 상세 응답 내용 로깅
                    self.logger.error(f"HTTP Error {response.status_code}: {response.text}")
                    response.raise_for_status()

                # 응답 파싱
                result = response.json()
                self.total_success += 1

                self.logger.info(
                    f"[성공] 정밀 분석 완료 - "
                    f"카메라: {camera_id}, "
                    f"윈도우: {task_metadata.get('window_start', 0)}-"
                    f"{task_metadata.get('window_end', 0)}"
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

        Args:
            camera_id: 카메라 식별자
            frames: JPEG 프레임 바이트 리스트
            vlm_metadata: VLM 결과 메타데이터
            task_metadata: 작업 메타데이터

        Returns:
            JSON으로 직렬화 가능한 페이로드 딕셔너리
        """
        # 프레임 base64 인코딩
        encoded_frames = [base64.b64encode(frame).decode("utf-8") for frame in frames]

        # 윈도우 시작/종료 시간 안전하게 처리 (None 또는 빈 문자열일 경우 기본값 사용)
        window_start = task_metadata.get("window_start")
        if not window_start:
            window_start = 0
        
        window_end = task_metadata.get("window_end")
        if not window_end:
            window_end = 0

        payload = {
            "camera_id": camera_id,
            "frames": encoded_frames,
            "num_frames": len(frames),
            "occurred_at": task_metadata.get("occurred_at"),  # datetime 객체를 그대로 전달
            "window_start": window_start,
            "window_end": window_end,
            "vlm_result": {
                "risk_level": vlm_metadata.get("risk_level", "UNKNOWN"),
                "event_type": vlm_metadata.get("event_type", "UNKNOWN"),
            }
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
