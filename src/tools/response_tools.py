"""
대응 조치(Response) 관련 LangChain 도구 모음

response_agent에서 사용하는 도구들을 정의합니다:
- execute_field_action: 현장 물리적 조치 실행 (방송, 조명, PTZ, 사이렌)
- emergency_call: 긴급 신고 접수 (112, 119, 보안팀)

[참고] search_protocol_and_cases는 search_knowledge 노드로 분리되어
response_agent 서브그래프에서 ReAct 루프 진입 전에 무조건 실행됩니다.
(파일 위치: src/graph/subgraphs/response_agent.py)

사용 예시:
    from src.tools.response_tools import create_response_tools
    from src.config import Config

    config = Config()
    tools = create_response_tools(config)

    # tools는 LangChain 도구 리스트로 반환됩니다.
    # [execute_field_action, emergency_call]
"""
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from langchain_core.tools import tool

if TYPE_CHECKING:
    from ..config import Config

logger = logging.getLogger(__name__)


def create_response_tools(config: "Config"):
    """
    대응 에이전트가 사용할 도구들을 생성합니다.

    [참고] search_protocol_and_cases는 search_knowledge 노드로 분리되어
    ReAct 루프 진입 전에 무조건 실행됩니다. 따라서 도구 목록에서 제외됩니다.

    Args:
        config: Config 인스턴스 (Qdrant, OpenAI 설정 포함)

    Returns:
        LangChain 도구 리스트 [execute_field_action, emergency_call]
    """

    # =========================================
    # [DEPRECATED] search_protocol_and_cases
    # =========================================
    # 이 도구는 search_knowledge 노드로 분리되었습니다.
    # 노드로 분리한 이유:
    # 1. LLM이 도구 호출을 건너뛸 수 있어 실행이 보장되지 않았음
    # 2. ReAct 루프의 iteration 제한(5회)으로 검색 없이 종료될 수 있었음
    # 3. 매뉴얼/과거 사례 검색은 대응 결정의 필수 전제 조건임
    #
    # 검색 로직은 src/graph/subgraphs/response_agent.py의
    # search_knowledge_node() 함수에서 처리됩니다.
    # =========================================

    @tool
    def execute_field_action(action_name: str, camera_id: str, message_content: str = None) -> str:
        """
        현장 대응 도구: CCTV 방송, 조명 제어, PTZ 추적 등 물리적인 조치를 취합니다.

        Args:
            action_name: 실행할 액션 (BROADCAST, LIGHT_ON, PTZ_TRACK, SIREN)
                - BROADCAST: CCTV 스피커로 음성 방송
                - LIGHT_ON: 현장 조명 점등
                - PTZ_TRACK: PTZ 카메라로 대상 추적
                - SIREN: 경고 사이렌 작동
            camera_id: 대상 카메라 ID
            message_content: 방송 메시지 (BROADCAST 시 필수)

        Returns:
            실행 성공 여부
        """
        logger.info(f"[Tool] execute_field_action 호출: action={action_name}, camera={camera_id}, message={message_content}")

        # =========================================
        # Mock 응답 - 실제 구현 시 장비 제어 API 호출
        # =========================================
        # 실제 환경에서는 VMS(Video Management System) 또는
        # IoT 장비 제어 API를 호출하여 물리적 조치를 수행합니다.
        # =========================================
        mock_response = f"""## 현장 조치 실행 결과

- 액션: {action_name}
- 대상 카메라: {camera_id}
- 실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 상태: ✅ 성공

{f'- 방송 내용: "{message_content}"' if message_content else ''}
"""
        return mock_response

    @tool
    def emergency_call(agency_type: str, situation_report: str) -> str:
        """
        긴급 전파 도구: 112, 119 또는 유관 부서에 시스템적으로 신고를 접수합니다.

        Args:
            agency_type: 신고 기관 (112_POLICE, 119_FIRE, SECURITY_TEAM, MANAGEMENT)
                - 112_POLICE: 경찰 신고
                - 119_FIRE: 소방/응급 신고
                - SECURITY_TEAM: 내부 보안팀 호출
                - MANAGEMENT: 관리사무소 연락
            situation_report: 상황 보고 내용 (신고 시 전달할 내용)

        Returns:
            신고 접수 결과
        """
        logger.info(f"[Tool] emergency_call 호출: agency={agency_type}, report={situation_report[:50]}...")

        # =========================================
        # Mock 응답 - 실제 구현 시 신고 API 연동
        # =========================================
        # 실제 환경에서는 각 기관별 API 또는
        # 통합 신고 시스템과 연동하여 신고를 접수합니다.
        # =========================================
        agency_names = {
            "112_POLICE": "경찰청 112",
            "119_FIRE": "소방청 119",
            "SECURITY_TEAM": "내부 보안팀",
            "MANAGEMENT": "관리사무소"
        }

        mock_response = f"""## 긴급 신고 접수 결과

- 신고 기관: {agency_names.get(agency_type, agency_type)}
- 접수 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 접수 번호: EMG-{datetime.now().strftime('%Y%m%d%H%M%S')}
- 상태: ✅ 접수 완료

### 전달 내용
{situation_report}

### 예상 대응
- 담당자 배정 중
- 예상 도착 시간: 5-10분
"""
        return mock_response

    # =========================================
    # 생성된 도구 리스트 반환
    # =========================================
    # search_protocol_and_cases는 노드로 분리되어 제외됨
    return [execute_field_action, emergency_call]

