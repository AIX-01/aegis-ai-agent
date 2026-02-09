import logging
import base64
import json
from typing import Dict, Any

from ..state import AnalysisState
from ...clients.openai_client import get_vision_completion
from ...config import Config

logger = logging.getLogger(__name__)


def verification_node(state: AnalysisState, config: Config) -> Dict[str, Any]:
    """
    정밀 분석 결과를 검증하는 노드

    precision_analysis 후 실행되며, OpenAI Vision API를 통해
    정밀 분석 결과를 검증하여 ABNORMAL(이상)을 확정하거나 SUSPICIOUS(의심)로 변경합니다.

    Args:
        state: 현재 분석 상태 (precision_result, frames 포함)
        config: 시스템 설정 (프롬프트, API 키 등)

    Returns:
        업데이트된 상태 딕셔너리 (risk_level, verification_result)
    """
    camera_id = state["camera_id"]
    frames = state.get("frames", [])
    precision_result = state.get("precision_result", {})
    current_risk_level = state.get("risk_level", "ABNORMAL")

    logger.info(f"[{camera_id}] 정밀 분석 결과 검증 시작... (현재 risk_level: {current_risk_level})")

    # API 키 확인
    if not config.openai_api_key:
        logger.warning(f"[{camera_id}] OpenAI API 키가 설정되지 않음 - 현재 risk_level 유지")
        return {
            "verification_result": {
                "risk_level": current_risk_level
            }
        }

    # 프레임이 없으면 검증 생략
    if not frames:
        logger.warning(f"[{camera_id}] 프레임이 없음 - 현재 risk_level 유지")
        return {
            "verification_result": {
                "risk_level": current_risk_level
            }
        }

    try:
        # 프롬프트 구성
        prompt = _build_prompt(config.verification_system_prompt, precision_result, state)

        # 프레임을 base64로 인코딩
        images_base64 = [
            base64.b64encode(frame).decode("utf-8") for frame in frames
        ]

        # OpenAI Vision API 호출
        logger.debug(f"[{camera_id}] OpenAI Vision API 호출 중...")
        raw_response = get_vision_completion(
            prompt=prompt,
            images_base64=images_base64,
            api_key=config.openai_api_key,
            model=config.openai_chat_model,
            timeout=config.openai_chat_timeout
        )

        # 응답 파싱
        result = _parse_response(raw_response)

        if result:
            new_risk_level = result.get("risk_level", current_risk_level)
            new_event_type = result.get("event_type", state.get("event_type", ""))
            reason = result.get("reason", "")

            # 로그 출력
            if new_event_type != state.get("event_type", ""):
                logger.info(f"[{camera_id}] 검증 완료: {new_risk_level}, 이벤트 유형 수정: {state.get('event_type')} → {new_event_type} (사유: {reason})")
            else:
                logger.info(f"[{camera_id}] 검증 완료: {new_risk_level} (사유: {reason})")

            return {
                "risk_level": new_risk_level,
                "event_type": new_event_type,
                "verification_result": {
                    "risk_level": new_risk_level,
                    "event_type": new_event_type,
                    "reason": reason
                }
            }
        else:
            # 파싱 실패 시 현재 상태 유지
            logger.warning(f"[{camera_id}] 검증 응답 파싱 실패 - 현재 risk_level 유지: {current_risk_level}")
            return {
                "verification_result": {
                    "risk_level": current_risk_level
                }
            }

    except Exception as e:
        logger.error(f"[{camera_id}] 검증 중 오류 발생: {e}", exc_info=True)
        # 오류 시 현재 상태 유지
        return {
            "verification_result": {
                "risk_level": current_risk_level
            },
            "errors": state.get("errors", []) + [f"Verification exception: {e}"]
        }


