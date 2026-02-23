"""
LLM 에이전트 노드

LLM이 도구 호출을 결정합니다.
- create_agent_node: LLM 에이전트 노드 생성 (시스템 프롬프트 포함)
- increment_iteration: 반복 횟수 증가

[참고] 라우터 함수들은 edges/routers.py로 이동:
- should_continue: 조건부 라우터 (tools/check_approval/report/end)
- approval_router: 승인 결과에 따른 분기
"""
import logging
from typing import Dict, Any, TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

if TYPE_CHECKING:
    from ....config import Config
    from ..state import ResponseAgentState

logger = logging.getLogger(__name__)


# =========================================
# 시스템 프롬프트
# =========================================
# search_protocol_and_cases 도구가 search_knowledge 노드로 분리됨
# LLM은 이미 검색된 결과를 참조하여 대응 결정만 수행
SYSTEM_PROMPT = """당신은 CCTV 이상 감지 시스템의 대응 전문가입니다.

## 역할
이상 상황이 감지되면 적절한 대응 조치를 결정하고 실행합니다.

## 사용 가능한 도구
1. **execute_field_action**: 현장 물리적 조치 (방송, 조명, PTZ, 사이렌)
   - action_name: BROADCAST, LIGHT_ON, PTZ_TRACK, SIREN
   - camera_id: 대상 카메라 ID
   - message_content: 방송 메시지 (BROADCAST 시 필수)
2. **emergency_call**: 긴급 신고 (112, 119, 보안팀)
   - agency_type: POLICE_112, FIRE_119, SECURITY_TEAM
   - situation_report: 상황 설명

## 참고 정보
대응 매뉴얼과 과거 유사 사례는 이미 검색되어 아래에 제공됩니다.
이 정보를 참고하여 적절한 조치를 결정하세요.

## 프로세스
1. 상황 분석: 제공된 이벤트 정보와 참조 정보를 분석합니다.
2. 현장 조치: execute_field_action으로 필요한 현장 조치를 실행합니다.
3. 긴급 신고: 필요시 emergency_call로 112/119/보안팀에 신고합니다.
4. 완료: 모든 필요한 조치를 완료했으면 종료합니다.

## 대응 기준
- SWOON (실신): 즉시 119 신고, 현장 방송으로 주변에 알림
- ASSAULT (폭행): 112 신고 + 보안팀 출동, 현장 방송/사이렌
- BURGLARY (절도): 112 신고 + 보안팀 출동, PTZ 추적
- VANDALISM (기물파손): 보안팀 출동, 현장 방송
- DUMP (무단투기): 현장 방송으로 경고, 기록 보존

## 복합 상황 대응 (LLM 판단)
상황 요약(summary)을 분석하여 복합적인 대응이 필요한 경우를 판단하세요:
- 폭행(ASSAULT) 중 부상자/실신자 발생: 112 + 119 동시 신고
- 절도(BURGLARY) 중 폭행 발생: 112 신고 + PTZ 추적 + 현장 방송
- 기물파손(VANDALISM) 중 부상자 발생: 112 + 119 동시 신고

※ 이벤트 유형(event_type)만 보지 말고, 상황 요약(summary)의 세부 내용을 
  분석하여 인명 피해 가능성이 있으면 119를 반드시 포함하세요.

## 주의사항
- 상황 심각도에 따라 적절한 도구를 선택하세요.
- 인명 관련 사건(SWOON, ASSAULT)은 반드시 긴급 신고를 수행하세요.
- 현장 조치와 신고를 병행할 수 있습니다.
- 참조 정보(매뉴얼, 과거 사례)를 반드시 확인하고 결정하세요.

## 응답 형식 (중요)
도구를 호출하기 전에 반드시 다음 형식으로 판단 근거를 설명하세요:

```
### 과거 사례 분석
- 유사 사례: [N]건 발견
- 과거 대응 조치: [조치명] [N]회 ([비율]%)
- 시간대 패턴: [N]시~[N]시에 [N]건 발생
- 요일 패턴: [요일]에 [N]건 발생
- 장소 패턴: [장소명]에서 반복 발생 여부

### 법적 근거
[대응 매뉴얼에서 제공된 법적 근거를 인용하여 작성]
- 관련 법령: [법령명 및 조항]
- 적용 사유: [해당 법령이 적용되는 이유 간략히]

### 판단 근거
[과거 사례와 매뉴얼을 참고하여 선택 이유 1~2문장으로 설명]

### 선택한 조치
1. [조치명] - [이유]
2. [조치명] - [이유] (있는 경우)
```

### 과거 사례가 있는 경우 예시:
```
### 과거 사례 분석
- 유사 사례: 3건 발견
- 과거 대응 조치: 현장 방송 경고 2회 (67%), 영상 보존만 1회 (33%)
- 시간대 패턴: 22시~02시에 3건 발생 (야간 집중)
- 요일 패턴: 월요일 2건, 토요일 1건
- 장소 패턴: 후문 CCTV에서 반복 발생 중

### 법적 근거
- 관련 법령: 폐기물관리법 제8조 (폐기물의 투기 금지)
- 적용 사유: 지정된 장소가 아닌 곳에 폐기물 투기 행위 확인

### 판단 근거
과거 사례에서 현장 방송 경고가 67% 사용되었고, 매뉴얼에서도 DUMP 상황에서 현장 방송을 권장합니다.
야간 시간대(22시~02시)에 집중 발생하므로 즉각 대응이 필요합니다.

### 선택한 조치
1. 현장 방송 경고 - 무단투기 중단 및 경고 메시지 전달
```

### 과거 사례가 없는 경우 예시:
```
### 과거 사례 분석
- 유사 사례: 0건 (과거 사례 없음)
- 참고: 대응 매뉴얼 기준으로 판단

### 법적 근거
- 관련 법령: 폐기물관리법 제8조 (폐기물의 투기 금지)
- 적용 사유: 지정된 장소가 아닌 곳에 폐기물 투기 행위 확인

### 판단 근거
과거 유사 사례가 없어 대응 매뉴얼을 기준으로 판단합니다.
DUMP(무단투기) 매뉴얼에 따라 현장 방송 경고를 실행합니다.

### 선택한 조치
1. 현장 방송 경고 - 매뉴얼 권장 조치
```
"""


