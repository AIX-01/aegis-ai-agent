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
            reason = result.get("reason", "")

            # reason은 로그에만 출력 (state에 저장하지 않음)
            logger.info(f"[{camera_id}] 검증 완료: {new_risk_level} (사유: {reason})")

            return {
                "risk_level": new_risk_level,
                "verification_result": {
                    "risk_level": new_risk_level
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

    context = f"""
## 정밀 분석 결과
- 위험도(risk_level): {risk_level}
- 이벤트 유형(event_type): {event_type}
- 요약(summary): {summary}
- 위험 점수(risk_score): {risk_score}

## 검증 요청
위 정밀 분석 결과와 제공된 8개의 이미지를 비교하여 최종 위험도를 판정해주세요.
- 분석 결과(summary)가 이미지와 일치하는지 확인하세요.
- 이벤트 유형(event_type)이 실제 상황과 맞는지 확인하세요.
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

        return result

    except json.JSONDecodeError as e:
        logger.warning(f"JSON 파싱 실패: {e}, 원본: {raw_response[:200]}")
        return None
    except Exception as e:
        logger.warning(f"응답 파싱 중 오류: {e}")
        return None

