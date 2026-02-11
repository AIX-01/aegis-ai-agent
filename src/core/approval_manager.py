"""
Human-in-the-Loop 승인 관리자

emergency_call 도구 실행 전에 사용자 승인을 받기 위한 관리자입니다.
SSE로 프론트엔드 모달에 승인 요청을 보내고, REST API로 응답을 받습니다.

[워크플로우]
1. LLM이 emergency_call 도구 호출을 결정
2. ApprovalManager.request_approval() 호출 - 승인 요청 생성
3. SSE로 프론트엔드에 승인 요청 전송 → 모달 표시
4. 사용자가 모달에서 승인/거부 버튼 클릭
5. POST /api/approval/{request_id} → ApprovalManager.set_approval_result() 호출
6. 승인 시: emergency_call 실행 / 거부 시: 스킵

[통신 방식]
- 승인 요청 전송: SSE (서버 → 클라이언트, 단방향)
- 승인/거부 응답: REST API (클라이언트 → 서버)

[사용 예시]
    from src.core.approval_manager import approval_manager

    # 승인 요청 생성 (SSE로 프론트엔드에 자동 전송)
    request_id = approval_manager.request_approval(
        event_id="abc-123",
        camera_id="cam-001",
        action_type="emergency_call",
        action_detail={"agency_type": "112_POLICE", "situation_report": "..."},
    )

    # 승인 대기 (타임아웃 60초)
    result = approval_manager.wait_for_approval(request_id, timeout=60)

    # result: {"approved": True/False, "status": "approved"/"rejected"/"timeout"}
"""
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Any, List, Callable
from enum import Enum

logger = logging.getLogger(__name__)


class ApprovalStatus(Enum):
    """승인 요청 상태"""
    PENDING = "pending"      # 대기 중 (사용자 응답 전)
    APPROVED = "approved"    # 승인됨
    REJECTED = "rejected"    # 거부됨
    TIMEOUT = "timeout"      # 타임아웃 (사용자 미응답)
    CANCELLED = "cancelled"  # 취소됨 (시스템에서 취소)


@dataclass
class ApprovalRequest:
    """
    승인 요청 데이터 클래스

    프론트엔드 모달에 표시할 승인 요청 정보를 담습니다.
    """
    # 요청 식별 정보
    request_id: str                          # 승인 요청 고유 ID
    event_id: str                            # 관련 이벤트 ID
    camera_id: str                           # 카메라 ID
    camera_name: str = ""                    # 카메라 이름 (표시용)
    camera_location: str = ""                # 카메라 위치 (표시용)

    # 액션 정보
    action_type: str = ""                    # "emergency_call"
    action_detail: Dict[str, Any] = field(default_factory=dict)  # 도구 호출 파라미터

    # 상태 정보
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    responded_at: Optional[datetime] = None
    responded_by: Optional[str] = None       # 응답한 사용자 ID

    # 동기화 (스레드 대기용)
    event: threading.Event = field(default_factory=threading.Event)

    def to_dict(self) -> Dict[str, Any]:
        """
        프론트엔드 모달에 전송할 딕셔너리로 변환

        Returns:
            승인 요청 정보 딕셔너리
        """
        # 신고 기관명 매핑
        agency_names = {
            "112_POLICE": "경찰청 112",
            "119_FIRE": "소방청 119",
            "SECURITY_TEAM": "내부 보안팀",
            "MANAGEMENT": "관리사무소",
        }

        agency_type = self.action_detail.get("agency_type", "")
        agency_name = agency_names.get(agency_type, agency_type)

        return {
            "request_id": self.request_id,
            "event_id": self.event_id,
            "camera_id": self.camera_id,
            "camera_name": self.camera_name,
            "camera_location": self.camera_location,
            "action_type": self.action_type,
            "action_detail": self.action_detail,
            "agency_name": agency_name,  # 모달 표시용
            "situation_report": self.action_detail.get("situation_report", ""),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
        }