def create_agent_node(config: "Config", tools: list):
    """
    에이전트 노드를 생성합니다.

    Args:
        config: 시스템 설정
        tools: LangChain 도구 리스트

    Returns:
        에이전트 노드 함수
    """
    # LLM 초기화
    llm = ChatOpenAI(
        model=config.openai_chat_model,
        api_key=config.openai_api_key,
        temperature=0.3
    ).bind_tools(tools)

    def agent_node(state: "ResponseAgentState") -> Dict[str, Any]:
        """에이전트가 다음 행동을 결정합니다."""
        messages = list(state.get("messages", []))

        # 첫 실행 시 시스템 프롬프트와 상황 정보 추가
        if not messages:
            # search_knowledge 노드에서 생성된 검색 결과 가져오기
            knowledge_context = state.get("knowledge_context", "")

            context = f"""## 현재 상황
            - 카메라: {state.get('camera_name', '')} ({state.get('camera_location', '')})
            - 카메라 ID: {state.get('camera_id', '')}
            - 이벤트 유형: {state.get('event_type', '')}
            - 위험도: {state.get('risk_level', '')} (점수: {state.get('risk_score', 0)})
            - 상황 요약: {state.get('summary', '')}
            - 발생 시각: {state.get('occurred_at', '')}
            
            ## 참조 정보 (대응 매뉴얼 및 과거 사례)
            {knowledge_context}
            
            위 정보를 참고하여 적절한 대응 조치를 결정해주세요."""

            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=context)
            ]

        # LLM 호출
        response = llm.invoke(messages)

        return {"messages": [response]}

    return agent_node



def increment_iteration(state: "ResponseAgentState") -> Dict[str, Any]:
    """
    반복 횟수를 증가시킵니다.

    Args:
        state: 현재 에이전트 상태

    Returns:
        업데이트된 상태 (iteration 증가)
    """
    return {"iteration": state.get("iteration", 0) + 1}

