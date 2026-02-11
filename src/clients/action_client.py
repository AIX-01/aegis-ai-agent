"""
대응 조치 결정 클라이언트 (OpenAI Chat API 사용)

이벤트 유형과 위험도에 따라 적절한 대응 조치를 LLM으로 결정합니다.
"""
import logging
import time
import json
from typing import List, Dict, Any, Optional

from .openai_client import get_chat_completion
from ..utils import exponential_backoff


class ActionClient:
    """대응 조치 결정 클라이언트 (OpenAI Chat 기반)"""

    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger("aegis-agent.action")

        self.api_key = config.openai_api_key
        self.model = config.openai_chat_model
        self.timeout = config.openai_chat_timeout
        self.max_retries = config.action_max_retries
        self.retry_delay = config.action_retry_delay

        self.system_prompt = config.action_system_prompt

        self.total_requests = 0
        self.total_success = 0
        self.total_failures = 0

        self.logger.info(f"ActionClient 초기화됨: 모델={self.model}")

    def decide_actions(
        self,
        camera_id: str,
        camera_name: str,
        camera_location: str,
        event_type: str,
        risk_level: str,
        risk_score: float,
        summary: str,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        이벤트 분석 결과를 기반으로 대응 조치를 결정합니다.

        Returns:
            대응 조치 리스트 또는 실패 시 None
            [{"action": str, "priority": str, "target": str, "message": str}, ...]
        """
        self.total_requests += 1

        prompt = self._build_prompt(
            camera_id, camera_name, camera_location,
            event_type, risk_level, risk_score, summary
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]

        for attempt in range(self.max_retries):
            try:
                start_time = time.time()

                raw_response = get_chat_completion(
                    messages=messages,
                    api_key=self.api_key,
                    model=self.model,
                    timeout=self.timeout,
                )

                duration = time.time() - start_time
                result = self._parse_response(raw_response)

                if result is not None:
                    self.total_success += 1
                    self.logger.info(
                        f"[{camera_id}] 대응 조치 결정 완료: {len(result)}건, "
                        f"소요시간: {duration:.2f}초"
                    )
                    return result
                else:
                    self.logger.warning(
                        f"대응 조치 응답 파싱 실패: {raw_response[:200]}..."
                    )

            except Exception as e:
                self.logger.warning(
                    f"대응 조치 요청 실패 - 카메라: {camera_id}: {e}, "
                    f"시도: {attempt + 1}/{self.max_retries}"
                )

            if attempt < self.max_retries - 1:
                delay = exponential_backoff(attempt, self.retry_delay)
                time.sleep(delay)

        self.total_failures += 1
        self.logger.error(f"대응 조치 결정 최종 실패 - 카메라: {camera_id}")
        return None

    def _build_prompt(
        self,
        camera_id: str,
        camera_name: str,
        camera_location: str,
        event_type: str,
        risk_level: str,
        risk_score: float,
        summary: str,
    ) -> str:
        return f"""## 이벤트 정보
- 카메라: {camera_name} ({camera_id})
- 위치: {camera_location}
- 이벤트 유형: {event_type}
- 위험 등급: {risk_level}
- 위험 점수: {risk_score:.2f}
- 상황 요약: {summary}"""

    def _parse_response(self, raw_response: str) -> Optional[List[Dict[str, Any]]]:
        try:
            response = raw_response.strip()

            if "```json" in response:
                start = response.find("```json") + 7
                end = response.find("```", start)
                response = response[start:end].strip()
            elif "```" in response:
                start = response.find("```") + 3
                end = response.find("```", start)
                response = response[start:end].strip()

            result = json.loads(response)

            actions = result.get("actions", result if isinstance(result, list) else [])

            validated = []
            for action in actions:
                validated.append({
                    "action": action.get("action", ""),
                    "priority": action.get("priority", "MEDIUM"),
                    "target": action.get("target", ""),
                    "message": action.get("message", ""),
                })
            return validated

        except json.JSONDecodeError as e:
            self.logger.error(f"JSON 파싱 오류: {e}")
            return None
        except Exception as e:
            self.logger.error(f"응답 처리 오류: {e}")
            return None

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "total_success": self.total_success,
            "total_failures": self.total_failures,
        }
