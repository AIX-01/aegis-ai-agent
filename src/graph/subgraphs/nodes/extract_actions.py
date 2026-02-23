"""
조치 정보 추출 노드 (extract_actions)

메시지에서 결정된 조치들과 참조 문서를 추출합니다.
LLM 응답에서 판단 근거(reasoning)와 조치별 이유(reason)를 파싱합니다.
emergency_call 도구 실행 후 백엔드에 update_action API를 호출합니다.
"""
import re
import logging
from typing import Dict, Any, List, TYPE_CHECKING

from langchain_core.messages import ToolMessage, AIMessage

if TYPE_CHECKING:
    from ....config import Config
    from ..state import ResponseAgentState

logger = logging.getLogger(__name__)

# agency_type을 action 코드로 변환하는 매핑
# (response_tools.py의 emergency_call 도구에서 사용하는 코드와 일치)
AGENCY_TO_ACTION = {
    "경찰청 112": "112_POLICE",
    "소방청 119": "119_FIRE",
    "내부 보안팀": "SECURITY_TEAM",
    "관리사무소": "MANAGEMENT",
}


def extract_actions(state: "ResponseAgentState", config: "Config") -> Dict[str, Any]:
    """
    메시지에서 결정된 조치들, 참조 문서, LLM 판단 근거를 추출합니다.
    emergency_call 도구 실행 후 백엔드에 update_action API를 호출합니다.

    [추출 정보 - 백엔드 event_actions 테이블과 일치]
    - action: TEXT - 조치 유형/코드 ("BROADCAST", "112_POLICE" 등)
    - description: TEXT - 조치에 대한 상세 설명
    - reason: TEXT - LLM이 해당 조치를 선택한 이유
    - user_id: UUID | None - HITL 승인자 ID (시스템 자동 시 None)

    [추출 정보 - 보고서용]
    - reasoning: LLM 전체 판단 근거 (과거 사례 분석, 법적 근거, 판단 근거)

    [액션 코드 매핑]
    - field_action: BROADCAST, LIGHT_ON, PTZ_TRACK, SIREN
    - emergency_call (승인): 112_POLICE, 119_FIRE, SECURITY_TEAM, MANAGEMENT
    - emergency_call (거절): REJECTED_112_POLICE, REJECTED_119_FIRE, ...

    [백엔드 갱신]
    - emergency_call 도구 실행 후 PATCH /internal/agent/events/{eventId}/actions/{actionId} 호출

    Args:
        state: 현재 에이전트 상태
        config: 시스템 설정

    Returns:
        업데이트된 상태 (actions, rag_references, reasoning)
    """
    from ....clients.backend_client import BackendClient

    actions = []
    rag_references = []
    reasoning = ""
    action_reasons = {}  # LLM이 응답한 조치별 이유 {"조치명": "이유"}

    # Human-in-the-Loop 승인 정보 확인
    approval_result = state.get("approval_result", {})
    approval_user_id = approval_result.get("user_id")
    approval_user_name = approval_result.get("user_name")
    approval_user_mail = approval_result.get("user_mail")
    approval_action_id = approval_result.get("action_id")

    # 이벤트 ID (백엔드 갱신에 필요)
    event_id = state.get("event_id", "")

    # 1단계: LLM 응답(AIMessage)에서 판단 근거와 조치 이유 추출
    for message in state.get("messages", []):
        if isinstance(message, AIMessage) and message.content:
            # 전체 판단 근거 추출
            extracted_reasoning = _extract_reasoning(message.content)
            if extracted_reasoning:
                reasoning = extracted_reasoning

            # 조치별 이유 추출 (### 선택한 조치 섹션에서)
            extracted_reasons = _extract_action_reasons(message.content)
            if extracted_reasons:
                action_reasons.update(extracted_reasons)

    # 2단계: 도구 실행 결과(ToolMessage)에서 actions 추출
    for message in state.get("messages", []):
        if isinstance(message, ToolMessage):
            content = message.content

            # search_protocol_and_cases 결과 → rag_references
            if "대응 매뉴얼" in content or "과거 유사 사례" in content:
                rag_references.append({
                    "type": "protocol_and_cases",
                    "content": content[:1000]
                })

            # execute_field_action 결과 → actions
            elif "현장 조치 실행 결과" in content:
                camera_location = state.get("camera_location", "")
                camera_name = state.get("camera_name", "")
                action_data = _extract_field_action(content, action_reasons, camera_location, camera_name)
                if action_data:
                    actions.append(action_data)

            # emergency_call 결과 → actions + 백엔드 갱신
            elif "긴급 신고 접수 결과" in content:
                action_data = _extract_emergency_call_approved(
                    content, approval_user_id, approval_user_name, approval_user_mail, action_reasons
                )
                if action_data:
                    actions.append(action_data)
                    _update_backend_action(
                        config, event_id, approval_action_id,
                        action_data["action"], action_data["description"], approval_user_id
                    )

            # emergency_call 거절 결과 → actions + 백엔드 갱신
            elif "긴급 신고가 사용자에 의해 거부되었습니다" in content:
                action_data = _extract_emergency_call_rejected(
                    state, approval_user_id, approval_user_name, approval_user_mail
                )
                if action_data:
                    actions.append(action_data)
                    _update_backend_action(
                        config, event_id, approval_action_id,
                        action_data["action"], action_data["description"], approval_user_id
                    )

            # emergency_call 타임아웃 결과 → actions + 백엔드 갱신
            elif "긴급 신고가 타임아웃되었습니다" in content:
                action_data = _extract_emergency_call_timeout(state)
                if action_data:
                    actions.append(action_data)
                    _update_backend_action(
                        config, event_id, approval_action_id,
                        action_data["action"], action_data["description"], None
                    )

    return {"actions": actions, "rag_references": rag_references, "reasoning": reasoning}


