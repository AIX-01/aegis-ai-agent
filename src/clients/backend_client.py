"""
스프링부트 백엔드 API 클라이언트
"""
import logging
import time
from typing import Dict, Any, Optional
import requests
from requests.exceptions import RequestException, Timeout

from ..utils import exponential_backoff


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

        # 엔드포인트 분리
        self.create_endpoint = config.backend_create_endpoint
        self.update_endpoint_template = config.backend_update_endpoint
        
        self.timeout = config.backend_timeout
        self.max_retries = config.backend_max_retries
        self.retry_delay = config.backend_retry_delay

    def send_vlm_result(
        self,
        camera_id: str,
        risk: str,
        type: str,
        occurred_at: Any,
    ) -> Optional[str]:
        """
        1차 분석(VLM) 결과를 백엔드 API로 전송하고 event_id를 받습니다.

        Args:
            camera_id: 카메라 식별자
            risk: 1차 분석 위험도 (VLM의 primary_category)
            type: 1차 분석 타입 (VLM의 secondary_category)
            occurred_at: 이벤트 발생 시각 (윈도우 시작 시점)

        Returns:
            전송 성공 시 event_id, 실패 시 None
        """
        payload = {
            "cameraId": camera_id,
            "risk": risk,
            "type": type,
            "occurredAt": occurred_at.isoformat() if hasattr(occurred_at, "isoformat") else str(occurred_at),
        }

        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    self.create_endpoint, # 생성용 엔드포인트 사용
                    json=payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()

                response_data = response.json()
                
                # 백엔드 응답에서 event_id 추출 (여러 키 시도)
                event_id = response_data.get("event_id") or response_data.get("eventId") or response_data.get("id")

                if not event_id:
                    self.logger.error(f"🚫 [백엔드 응답 오류] {camera_id}의 응답에 event_id가 없습니다. 응답: {response_data}")
                    return None

                self.logger.info(f"[백엔드 전송 성공] {camera_id}의 VLM 결과를 전송하고 event_id {event_id}를 받았습니다.")
                return event_id

            except Timeout:
                self.logger.warning(f"⏱️ [백엔드 전송 타임아웃] {camera_id}, 시도: {attempt + 1}/{self.max_retries}")
            except RequestException as e:
                self.logger.warning(f"❌ [백엔드 전송 실패] {camera_id}: {e}, 시도: {attempt + 1}/{self.max_retries}")
            except Exception as e:
                self.logger.error(f"💥 [백엔드 전송 예외] {camera_id}: {e}", exc_info=True)
                break

            if attempt < self.max_retries - 1:
                delay = exponential_backoff(attempt, self.retry_delay)
                time.sleep(delay)

        self.logger.error(f"🚫 [백엔드 전송 최종 실패] {camera_id}의 VLM 결과 전송에 실패했습니다.")
        return None

    def update_event(
        self,
        event_id: str,
        detail_result: Dict[str, Any]
    ) -> bool:
        """
        2차 분석(LLM) 결과로 기존 이벤트를 갱신합니다.

        Args:
            event_id: 갱신할 이벤트 ID
            detail_result: 상세 분석 결과 (risk, type, summary, risk_score 등)

        Returns:
            성공 여부
        """
        # 갱신용 엔드포인트 템플릿에 event_id 적용
        update_endpoint = self.update_endpoint_template.format(event_id=event_id)
        
        risk_score = detail_result.get("risk_score")
        
        payload = {
            "risk": detail_result.get("risk"),
            "type": detail_result.get("type"),
            "summary": detail_result.get("summary"),
            "riskScore": f"{risk_score:.2f}" if isinstance(risk_score, float) else str(risk_score) if risk_score is not None else None,
        }
        final_payload = {k: v for k, v in payload.items() if v is not None}

        if not final_payload:
            self.logger.warning(f"백엔드로 갱신할 데이터가 없습니다. (Event ID: {event_id})")
            return True

        for attempt in range(self.max_retries):
            try:
                response = requests.patch( # PUT -> PATCH 로 변경
                    update_endpoint,
                    json=final_payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                
                self.logger.info(f"[백엔드 갱신 성공] Event ID: {event_id}")
                return True

            except Exception as e:
                self.logger.warning(f"❌ [백엔드 갱신 실패] Event ID {event_id}: {e}, 시도: {attempt + 1}/{self.max_retries}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)

        return False
