"""
최종 보고서 생성 클라이언트 (OpenAI Chat API 사용)

분석 결과와 대응 조치를 종합하여 구조화된 사건 보고서를 생성합니다.
"""
import logging
import time
from typing import List, Dict, Any, Optional

from .openai_client import get_chat_completion
from ..utils import exponential_backoff


class ReportClient:
    """최종 보고서 생성 클라이언트 (OpenAI Chat 기반)"""

    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger("aegis-agent.report")

        self.api_key = config.openai_api_key
        self.model = config.openai_chat_model
        self.timeout = config.openai_chat_timeout
        self.max_retries = config.report_max_retries
        self.retry_delay = config.report_retry_delay

        self.system_prompt = config.report_system_prompt

        self.total_requests = 0
        self.total_success = 0
        self.total_failures = 0

        self.logger.info(f"ReportClient 초기화됨: 모델={self.model}")

    def generate_report(
        self,
        camera_id: str,
        camera_name: str,
        camera_location: str,
        occurred_at: Any,
        event_type: str,
        risk_level: str,
        risk_score: float,
        summary: str,
        vlm_summary: str,
        actions: List[Dict[str, Any]],
    ) -> Optional[str]:
        """
        사건 보고서를 생성합니다.

        Returns:
            마크다운 형식 보고서 문자열 또는 실패 시 None
        """
        self.total_requests += 1

        prompt = self._build_prompt(
            camera_id, camera_name, camera_location, occurred_at,
            event_type, risk_level, risk_score, summary, vlm_summary, actions
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]

        for attempt in range(self.max_retries):
            try:
                start_time = time.time()

                report = get_chat_completion(
                    messages=messages,
                    api_key=self.api_key,
                    model=self.model,
                    timeout=self.timeout,
                )

                duration = time.time() - start_time

                if report and report.strip():
                    self.total_success += 1
                    self.logger.info(
                        f"[{camera_id}] 보고서 생성 완료, 소요시간: {duration:.2f}초"
                    )
                    return report.strip()

            except Exception as e:
                self.logger.warning(
                    f"보고서 생성 요청 실패 - 카메라: {camera_id}: {e}, "
                    f"시도: {attempt + 1}/{self.max_retries}"
                )

            if attempt < self.max_retries - 1:
                delay = exponential_backoff(attempt, self.retry_delay)
                time.sleep(delay)

        self.total_failures += 1
        self.logger.error(f"보고서 생성 최종 실패 - 카메라: {camera_id}")
        return None

    def _build_prompt(
        self,
        camera_id: str,
        camera_name: str,
        camera_location: str,
        occurred_at: Any,
        event_type: str,
        risk_level: str,
        risk_score: float,
        summary: str,
        vlm_summary: str,
        actions: List[Dict[str, Any]],
    ) -> str:
        actions_text = ""
        for i, act in enumerate(actions, 1):
            actions_text += (
                f"  {i}. [{act.get('priority', 'N/A')}] {act.get('action', 'N/A')}"
                f" → {act.get('target', 'N/A')}: {act.get('message', '')}\n"
            )
        if not actions_text:
            actions_text = "  (대응 조치 없음)\n"

        return f"""## 사건 데이터
- 카메라: {camera_name} ({camera_id})
- 위치: {camera_location}
- 발생 시각: {occurred_at}
- 이벤트 유형: {event_type}
- 위험 등급: {risk_level}
- 위험 점수: {risk_score:.2f}
- 1차 VLM 요약: {vlm_summary}
- 정밀 분석 요약: {summary}

## 결정된 대응 조치
{actions_text}"""

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "total_success": self.total_success,
            "total_failures": self.total_failures,
        }