def _extract_reasoning(content: str) -> str:
    """
    LLM 응답에서 전체 판단 근거를 추출합니다.

    [추출 대상]
    - ### 과거 사례 분석
    - ### 법적 근거
    - ### 판단 근거

    Args:
        content: LLM 응답 텍스트

    Returns:
        추출된 판단 근거 텍스트 (없으면 빈 문자열)
    """
    if not content:
        return ""

    reasoning_parts = []

    # 과거 사례 분석 추출
    case_match = re.search(r"### 과거 사례 분석\s*\n(.*?)(?=###|\Z)", content, re.DOTALL)
    if case_match:
        reasoning_parts.append(f"[과거 사례 분석]\n{case_match.group(1).strip()}")

    # 법적 근거 추출
    legal_match = re.search(r"### 법적 근거\s*\n(.*?)(?=###|\Z)", content, re.DOTALL)
    if legal_match:
        reasoning_parts.append(f"[법적 근거]\n{legal_match.group(1).strip()}")

    # 판단 근거 추출
    decision_match = re.search(r"### 판단 근거\s*\n(.*?)(?=###|\Z)", content, re.DOTALL)
    if decision_match:
        reasoning_parts.append(f"[판단 근거]\n{decision_match.group(1).strip()}")

    return "\n\n".join(reasoning_parts)


