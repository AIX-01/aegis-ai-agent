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

        # 엔드포인트 분리 (생성/갱신/클립)
        # 갱신 엔드포인트가 분석 결과 + 보고서 + 상태를 통합 처리
        self.create_endpoint = config.backend_create_endpoint
        self.update_endpoint_template = config.backend_update_endpoint  # 통합 갱신 엔드포인트
        self.clip_endpoint_template = config.backend_clip_endpoint

        # Human-in-the-Loop (HITL) 엔드포인트 템플릿 (config에서 관리)
        self.action_create_endpoint_template = config.backend_action_create_endpoint
        self.action_confirm_endpoint_template = config.backend_action_confirm_endpoint
        self.action_update_endpoint_template = config.backend_action_update_endpoint

        # base_url 추출 (create_endpoint에서 /internal 이전까지)
        # 예: "http://localhost:8080/internal/agent/events" → "http://localhost:8080"
        self.base_url = self._extract_base_url(self.create_endpoint)

        self.timeout = config.backend_timeout
        self.max_retries = config.backend_max_retries
        self.retry_delay = config.backend_retry_delay

    def _extract_base_url(self, endpoint: str) -> str:
        """
        엔드포인트에서 base_url을 추출합니다.

        예: "http://localhost:8080/internal/agent/events" → "http://localhost:8080"

        Args:
            endpoint: 전체 엔드포인트 URL

        Returns:
            base_url (스키마 + 호스트 + 포트)
        """
        from urllib.parse import urlparse

        parsed = urlparse(endpoint)
        return f"{parsed.scheme}://{parsed.netloc}"

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
        기존 이벤트를 갱신합니다. (분석 결과, 보고서, 상태 통합)

        [API 엔드포인트]
        PATCH /internal/agent/events/{eventId}

        [Request Body] - 업데이트할 값만 전달
        {
            "risk": "normal | suspicious | abnormal", (optional)
            "type": "assault | burglary | dump | swoon | vandalism", (optional)
            "summary": "AI 분석 요약", (optional)
            "report": "상세 보고서 내용", (optional)
            "status": "processing | analyzed" (optional)
        }

        [Response Body]
        {
            "eventId": "uuid"
        }

        Args:
            event_id: 갱신할 이벤트 ID
            detail_result: 갱신할 데이터 딕셔너리
                - risk: 위험도 (normal/suspicious/abnormal)
                - type: 이벤트 유형 (assault/burglary/dump/swoon/vandalism)
                - summary: AI 분석 요약
                - report: 상세 보고서 내용
                - status: 상태 (processing/analyzed)

        Returns:
            성공 여부
        """
        # 갱신용 엔드포인트 템플릿에 event_id 적용
        update_endpoint = self.update_endpoint_template.format(event_id=event_id)
        
        # 새로운 API 스펙에 맞게 payload 구성 (업데이트할 값만 포함)
        payload = {}

        # risk (위험도)
        if "risk" in detail_result and detail_result["risk"] is not None:
            payload["risk"] = detail_result["risk"].lower()

        # type (이벤트 유형)
        if "type" in detail_result and detail_result["type"] is not None:
            payload["type"] = detail_result["type"].lower()

        # summary (AI 분석 요약)
        if "summary" in detail_result and detail_result["summary"] is not None:
            payload["summary"] = detail_result["summary"]

        # report (상세 보고서 내용)
        if "report" in detail_result and detail_result["report"] is not None:
            payload["report"] = detail_result["report"]

        # status (상태)
        if "status" in detail_result and detail_result["status"] is not None:
            payload["status"] = detail_result["status"]

        if not payload:
            self.logger.warning(f"백엔드로 갱신할 데이터가 없습니다. (Event ID: {event_id})")
            return True

        for attempt in range(self.max_retries):
            try:
                response = requests.patch(
                    update_endpoint,
                    json=payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                
                self.logger.info(f"[백엔드 갱신 성공] Event ID: {event_id}, 갱신 필드: {list(payload.keys())}")
                return True

            except Exception as e:
                self.logger.warning(f"❌ [백엔드 갱신 실패] Event ID {event_id}: {e}, 시도: {attempt + 1}/{self.max_retries}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)

        return False

    def get_clip_upload_url(self, event_id: str) -> Optional[str]:
        """
        클립 업로드용 presigned URL 요청
        GET /internal/agent/events/{event_id}/clip/upload-url

        Returns:
            presigned PUT URL 또는 None
        """
        endpoint = self.clip_endpoint_template.format(event_id=event_id) + "/upload-url"

        try:
            response = requests.get(endpoint, timeout=self.timeout)
            response.raise_for_status()

            data = response.json()
            upload_url = data.get("uploadUrl")
            self.logger.debug(f"[업로드 URL 획득] Event ID: {event_id}")
            return upload_url

        except Exception as e:
            self.logger.error(f"❌ [업로드 URL 요청 실패] {event_id}: {e}")
            return None

    def upload_clip(self, upload_url: str, file_data: bytes) -> bool:
        """
        presigned URL로 클립 직접 업로드 (S3/MinIO)

        Args:
            upload_url: presigned PUT URL
            file_data: MP4 바이너리 데이터

        Returns:
            성공 여부
        """
        try:
            response = requests.put(
                upload_url,
                data=file_data,
                headers={"Content-Type": "video/mp4"},
                timeout=60  # 업로드는 시간이 더 걸릴 수 있음
            )
            response.raise_for_status()

            self.logger.info(f"✅ [클립 업로드 성공] {len(file_data)} bytes")
            return True

        except Exception as e:
            self.logger.error(f"❌ [클립 업로드 실패]: {e}")
            return False

    def confirm_event_clip(self, event_id: str) -> bool:
        """
        클립 업로드 완료 확인
        POST /internal/agent/events/{event_id}/clip/confirm

        Args:
            event_id: 이벤트 ID

        Returns:
            성공 여부
        """
        endpoint = self.clip_endpoint_template.format(event_id=event_id) + "/confirm"

        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    endpoint,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                
                self.logger.info(f"✅ [클립 확정 성공] Event ID: {event_id}")
                return True

            except Exception as e:
                self.logger.warning(f"❌ [클립 확정 실패] {event_id}: {e}, 시도 {attempt + 1}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)

        return False


    # =========================================
    # Human-in-the-Loop 승인 관련 API
    # =========================================
    #
    # [HITL 흐름]
    # 1. create_action(): Action 생성 → actionId 획득
    #    POST /internal/agent/events/{eventId}/actions
    #    Request:  { action, description }
    #    Response: { actionId }
    #
    # 2. confirm_action(): 승인 결과 대기 및 조회
    #    POST /internal/agent/events/{eventId}/actions/{actionId}/pending
    #    Request:  (없음)
    #    Response: { userId, userName, userMail, result }
    #
    # [액션 코드]
    # - 112_POLICE: 경찰 신고
    # - 119_FIRE: 소방/응급 신고
    # - SECURITY_TEAM: 내부 보안팀 호출
    # - MANAGEMENT: 관리사무소 연락
    # =========================================
    def create_action(
        self,
        event_id: str,
        action: str,
        description: str,
    ) -> Optional[str]:
        """
        Action을 생성하고 actionId를 받습니다.

        [API 엔드포인트]
        POST /internal/agent/events/{eventId}/actions

        [Request Body]
        {
            "action": "112_POLICE",      # 액션 코드
            "description": "긴급 신고 요청..."  # 설명
        }

        [Response Body]
        {
            "actionId": "uuid"           # 생성된 action ID
        }

        Args:
            event_id: 이벤트 ID
            action: 액션 코드 (예: "112_POLICE", "119_FIRE")
            description: 액션 설명

        Returns:
            생성된 actionId 또는 None (실패 시)
        """
        # config에서 관리되는 엔드포인트 템플릿 사용
        endpoint = self.action_create_endpoint_template.format(event_id=event_id)

        payload = {
            "action": action,
            "description": description,
        }

        try:
            self.logger.info(f"[HITL] Action 생성 요청: {event_id} - {action}")

            response = requests.post(
                endpoint,
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()

            data = response.json()
            action_id = data.get("actionId")

            self.logger.info(f"[HITL] Action 생성 완료: {event_id} - actionId={action_id}")
            return action_id

        except Timeout:
            self.logger.warning(f"⏱️ [HITL] Action 생성 타임아웃: {event_id}")
            return None

        except RequestException as e:
            self.logger.error(f"❌ [HITL] Action 생성 실패: {event_id} - {e}")
            return None

        except Exception as e:
            self.logger.error(f"💥 [HITL] Action 생성 예외: {event_id} - {e}", exc_info=True)
            return None

    def confirm_action(
        self,
        event_id: str,
        action_id: str,
        timeout: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Action에 대한 Human-in-the-Loop 승인 결과를 조회합니다.

        백엔드에서 사용자 승인/거절이 완료될 때까지 대기하고,
        결과를 반환합니다.

        [API 엔드포인트]
        POST /internal/agent/events/{eventId}/actions/{actionId}/pending

        [Request Body]
        (없음)

        [Response Body]
        {
            "userId": "uuid",        # 승인/거절한 사용자 ID
            "userName": "홍길동",     # 사용자 이름
            "userMail": "a@b.com",   # 사용자 이메일
            "result": true/false     # 승인 여부
        }

        Args:
            event_id: 이벤트 ID
            action_id: 승인 요청할 action ID
            timeout: 요청 타임아웃 (초, None이면 기본값 사용)

        Returns:
            백엔드 응답 딕셔너리 또는 None (실패 시)
        """
        # config에서 관리되는 엔드포인트 템플릿 사용
        endpoint = self.action_confirm_endpoint_template.format(
            event_id=event_id, action_id=action_id
        )

        # HITL 승인은 사용자 응답을 기다려야 하므로 타임아웃을 길게 설정
        # 기본값: 없음 (무한 대기) 또는 설정된 값 사용
        request_timeout = timeout if timeout else None  # None = 무한 대기

        try:
            self.logger.info(f"[HITL] 승인 확인 요청: {event_id} - actionId={action_id}")

            response = requests.post(
                endpoint,
                timeout=request_timeout,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()

            data = response.json()
            self.logger.info(f"[HITL] 승인 확인 응답: {event_id} - result={data.get('result')}")

            return data

        except Timeout:
            self.logger.warning(f"⏱️ [HITL] 승인 확인 타임아웃: {event_id}")
            return None

        except RequestException as e:
            self.logger.error(f"❌ [HITL] 승인 확인 실패: {event_id} - {e}")
            return None

        except Exception as e:
            self.logger.error(f"💥 [HITL] 승인 확인 예외: {event_id} - {e}", exc_info=True)
            return None

    def update_action(
        self,
        event_id: str,
        action_id: str,
        action: str,
        description: str,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Action 정보를 백엔드에 갱신합니다.

        도구 실행이 완료된 후, 최종 결과를 백엔드에 업데이트합니다.
        emergency_call 도구 실행 후 호출됩니다.

        [API 엔드포인트]
        PATCH /internal/agent/events/{eventId}/actions/{actionId}

        [Request Body]
        {
            "userId": "uuid",        # (optional) 승인/거절한 사용자 ID
            "action": "112_POLICE",  # 액션 코드
            "description": "..."     # 최종 설명 (도구 실행 결과 포함)
        }

        [Response Body]
        {
            "actionId": "uuid"       # 갱신된 action ID
        }

        Args:
            event_id: 이벤트 ID
            action_id: 갱신할 action ID
            action: 액션 코드 (예: "112_POLICE", "REJECTED_112_POLICE")
            description: 최종 설명 (도구 실행 결과 포함)
            user_id: 승인/거절한 사용자 ID (optional)

        Returns:
            갱신된 actionId 또는 None (실패 시)
        """
        # config에서 관리되는 엔드포인트 템플릿 사용
        endpoint = self.action_update_endpoint_template.format(
            event_id=event_id, action_id=action_id
        )

        # Request Body 구성 (userId는 optional)
        payload = {
            "action": action,
            "description": description,
        }
        if user_id:
            payload["userId"] = user_id

        try:
            self.logger.info(f"[HITL] Action 갱신 요청: {event_id} - actionId={action_id}")

            response = requests.patch(
                endpoint,
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()

            data = response.json()
            updated_action_id = data.get("actionId")

            self.logger.info(f"[HITL] Action 갱신 완료: {event_id} - actionId={updated_action_id}")
            return updated_action_id

        except Timeout:
            self.logger.warning(f"⏱️ [HITL] Action 갱신 타임아웃: {event_id}")
            return None

        except RequestException as e:
            self.logger.error(f"❌ [HITL] Action 갱신 실패: {event_id} - {e}")
            return None

        except Exception as e:
            self.logger.error(f"💥 [HITL] Action 갱신 예외: {event_id} - {e}", exc_info=True)
            return None
