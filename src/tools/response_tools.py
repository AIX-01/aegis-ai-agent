"""
대응 조치(Response) 관련 LangChain 도구 모음

response_agent에서 사용하는 도구들을 정의합니다:
- search_protocol_and_cases: 대응 매뉴얼 및 과거 사례 검색
- execute_field_action: 현장 물리적 조치 실행
- emergency_call: 긴급 신고 접수

사용 예시:
    from src.tools.response_tools import create_response_tools
    from src.config import Config

    config = Config()
    tools = create_response_tools(config)

    # tools는 LangChain 도구 리스트로 반환됩니다.
    # [search_protocol_and_cases, execute_field_action, emergency_call]
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

    Args:
        config: Config 인스턴스 (Qdrant, OpenAI 설정 포함)

    Returns:
        LangChain 도구 리스트 [search_protocol_and_cases, execute_field_action, emergency_call]
    """

    @tool
    def search_protocol_and_cases(
        summary: str,
        event_type: str,
        camera_name: str = "",
        camera_location: str = ""
    ) -> str:
        """
        지식 검색 도구: 과거 유사 사례와 표준 대응 매뉴얼을 검색합니다.

        Args:
            summary: 상황 요약 (예: "1층 로비에서 남성이 쓰러져 있음") - 검색 우선순위 가장 높음
            event_type: 사건 유형 (ASSAULT, BURGLARY, DUMP, SWOON, VANDALISM)
            camera_name: 카메라 이름 (예: "주차장 A동")
            camera_location: 카메라 위치 (예: "1층 입구")

        Returns:
            해당 사건에 대한 단계별 대응 지침, 법적 근거, 과거 유사 처리 결과
        """
        from ..clients.vector_store_client import VectorStoreClient

        # =========================================
        # 임베딩용 검색 텍스트 구성
        # =========================================
        # 이 텍스트가 OpenAI Embedding API를 통해 1536차원 벡터로 변환되어
        # Qdrant에 저장된 과거 사례들의 vector와 유사도 비교됩니다.
        #
        # [검색 흐름]
        # query (문자열)
        #     ↓
        # OpenAI text-embedding-3-small 모델
        #     ↓
        # query_vector: [0.012, -0.034, ...] (1536차원)
        #     ↓
        # Qdrant에서 저장된 vector들과 코사인 유사도 비교
        #     ↓
        # 유사도 높은 순으로 결과 반환
        #
        # [우선순위]
        # summary가 가장 앞에 배치되어 검색 시 가장 높은 영향력을 가짐
        # (임베딩 모델은 텍스트 앞부분에 더 높은 가중치 부여)
        #
        # [저장 시와 동일한 필드 사용]
        # - summary: 상황 요약 (우선순위 1)
        # - camera_name + camera_location: 위치 정보 (우선순위 2)
        # - event_type: 이벤트 유형 (우선순위 3)
        # =========================================
        query_parts = []

        # summary가 가장 중요하므로 맨 앞에 배치 (임베딩 시 앞부분이 더 큰 영향)
        if summary:
            query_parts.append(f"상황: {summary}")

        # 부가 정보 (카메라 정보)
        if camera_name or camera_location:
            location_info = f"{camera_name} {camera_location}".strip()
            if location_info:
                query_parts.append(f"위치: {location_info}")

        # 이벤트 유형
        if event_type:
            query_parts.append(f"유형: {event_type}")

        # 최종 검색 쿼리 구성
        # 예시: "상황: 1층 로비에서 남성 2인이 폭행 중 | 위치: 주차장 A동 1층 입구 | 유형: ASSAULT"
        query = " | ".join(query_parts) if query_parts else summary

        logger.info(f"[Tool] search_protocol_and_cases 호출: query='{query[:80]}...', event_type={event_type}")

        result_text = ""

        # =========================================
        # 과거 사례 검색 (벡터 유사도 + 필터링)
        # =========================================
        # - query: 벡터 유사도 검색 (임베딩 필수)
        # - filters: 메타데이터 필터링 (임베딩 불필요, 정확히 일치)
        # =========================================
        try:
            client = VectorStoreClient(config)

            if client.collection_exists("past_cases"):
                past_results = client.search(
                    collection_name="past_cases",
                    query=query,                                    # 벡터 유사도 검색
                    limit=3,
                    filters={"event_type": event_type} if event_type else None  # 메타데이터 필터링
                )

                if past_results:
                    result_text += "## 과거 유사 사례\n\n"
                    for i, result in enumerate(past_results, 1):
                        payload = result.get("payload", {})
                        score = result.get("score", 0)
                        result_text += f"### 사례 {i} (유사도: {score:.2f})\n"
                        result_text += f"- 카메라: {payload.get('camera_name', '')} ({payload.get('camera_location', '')})\n"
                        result_text += f"- 이벤트: {payload.get('event_type', '')}\n"
                        result_text += f"- 발생시각: {payload.get('occurred_at', '')}\n"
                        result_text += f"- 상황: {payload.get('summary', '')}\n\n"
                else:
                    result_text += "## 과거 유사 사례\n검색 결과 없음\n\n"
            else:
                result_text += "## 과거 유사 사례\n컬렉션이 존재하지 않습니다.\n\n"

        except Exception as e:
            logger.error(f"과거 사례 검색 실패: {e}")
            result_text += f"## 과거 유사 사례\n검색 실패: {e}\n\n"

        # =========================================
        # 대응 매뉴얼 조회
        # =========================================
        # 매뉴얼은 manual_templates.py에 정의되어 있습니다.
        # 현재는 하드코딩 방식이며, 매뉴얼 수가 20개 이상으로 증가하거나
        # 동적 업데이트가 필요한 경우 Qdrant RAG로 전환을 검토합니다.
        # =========================================
        from .manual_templates import get_manual
        result_text += get_manual(event_type)

        return result_text

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

    # 생성된 도구 리스트 반환
    return [search_protocol_and_cases, execute_field_action, emergency_call]