def _extract_action_reasons(content: str) -> Dict[str, str]:
    """
    LLM 응답에서 '### 선택한 조치' 섹션의 조치별 상세 판단 근거를 추출합니다.

    [추출 형식]
    ### 선택한 조치
    1. 현장 방송 경고 - 무단투기 중단 및 경고 메시지 전달
    2. 112 신고 - 폭행 현행범 신고 및 가해자 검거 요청

    [판단 근거 포함 시]
    ### 판단 근거, ### 법적 근거 등에서 관련 내용을 함께 추출하여
    더 상세한 reason을 생성합니다.

    Args:
        content: LLM 응답 텍스트

    Returns:
        {"현장 방송 경고": "상세 판단 근거", ...}
    """
    if not content:
        return {}

    reasons = {}

    # 1. ### 선택한 조치 섹션에서 기본 이유 추출
    actions_match = re.search(r"### 선택한 조치\s*\n(.*?)(?=###|\Z)", content, re.DOTALL)
    if actions_match:
        actions_text = actions_match.group(1)
        lines = actions_text.strip().split("\n")
        for line in lines:
            # "1. 현장 방송 경고 - 이유" 패턴
            match = re.match(r"^[\d\.\-\*]\s*(.+?)\s*-\s*(.+)$", line.strip())
            if match:
                action_name = match.group(1).strip()
                reason = match.group(2).strip()
                reasons[action_name] = reason

    # 2. ### 판단 근거 섹션에서 추가 상세 내용 추출
    decision_match = re.search(r"### 판단 근거\s*\n(.*?)(?=###|\Z)", content, re.DOTALL)
    decision_text = decision_match.group(1).strip() if decision_match else ""

    # 3. ### 과거 사례 분석 섹션에서 과거 사례 추출 (있을 때만)
    case_match = re.search(r"### 과거 사례 분석\s*\n(.*?)(?=###|\Z)", content, re.DOTALL)
    case_text = case_match.group(1).strip() if case_match else ""

    # 과거 사례가 실제로 있는지 확인 (유사 사례 0건이면 없는 것으로 처리)
    has_past_cases = case_text and "유사 사례" in case_text and "0건" not in case_text

    # 4. 각 액션에 대해 상세 판단 근거 조합
    for action_name, basic_reason in reasons.items():
        detailed_parts = [basic_reason]

        # 판단 근거에서 해당 액션 관련 내용 찾기
        if decision_text:
            action_keywords = _get_action_keywords(action_name)
            for keyword in action_keywords:
                for sentence in decision_text.split('.'):
                    if keyword in sentence:
                        sentence = sentence.strip()
                        if sentence and sentence not in detailed_parts:
                            detailed_parts.append(sentence)
                        break

        # 법적 근거 추가 (신고 관련 액션인 경우 - 템플릿 기반)
        if any(kw in action_name for kw in ["112", "119", "신고", "경찰", "소방"]):
            legal_basis = _get_legal_basis_template(action_name)
            if legal_basis:
                detailed_parts.append(legal_basis)

        # 과거 사례 참조 추가 (실제 과거 사례가 있을 때만)
        if has_past_cases:
            case_summary = re.search(r"과거 대응[^:]*:\s*([^\n]+)", case_text)
            if case_summary:
                detailed_parts.append(f"과거 사례 참조: {case_summary.group(1).strip()[:50]}")

        # 상세 판단 근거 조합 (최대 200자)
        detailed_reason = " | ".join(detailed_parts)
        if len(detailed_reason) > 200:
            detailed_reason = detailed_reason[:197] + "..."

        reasons[action_name] = detailed_reason

    return reasons


def _get_legal_basis_template(action_name: str) -> str:
    """
    액션별 법적 근거 템플릿을 반환합니다.

    Args:
        action_name: 액션명

    Returns:
        법적 근거 문자열 (해당 없으면 빈 문자열)
    """
    # 112 경찰 신고 관련
    if any(kw in action_name for kw in ["112", "경찰"]):
        return "법적 근거: 형법 제257조(상해), 제260조(폭행), 제329조(절도)"

    # 119 소방/응급 신고 관련
    if any(kw in action_name for kw in ["119", "소방", "응급"]):
        return "법적 근거: 응급의료에 관한 법률 제2조, 소방기본법 제16조"

    # 보안팀 호출 관련
    if any(kw in action_name for kw in ["보안팀", "보안"]):
        return "법적 근거: 경비업법 제2조, 개인정보보호법 제25조(영상정보처리기기)"

    return ""