class ApprovalManager:
    """
    Human-in-the-Loop 승인 관리자 (싱글톤)

    emergency_call 도구 실행 전에 사용자 승인을 받기 위한 중앙 관리자입니다.
    SSE를 통해 프론트엔드 모달에 승인 요청을 전송하고,
    REST API를 통해 승인/거부 응답을 수신합니다.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """싱글톤 패턴으로 인스턴스 생성"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """ApprovalManager 초기화"""
        if self._initialized:
            return

        self._initialized = True
        self._requests: Dict[str, ApprovalRequest] = {}  # request_id -> ApprovalRequest
        self._event_requests: Dict[str, List[str]] = {}  # event_id -> [request_ids]
        self._lock = threading.Lock()

        # SSE 전송 콜백 (app.py에서 설정)
        # 형태: def callback(event_type: str, data: dict) -> None
        self._sse_callback: Optional[Callable[[str, dict], None]] = None

        logger.info("[ApprovalManager] 초기화 완료")

    def set_sse_callback(self, callback: Callable[[str, dict], None]):
        """
        SSE 전송 콜백 설정

        Args:
            callback: SSE 이벤트 전송 함수
                      def callback(event_type: str, data: dict) -> None
        """
        self._sse_callback = callback
        logger.info("[ApprovalManager] SSE 콜백 설정 완료")

    def request_approval(
        self,
        event_id: str,
        camera_id: str,
        action_type: str,
        action_detail: Dict[str, Any],
        camera_name: str = "",
        camera_location: str = "",
    ) -> str:
        """
        승인 요청 생성 및 SSE로 프론트엔드에 전송

        Args:
            event_id: 이벤트 ID
            camera_id: 카메라 ID
            action_type: 액션 유형 ("emergency_call")
            action_detail: 도구 호출 파라미터 (agency_type, situation_report 등)
            camera_name: 카메라 이름 (모달 표시용)
            camera_location: 카메라 위치 (모달 표시용)

        Returns:
            승인 요청 ID (request_id)
        """
        request_id = str(uuid.uuid4())

        request = ApprovalRequest(
            request_id=request_id,
            event_id=event_id,
            camera_id=camera_id,
            camera_name=camera_name,
            camera_location=camera_location,
            action_type=action_type,
            action_detail=action_detail,
        )

        with self._lock:
            self._requests[request_id] = request

            # event_id별 요청 목록 관리
            if event_id not in self._event_requests:
                self._event_requests[event_id] = []
            self._event_requests[event_id].append(request_id)

        logger.info(f"[ApprovalManager] 승인 요청 생성: {request_id} (event: {event_id}, action: {action_type})")

        # SSE로 프론트엔드 모달에 승인 요청 전송
        self._send_approval_request_via_sse(request)

        return request_id

    def _send_approval_request_via_sse(self, request: ApprovalRequest):
        """
        SSE를 통해 프론트엔드 모달에 승인 요청 전송

        Args:
            request: 승인 요청 객체
        """
        if self._sse_callback is None:
            logger.warning("[ApprovalManager] SSE 콜백이 설정되지 않음 - 프론트엔드 알림 스킵")
            return

        try:
            # SSE 이벤트 전송 (event_type: "approval_request")
            self._sse_callback("approval_request", request.to_dict())
            logger.info(f"[ApprovalManager] SSE 전송 완료: {request.request_id}")
        except Exception as e:
            logger.error(f"[ApprovalManager] SSE 전송 실패: {e}")

    def wait_for_approval(self, request_id: str, timeout: float = 60.0) -> Dict[str, Any]:
        """
        승인 응답 대기 (REST API 응답이 올 때까지 블로킹)

        Args:
            request_id: 승인 요청 ID
            timeout: 대기 타임아웃 (초)

        Returns:
            승인 결과 딕셔너리:
            {
                "approved": True/False,
                "status": "approved"/"rejected"/"timeout",
                "responded_by": "user_id" or None,
                "responded_at": "ISO timestamp" or None,
            }
        """
        request = self._requests.get(request_id)

        if request is None:
            logger.error(f"[ApprovalManager] 존재하지 않는 요청 ID: {request_id}")
            return {"approved": False, "status": "not_found"}

        logger.info(f"[ApprovalManager] 승인 대기 시작: {request_id} (timeout: {timeout}s)")

        # 이벤트 대기 (사용자가 모달에서 버튼 클릭 또는 타임아웃)
        received = request.event.wait(timeout=timeout)

        if not received:
            # 타임아웃 - 사용자가 응답하지 않음
            with self._lock:
                request.status = ApprovalStatus.TIMEOUT
            logger.warning(f"[ApprovalManager] 승인 타임아웃: {request_id}")

            # 타임아웃 SSE 이벤트 전송 (모달 닫기용)
            if self._sse_callback:
                self._sse_callback("approval_timeout", {"request_id": request_id})

            return {"approved": False, "status": "timeout"}

        # 응답 결과 반환
        return {
            "approved": request.status == ApprovalStatus.APPROVED,
            "status": request.status.value,
            "responded_by": request.responded_by,
            "responded_at": request.responded_at.isoformat() if request.responded_at else None,
        }

    def set_approval_result(
        self,
        request_id: str,
        approved: bool,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        승인 결과 설정 (프론트엔드 REST API에서 호출)

        모달에서 사용자가 승인/거부 버튼을 클릭하면
        POST /api/approval/{request_id} 요청이 오고,
        이 메서드가 호출됩니다.

        Args:
            request_id: 승인 요청 ID
            approved: 승인 여부 (True: 승인, False: 거부)
            user_id: 응답한 사용자 ID

        Returns:
            성공 여부
        """
        request = self._requests.get(request_id)

        if request is None:
            logger.error(f"[ApprovalManager] 존재하지 않는 요청 ID: {request_id}")
            return False

        if request.status != ApprovalStatus.PENDING:
            logger.warning(f"[ApprovalManager] 이미 처리된 요청: {request_id} (status: {request.status})")
            return False

        with self._lock:
            request.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
            request.responded_at = datetime.now()
            request.responded_by = user_id

        # 대기 중인 스레드 깨우기 (wait_for_approval 해제)
        request.event.set()

        status_str = "승인" if approved else "거부"
        logger.info(f"[ApprovalManager] 승인 결과 설정: {request_id} → {status_str} (by: {user_id})")

        return True

    def get_pending_requests(self, event_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        대기 중인 승인 요청 목록 조회

        Args:
            event_id: 특정 이벤트의 요청만 조회 (None이면 전체)

        Returns:
            대기 중인 승인 요청 리스트
        """
        pending = []

        with self._lock:
            for req_id, request in self._requests.items():
                if request.status != ApprovalStatus.PENDING:
                    continue

                if event_id is not None and request.event_id != event_id:
                    continue

                pending.append(request.to_dict())

        return pending

    def get_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        """
        특정 승인 요청 조회

        Args:
            request_id: 승인 요청 ID

        Returns:
            승인 요청 정보 또는 None
        """
        request = self._requests.get(request_id)
        if request:
            return request.to_dict()
        return None

    def cancel_request(self, request_id: str) -> bool:
        """
        승인 요청 취소

        Args:
            request_id: 승인 요청 ID

        Returns:
            성공 여부
        """
        request = self._requests.get(request_id)

        if request is None:
            return False

        with self._lock:
            request.status = ApprovalStatus.CANCELLED

        # 대기 중인 스레드 깨우기
        request.event.set()

        logger.info(f"[ApprovalManager] 승인 요청 취소: {request_id}")
        return True

    def cleanup_old_requests(self, max_age_seconds: float = 300):
        """
        오래된 요청 정리 (메모리 관리)

        Args:
            max_age_seconds: 최대 보관 시간 (초, 기본 5분)
        """
        now = datetime.now()
        to_remove = []

        with self._lock:
            for req_id, request in self._requests.items():
                age = (now - request.created_at).total_seconds()
                # PENDING 상태가 아니고, max_age 초과한 요청 정리
                if age > max_age_seconds and request.status != ApprovalStatus.PENDING:
                    to_remove.append(req_id)

            for req_id in to_remove:
                del self._requests[req_id]
                # event_requests에서도 제거
                for event_id, req_ids in self._event_requests.items():
                    if req_id in req_ids:
                        req_ids.remove(req_id)

        if to_remove:
            logger.info(f"[ApprovalManager] 오래된 요청 {len(to_remove)}개 정리 완료")


# =========================================
# 싱글톤 인스턴스 (전역 접근용)
# =========================================
approval_manager = ApprovalManager()

