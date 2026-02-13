"""
보고서 생성 노드 (generate_report)

최종 보고서를 생성합니다.
templates/reports/report_template.html 템플릿을 로드하여
{{변수명}} 플레이스홀더를 실제 데이터로 치환합니다.
"""
import base64
import logging
import os
from datetime import datetime
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ....config import Config
    from ..state import ResponseAgentState

logger = logging.getLogger(__name__)


def generate_report_node(state: "ResponseAgentState", app_config: "Config") -> Dict[str, Any]:
    """
    최종 보고서를 생성합니다.

    templates/reports/report_template.html 템플릿을 로드하여
    {{변수명}} 플레이스홀더를 실제 데이터로 치환한 후
    백엔드 API (PATCH /internal/agent/events/{eventId})의 report 필드로 전달됩니다.

    Args:
        state: 현재 에이전트 상태
        app_config: 시스템 설정

    Returns:
        업데이트된 상태 (report: HTML 보고서 문자열)
    """
    # 상태에서 필요한 정보 추출
    camera_name = state.get("camera_name", "")
    camera_location = state.get("camera_location", "")
    event_type = state.get("event_type", "")
    risk_level = state.get("risk_level", "")
    summary = state.get("summary", "")
    occurred_at = state.get("occurred_at", "")
    actions = state.get("actions", [])
    frames = state.get("frames", [])
    frame_timestamps = state.get("frame_timestamps", [])
    event_id = state.get("event_id", "")

    # 이벤트 유형 한글 변환
    event_type_korean = _get_event_type_korean(event_type)

    # 대응 조치 HTML 생성 (action + description + reason 포함)
    actions_html = _generate_actions_html(actions)

    # 프레임 HTML 생성
    frames_html = _generate_frames_html(frames, frame_timestamps)

    # 현재 시각
    generated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 템플릿 파일 로드
    template_html = _load_template(app_config)

    if not template_html:
        logger.error(f"[{event_id}] 템플릿 로드 실패, 기본 보고서 생성")
        return {"report": f"<html><body><h1>보고서 생성 실패</h1><p>Event ID: {event_id}</p></body></html>"}

    # {{변수명}} 플레이스홀더 치환
    report_html = template_html.replace("{{event_id}}", str(event_id))
    report_html = report_html.replace("{{occurred_at}}", str(occurred_at))
    report_html = report_html.replace("{{event_type}}", str(event_type))
    report_html = report_html.replace("{{event_type_korean}}", event_type_korean)
    report_html = report_html.replace("{{camera_name}}", str(camera_name))
    report_html = report_html.replace("{{camera_location}}", str(camera_location))
    report_html = report_html.replace("{{risk_level}}", str(risk_level))
    report_html = report_html.replace("{{summary}}", str(summary) if summary else "상황 요약 정보가 없습니다.")
    report_html = report_html.replace("{{frames}}", frames_html)
    report_html = report_html.replace("{{actions}}", actions_html)
    report_html = report_html.replace("{{generated_at}}", generated_at)
    report_html = report_html.replace("{{status_text}}", "분석 완료")
    report_html = report_html.replace("{{version}}", "1.0.0")

    logger.info(f"[{event_id}] HTML 보고서 생성 완료: {len(report_html)} 자")

    # HTML 보고서를 반환 (백엔드 API의 report 필드로 전달됨)
    return {"report": report_html}


def _load_template(app_config: "Config") -> str:
    """
    HTML 템플릿 파일을 로드합니다.

    Args:
        app_config: 시스템 설정 (report_template_dir 포함)

    Returns:
        템플릿 HTML 문자열, 실패 시 빈 문자열
    """
    template_path = ""
    try:
        # 프로젝트 루트 경로 계산 (src/graph/subgraphs/nodes/ → 프로젝트 루트)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_dir))))

        # 템플릿 경로 구성
        template_dir = getattr(app_config, 'report_template_dir', 'templates/reports')
        template_path = os.path.join(project_root, template_dir, "report_template.html")

        logger.debug(f"템플릿 경로: {template_path}")

        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()

    except FileNotFoundError:
        logger.error(f"템플릿 파일을 찾을 수 없습니다: {template_path}")
        return ""
    except Exception as e:
        logger.error(f"템플릿 로드 중 오류: {e}")
        return ""