def _get_action_keywords(action_name: str) -> list:
    """액션명에서 키워드 추출"""
    keywords = []
    if "방송" in action_name:
        keywords.extend(["방송", "경고", "전달"])
    if "112" in action_name or "경찰" in action_name:
        keywords.extend(["112", "경찰", "신고", "검거"])
    if "119" in action_name or "소방" in action_name or "응급" in action_name:
        keywords.extend(["119", "소방", "응급", "구급"])
    if "보안" in action_name:
        keywords.extend(["보안", "출동"])
    if "조명" in action_name:
        keywords.extend(["조명", "점등"])
    if "PTZ" in action_name or "추적" in action_name:
        keywords.extend(["PTZ", "추적"])
    if "사이렌" in action_name:
        keywords.extend(["사이렌", "경보"])
    return keywords


def _match_action_reason(action_code: str, action_reasons: Dict[str, str]) -> str:
    """
    action 코드에 해당하는 이유를 찾습니다.

    Args:
        action_code: 액션 코드 (BROADCAST, 112_POLICE 등)
        action_reasons: LLM에서 추출한 {"조치명": "이유"} 딕셔너리

    Returns:
        매칭된 이유 (없으면 빈 문자열)
    """
    # 액션 코드와 조치명 매핑
    code_to_keywords = {
        "BROADCAST": ["방송", "BROADCAST"],
        "LIGHT_ON": ["조명", "LIGHT"],
        "PTZ_TRACK": ["PTZ", "추적"],
        "SIREN": ["사이렌", "SIREN"],
        "112_POLICE": ["112", "경찰"],
        "119_FIRE": ["119", "소방", "응급"],
        "SECURITY_TEAM": ["보안팀", "보안"],
        "MANAGEMENT": ["관리사무소", "관리"],
    }

    keywords = code_to_keywords.get(action_code, [])

    for action_name, reason in action_reasons.items():
        for keyword in keywords:
            if keyword in action_name:
                return reason

    return ""


def _extract_field_action(content: str, action_reasons: Dict[str, str], camera_location: str = "", camera_name: str = "") -> Dict[str, Any]:
    """execute_field_action 결과에서 action 정보 추출"""
    # action 코드 추출 (BROADCAST, LIGHT_ON, PTZ_TRACK, SIREN)
    action_code = None
    action_match = re.search(r"- 액션:\s*(\w+)", content)
    if action_match:
        action_code = action_match.group(1)

    # 카메라 ID 추출
    camera_match = re.search(r"- 대상 카메라:\s*(.+)", content)
    camera_id = camera_match.group(1).strip() if camera_match else ""

    # 방송 메시지 추출 (BROADCAST인 경우)
    message_match = re.search(r'- 방송 내용:\s*"(.+)"', content)
    broadcast_msg = message_match.group(1) if message_match else ""

    # 실행 시각 추출
    time_match = re.search(r"- 실행 시각:\s*(.+)", content)
    triggered_at = time_match.group(1).strip() if time_match else ""

    # LLM이 응답한 조치 이유 찾기
    reason = _match_action_reason(action_code, action_reasons) if action_code else ""

    # description 조립 (camera_location 우선, camera_name 2순위, camera_id 3순위)
    camera_display = camera_location or camera_name or camera_id
    if action_code == "BROADCAST" and broadcast_msg:
        description = f"카메라 {camera_display}에서 방송 실행: \"{broadcast_msg}\""
    else:
        description = f"카메라 {camera_display}에서 {action_code} 조치 실행"

    return {
        "action": action_code,
        "description": description,
        "reason": reason,  # LLM 판단 이유 추가
        "user_id": None
    }