def _build_prompt(system_prompt: str, precision_result: Dict[str, Any], state: AnalysisState) -> str:
    """
    검증용 프롬프트를 구성합니다.

    Args:
        system_prompt: config에서 가져온 시스템 프롬프트
        precision_result: 정밀 분석 결과
        state: 현재 상태

    Returns:
        완성된 프롬프트 문자열
    """
    # 정밀 분석 결과 추출
    risk_level = precision_result.get("risk_level", state.get("risk_level", ""))
    event_type = precision_result.get("event_type", state.get("event_type", ""))
    summary = precision_result.get("summary", state.get("summary", ""))
    risk_score = precision_result.get("risk_score", state.get("risk_score", 0.0))

    # 추가 컨텍스트 정보
    camera_name = state.get("camera_name", "")
    camera_location = state.get("camera_location", "")
    occurred_at = state.get("occurred_at", "")
    vlm_result = state.get("vlm_result", {})
    vlm_risk = vlm_result.get("risk_level", vlm_result.get("class1", ""))
    vlm_type = vlm_result.get("event_type", vlm_result.get("class2", ""))

    # 프레임별 타임스탬프 정보 구성
    frame_timestamps = state.get("frame_timestamps", [])
    frame_time_info = ""
    if frame_timestamps and len(frame_timestamps) > 0:
        first_ts = frame_timestamps[0]
        frame_lines = []
        for i, ts in enumerate(frame_timestamps):
            if hasattr(ts, 'strftime'):
                time_str = ts.strftime("%H:%M:%S")
            else:
                time_str = str(ts)
            # 첫 프레임 기준 경과 시간 계산
            if i == 0:
                elapsed = "0.0초"
            elif hasattr(ts, 'timestamp') and hasattr(first_ts, 'timestamp'):
                elapsed = f"{ts.timestamp() - first_ts.timestamp():.1f}초"
            else:
                elapsed = f"{i}초"
            frame_lines.append(f"- Frame {i+1}: {time_str} (경과: {elapsed})")
        frame_time_info = "\n".join(frame_lines)
    else:
        frame_time_info = "- 타임스탬프 정보 없음"

    context = f"""
## 카메라 정보
- 카메라 이름: {camera_name}
- 카메라 위치: {camera_location}
- 발생 시각: {occurred_at}

## 프레임별 시간 정보
{frame_time_info}

## 1차 VLM 분석 결과
- 위험도: {vlm_risk}
- 이벤트 유형: {vlm_type}

## 2차 정밀 분석 결과 (검증 대상)
- 위험도(risk_level): {risk_level}
- 이벤트 유형(event_type): {event_type}
- 요약(summary): {summary}
- 위험 점수(risk_score): {risk_score}

## 검증 요청
위 정밀 분석 결과와 제공된 8개의 이미지를 비교하여 최종 판정을 해주세요.

**판정 기준:**
1. **이미지 확인**: 8개 이미지에서 이상 상황(폭행, 절도, 무단투기, 실신, 기물파손)이 실제로 보이는지 확인
2. **시간 흐름 분석**: 프레임별 타임스탬프를 보고 움직임의 변화/흐름을 파악
3. **장소 맥락**: 카메라 위치({camera_location})를 고려하여 해당 장소에서 발생 가능한 상황인지 판단
4. **VLM vs 정밀분석 비교**: 1차 VLM({vlm_type})과 2차 정밀분석({event_type})이 다르면 이미지를 보고 어느 쪽이 맞는지 판단
5. **요약 검증**: summary 내용이 이미지에서 실제로 확인되는지 검증

**응답 형식 (JSON):**
```json
{{
  "risk_level": "ABNORMAL 또는 SUSPICIOUS",
  "event_type": "실제 이벤트 유형 (ASSAULT/BURGLARY/DUMP/SWOON/VANDALISM)",
  "reason": "판단 근거 설명"
}}
```

**판정 예시:**
- 이미지에 이상 상황이 명확히 보이고 분석이 정확하면:
  {{"risk_level": "ABNORMAL", "event_type": "{event_type}", "reason": "이미지에서 {event_type} 상황이 명확히 확인됨"}}

- 이미지에 이상 상황이 있지만 event_type이 다르면:
  {{"risk_level": "ABNORMAL", "event_type": "실제_유형", "reason": "{event_type}이 아닌 실제_유형으로 확인됨"}}

- 이미지에서 이상 상황이 확인되지 않으면 (오탐지):
  {{"risk_level": "SUSPICIOUS", "event_type": "{event_type}", "reason": "이미지에서 이상 상황이 명확히 확인되지 않음"}}

**event_type 선택지:** ASSAULT(폭행), BURGLARY(절도), DUMP(무단투기), SWOON(실신), VANDALISM(기물파손)
"""

    return f"{system_prompt}\n{context}"


def _parse_response(raw_response: str) -> Dict[str, Any]:
    """
    OpenAI 응답을 파싱합니다.

    Args:
        raw_response: 원시 응답 문자열

    Returns:
        파싱된 딕셔너리 또는 None
    """
    if not raw_response:
        return None

    try:
        # JSON 블록 추출 시도
        response = raw_response.strip()

        # ```json ... ``` 형식 처리
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            response = response[start:end].strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            response = response[start:end].strip()

        # JSON 파싱
        result = json.loads(response)

        # risk_level 정규화
        risk_level = result.get("risk_level", "").upper()
        if risk_level in ["ABNORMAL", "SUSPICIOUS"]:
            result["risk_level"] = risk_level
        else:
            result["risk_level"] = "SUSPICIOUS"  # 기본값

        # event_type 정규화
        valid_event_types = ["ASSAULT", "BURGLARY", "DUMP", "SWOON", "VANDALISM"]
        event_type = result.get("event_type", "").upper()
        if event_type in valid_event_types:
            result["event_type"] = event_type
        # event_type이 없거나 유효하지 않으면 그대로 둠 (기존 값 사용)

        return result

    except json.JSONDecodeError as e:
        logger.warning(f"JSON 파싱 실패: {e}, 원본: {raw_response[:200]}")
        return None
    except Exception as e:
        logger.warning(f"응답 파싱 중 오류: {e}")
        return None