def _get_event_type_korean(event_type: str) -> str:
    """
    이벤트 유형을 한글로 변환합니다.

    Args:
        event_type: 이벤트 유형 (ASSAULT, BURGLARY 등)

    Returns:
        한글 이벤트 유형
    """
    type_map = {
        "ASSAULT": "폭행",
        "BURGLARY": "절도/침입",
        "DUMP": "무단투기",
        "SWOON": "실신/쓰러짐",
        "VANDALISM": "기물파손",
    }
    return type_map.get(event_type.upper() if event_type else "", event_type)


def _generate_actions_html(actions: list) -> str:
    """
    대응 조치 목록을 HTML로 변환합니다.

    형식:
        [조치명]
        [description]
        💡 이유: [reason]

    Args:
        actions: 대응 조치 리스트
            [{"action": str, "description": str, "reason": str, "user_id": str|None}, ...]

    Returns:
        HTML 문자열 (action-item 형태)
    """
    if not actions:
        return '<div class="no-actions">결정된 조치 없음</div>'

    items_html = ""
    for i, action in enumerate(actions, 1):
        if isinstance(action, dict):
            action_code = action.get('action', '')
            description = action.get('description', '조치 내용 없음')
            reason = action.get('reason', '')

            # 액션 코드를 한글로 변환
            action_korean = _get_action_korean(action_code)

            items_html += f'''<div class="action-item">
                <div class="action-header">{i}. {action_korean}</div>
                <div class="action-content">{description}</div>
                {f'<div class="action-content" style="color:#6b7280; margin-top:4px;">💡 이유: {reason}</div>' if reason else ''}
            </div>\n'''
        else:
            items_html += f'''<div class="action-item">
                <div class="action-header">{i}. 조치</div>
                <div class="action-content">{str(action)}</div>
            </div>\n'''

    return items_html


def _get_action_korean(action_code: str) -> str:
    """
    액션 코드를 한글로 변환합니다.

    Args:
        action_code: 액션 코드 (BROADCAST, 112_POLICE 등)

    Returns:
        한글 액션명
    """
    action_map = {
        "BROADCAST": "현장 방송",
        "LIGHT_ON": "조명 점등",
        "PTZ_TRACK": "PTZ 추적",
        "SIREN": "사이렌 작동",
        "112_POLICE": "112 경찰 신고",
        "119_FIRE": "119 소방/응급 신고",
        "SECURITY_TEAM": "보안팀 출동",
        "MANAGEMENT": "관리사무소 연락",
    }

    # REJECTED_ 또는 TIMEOUT_ 접두사 처리
    if action_code.startswith("REJECTED_"):
        base_code = action_code.replace("REJECTED_", "")
        base_korean = action_map.get(base_code, base_code)
        return f"❌ {base_korean} (거부됨)"
    elif action_code.startswith("TIMEOUT_"):
        base_code = action_code.replace("TIMEOUT_", "")
        base_korean = action_map.get(base_code, base_code)
        return f"⏱️ {base_korean} (타임아웃)"

    return action_map.get(action_code, action_code)


def _generate_frames_html(frames: list, frame_timestamps: list = None) -> str:
    """
    프레임 목록을 HTML로 변환합니다.
    base64 Data URL을 사용하여 브라우저에서 이미지를 직접 렌더링합니다.

    Args:
        frames: 프레임 리스트 (bytes 이미지)
        frame_timestamps: 각 프레임의 타임스탬프 리스트 (datetime 또는 문자열)

    Returns:
        HTML 문자열 (frames-grid 내 img 태그)
    """
    if not frames:
        return '<div class="no-frames">캡처된 프레임이 없습니다.</div>'

    if frame_timestamps is None:
        frame_timestamps = []

    html_parts = ['<div class="frames-grid">']
    for idx, frame in enumerate(frames[:8]):
        b64 = base64.b64encode(frame).decode('utf-8')

        # 타임스탬프 포맷팅 (연월일 시:분:초)
        if idx < len(frame_timestamps) and frame_timestamps[idx]:
            ts = frame_timestamps[idx]
            if hasattr(ts, 'strftime'):
                time_label = ts.strftime("%Y년 %m월 %d일 %H:%M:%S")
            else:
                time_label = str(ts)
        else:
            time_label = f"프레임 {idx + 1}"

        html_parts.append(
            f'<div class="frame-item">\n'
            f'  <img src="data:image/jpeg;base64,{b64}" alt="{time_label}" />\n'
            f'  <div class="frame-label">{time_label}</div>\n'
            f'</div>'
        )
    html_parts.append('</div>')
    return '\n'.join(html_parts)