def _extract_emergency_call_approved(
    content: str,
    user_id: str,
    user_name: str,
    user_mail: str,
    action_reasons: Dict[str, str]
) -> Dict[str, Any]:
    """emergency_call 승인 결과에서 action 정보 추출"""
    # agency 추출 후 action 코드로 변환
    action_code = None
    agency_name = ""
    agency_match = re.search(r"- 신고 기관:\s*(.+)", content)
    if agency_match:
        agency_name = agency_match.group(1).strip()
        action_code = AGENCY_TO_ACTION.get(agency_name, agency_name)

    # 접수 번호 추출
    receipt_match = re.search(r"- 접수 번호:\s*(.+)", content)
    receipt_no = receipt_match.group(1).strip() if receipt_match else ""

    # 접수 시각 추출
    time_match = re.search(r"- 접수 시각:\s*(.+)", content)
    triggered_at = time_match.group(1).strip() if time_match else ""

    # 전달 내용 요약 추출
    report_match = re.search(r"### 전달 내용\n(.+?)(?:\n###|\Z)", content, re.DOTALL)
    situation_summary = report_match.group(1).strip()[:100] if report_match else ""

    # 승인자 정보 조립
    approver_info = ""
    if user_name:
        approver_info = f"승인자: {user_name}"
        if user_mail:
            approver_info += f" ({user_mail})"

    # LLM이 응답한 조치 이유 찾기
    reason = _match_action_reason(action_code, action_reasons) if action_code else ""

    # description 조립
    description = f"{agency_name} 긴급 신고 접수"
    if situation_summary:
        description += f" - {situation_summary}"

    return {
        "action": action_code,
        "description": description,
        "reason": reason,  # LLM 판단 이유 추가
        "user_id": user_id
    }


def _extract_emergency_call_rejected(
    state: "ResponseAgentState",
    user_id: str,
    user_name: str,
    user_mail: str
) -> Dict[str, Any]:
    """emergency_call 거절 결과에서 action 정보 추출"""
    pending_approval = state.get("pending_approval", {})
    pending_agency_type = pending_approval.get("agency_type", "")

    action_code = f"REJECTED_{pending_agency_type}" if pending_agency_type else "REJECTED_EMERGENCY"

    # 거절자 정보 조립
    rejecter_info = ""
    if user_name:
        rejecter_info = f"거절자: {user_name}"
        if user_mail:
            rejecter_info += f" ({user_mail})"

    description = f"긴급 신고 요청이 사용자에 의해 거부됨"
    if rejecter_info:
        description += f" ({rejecter_info})"

    return {
        "action": action_code,
        "description": description,
        "reason": "사용자 거부",  # 거절 이유
        "user_id": user_id
    }


def _extract_emergency_call_timeout(state: "ResponseAgentState") -> Dict[str, Any]:
    """emergency_call 타임아웃 결과에서 action 정보 추출"""
    pending_approval = state.get("pending_approval", {})
    pending_agency_type = pending_approval.get("agency_type", "")

    action_code = f"TIMEOUT_{pending_agency_type}" if pending_agency_type else "TIMEOUT_EMERGENCY"
    description = f"긴급 신고 요청에 대한 응답 타임아웃"

    return {
        "action": action_code,
        "description": description,
        "reason": "응답 타임아웃",  # 타임아웃 이유
        "user_id": None
    }


def _update_backend_action(
    config: "Config",
    event_id: str,
    action_id: str,
    action: str,
    description: str,
    user_id: str
) -> None:
    """백엔드에 action 정보 갱신"""
    if not action_id or not event_id:
        return

    try:
        from ....clients.backend_client import BackendClient
        backend_client = BackendClient(config)
        backend_client.update_action(
            event_id=event_id,
            action_id=action_id,
            action=action,
            description=description,
            user_id=user_id,
        )
        logger.info(f"[{event_id}] action 결과 백엔드 갱신 완료 (actionId: {action_id})")
    except Exception as e:
        logger.error(f"[{event_id}] action 결과 백엔드 갱신 실패: {e}")

