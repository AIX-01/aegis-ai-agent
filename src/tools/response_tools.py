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


# =========================================
# execute_field_action 실제 로직 (분리된 구현)
# =========================================
# skip_emergency_call_node에서도 호출 가능하도록 분리
# @tool 데코레이터 함수는 직접 호출이 어려우므로 로직을 별도 함수로 분리
def execute_field_action_impl(action_name: str, camera_id: str, message_content: str = None) -> str:
    """
    execute_field_action의 실제 구현 로직

    ToolNode의 @tool 함수와 skip_emergency_call_node에서 모두 호출됩니다.
    - @tool execute_field_action: 정상 흐름에서 ToolNode가 호출
    - skip_emergency_call_node: emergency_call 거부 시에도 execute_field_action은 실행해야 함

    Args:
        action_name: 실행할 액션 (BROADCAST, LIGHT_ON, PTZ_TRACK, SIREN)
        camera_id: 대상 카메라 ID
        message_content: 방송 메시지 (BROADCAST 시 필수)

    Returns:
        실행 결과 문자열
    """
    logger.info(f"[execute_field_action_impl] 호출: action={action_name}, camera={camera_id}, message={message_content}")

    # =========================================
    # Mock 응답 - 실제 구현 시 장비 제어 API 호출
    # =========================================
    # 실제 환경에서는 VMS(Video Management System) 또는
    # IoT 장비 제어 API를 호출하여 물리적 조치를 수행합니다.
    #
    # [LLM 참고용]
    # Mock 응답을 상세히 작성하면 LLM이 다음 행동 결정 시 참고합니다.
    # 예: "방송 완료 → 추가 조치 필요 여부 판단"
    # =========================================

    # 액션별 상세 응답 구성
    action_details = {
        "BROADCAST": {
            "description": "CCTV 스피커를 통한 음성 방송",
            "effect": "현장 인원에게 경고 메시지 전달 완료",
            "next_step": "대상자 반응 확인 필요, 반응 없을 시 추가 조치 고려",
            "coverage": "반경 50m 이내 청취 가능"
        },
        "LIGHT_ON": {
            "description": "현장 조명 점등",
            "effect": "해당 구역 조명 활성화 완료",
            "next_step": "야간 시인성 확보됨, CCTV 영상 품질 향상",
            "coverage": "해당 카메라 촬영 범위 전체"
        },
        "PTZ_TRACK": {
            "description": "PTZ 카메라 대상 추적 모드",
            "effect": "대상 자동 추적 시작",
            "next_step": "대상 이동 경로 기록 중, 도주 시 경로 추적 가능",
            "coverage": "카메라 회전 범위 내 자동 추적"
        },
        "SIREN": {
            "description": "경고 사이렌 작동",
            "effect": "경고음 발생 중 (90dB)",
            "next_step": "주변 인원 주의 환기됨, 30초 후 자동 종료",
            "coverage": "반경 100m 이내 청취 가능"
        }
    }

    action_info = action_details.get(action_name, {
        "description": f"{action_name} 실행",
        "effect": "조치 완료",
        "next_step": "상황 모니터링 필요",
        "coverage": "해당 카메라 범위"
    })

    result = f"""## 현장 조치 실행 결과

- 액션: {action_name}
- 설명: {action_info['description']}
- 대상 카메라: {camera_id}
- 실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 상태: ✅ 성공

### 실행 효과
- {action_info['effect']}
- 적용 범위: {action_info['coverage']}
{f'- 방송 내용: "{message_content}"' if message_content else ''}

### 권장 후속 조치
- {action_info['next_step']}
"""

    return result


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
        # 실제 로직은 execute_field_action_impl에서 처리
        # 분리된 이유: skip_emergency_call_node에서도 동일한 로직을 재사용하기 위함
        return execute_field_action_impl(action_name, camera_id, message_content)

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
        #
        # [LLM 참고용]
        # Mock 응답을 상세히 작성하면 LLM이 추가 조치 필요 여부를 판단합니다.
        # 예: "112 신고 완료 → 현장 보존 조치 필요"
        # =========================================

        # 기관별 상세 응답 구성
        agency_details = {
            "112_POLICE": {
                "name": "경찰청 112",
                "response_time": "5-10분",
                "dispatcher": "서울경찰청 112 상황실",
                "unit": "순찰차 1대 + 경찰관 2명",
                "instructions": [
                    "현장 보존 - CCTV 영상 확보 필수",
                    "가해자/피해자 분리 유지",
                    "목격자 확보 시 대기 요청",
                    "추가 폭력 발생 시 재신고"
                ]
            },
            "119_FIRE": {
                "name": "소방청 119",
                "response_time": "3-7분",
                "dispatcher": "서울소방재난본부 119 상황실",
                "unit": "구급차 1대 + 응급구조사 2명",
                "instructions": [
                    "환자 임의 이동 금지 (척추 손상 가능성)",
                    "기도 확보 및 호흡 확인",
                    "AED 위치 파악 및 준비",
                    "구급대 진입로 확보"
                ]
            },
            "SECURITY_TEAM": {
                "name": "내부 보안팀",
                "response_time": "2-5분",
                "dispatcher": "보안팀 상황실",
                "unit": "보안요원 2명",
                "instructions": [
                    "현장 출동하여 상황 통제",
                    "관계자 외 출입 통제",
                    "CCTV 실시간 모니터링 지속",
                    "경찰 도착 시 인계 준비"
                ]
            },
            "MANAGEMENT": {
                "name": "관리사무소",
                "response_time": "5-15분",
                "dispatcher": "관리사무소 당직자",
                "unit": "관리직원 1명",
                "instructions": [
                    "현장 확인 및 상황 파악",
                    "관련 부서 추가 연락",
                    "시설물 피해 확인",
                    "입주민 안내 및 협조 요청"
                ]
            }
        }

        agency_info = agency_details.get(agency_type, {
            "name": agency_type,
            "response_time": "확인 중",
            "dispatcher": "담당자",
            "unit": "담당 인원",
            "instructions": ["상황 모니터링 지속"]
        })

        instructions_text = "\n".join([f"  {i+1}. {inst}" for i, inst in enumerate(agency_info['instructions'])])

        mock_response = f"""## 긴급 신고 접수 결과

        - 신고 기관: {agency_info['name']}
        - 접수 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        - 접수 번호: EMG-{datetime.now().strftime('%Y%m%d%H%M%S')}
        - 상태: ✅ 접수 완료
        
        ### 전달 내용
        {situation_report}
        
        ### 출동 정보
        - 담당: {agency_info['dispatcher']}
        - 출동 인력: {agency_info['unit']}
        - 예상 도착 시간: {agency_info['response_time']}
        
        ### 현장 조치 지침 (출동 전까지)
        {instructions_text}
        """

        return mock_response

    # =========================================
    # 생성된 도구 리스트 반환
    # =========================================
    # search_protocol_and_cases는 노드로 분리되어 제외됨
    return [execute_field_action, emergency_call]

