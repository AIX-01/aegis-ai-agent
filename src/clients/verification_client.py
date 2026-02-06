"""
Verification 검증 클라이언트 (OpenAI Chat API 사용)

SUSPICIOUS 상태를 ABNORMAL로 격상하거나 SUSPICIOUS를 유지합니다.
"""
import logging
import time
import base64
import json
from typing import List, Dict, Any, Optional

from .openai_client import get_vision_completion
from ..utils import exponential_backoff


class VerificationClient:
    """Verification 검증 클라이언트 (OpenAI Chat 기반)"""

    def __init__(self, config):
        """
        검증 클라이언트 초기화

        Args:
            config: 시스템 설정
        """
        self.config = config
        self.logger = logging.getLogger("aegis-agent.verification")

        # OpenAI 설정
        self.api_key = config.openai_api_key
        self.model = config.openai_chat_model
        self.timeout = config.openai_chat_timeout
        self.max_retries = config.verification_max_retries
        self.retry_delay = config.verification_retry_delay

        # 시스템 프롬프트
        self.system_prompt = config.verification_system_prompt

        # 통계
        self.total_requests = 0
        self.total_success = 0
        self.total_failures = 0

        self.logger.info(
            f"VerificationClient 초기화됨: 모델={self.model}"
        )

    def verify(
        self,
        camera_id: str,
        frames: List[bytes],
        vlm_result: Dict[str, Any],
        task_metadata: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        SUSPICIOUS 상태를 검증하여 최종 risk_level을 결정합니다.

        Args:
            camera_id: 카메라 식별자
            frames: JPEG 프레임 바이트 리스트
            vlm_result: VLM 분석 결과
            task_metadata: 추가 작업 정보

        Returns:
            검증 결과 딕셔너리 또는 실패 시 None
            {
                "risk_level": "ABNORMAL" | "SUSPICIOUS",
                "reason": str
            }
        """
        self.total_requests += 1

        # 프롬프트 구성
        prompt = self._build_prompt(camera_id, vlm_result, task_metadata)

        # 프레임을 base64로 인코딩
        images_base64 = [
            base64.b64encode(frame).decode("utf-8") for frame in frames
        ]

        # 재시도 루프
        for attempt in range(self.max_retries):
            try:
                start_time = time.time()

                # OpenAI Vision API 호출
                raw_response = get_vision_completion(
                    prompt=prompt,
                    images_base64=images_base64,
                    api_key=self.api_key,
                    model=self.model,
                    timeout=self.timeout
                )

                duration = time.time() - start_time

                # JSON 응답 파싱
                result = self._parse_response(raw_response)

                if result:
                    self.total_success += 1
                    self.logger.info(
                        f"[검증 완료] 카메라: {camera_id}, "
                        f"결과: {result.get('risk_level')}, "
                        f"사유: {result.get('reason', 'N/A')}, "
                        f"소요시간: {duration:.2f}초"
                    )
                    return result
                else:
                    self.logger.warning(
                        f"검증 응답 파싱 실패: {raw_response[:200]}..."
                    )

            except Exception as e:
                self.logger.warning(
                    f"검증 요청 실패 - "
                    f"카메라: {camera_id}: {e}, "
                    f"시도: {attempt + 1}/{self.max_retries}"
                )

            # 지수 백오프
            if attempt < self.max_retries - 1:
                delay = exponential_backoff(attempt, self.retry_delay)
                self.logger.debug(f"{delay:.1f}초 후 재시도합니다...")
                time.sleep(delay)

        # 모든 재시도 실패 - 안전하게 ABNORMAL로 격상
        self.total_failures += 1
        self.logger.error(
            f"검증 최종 실패 - 카메라: {camera_id}, "
            f"안전을 위해 ABNORMAL로 격상합니다."
        )
        return {
            "risk_level": "ABNORMAL",
            "reason": "검증 실패로 인한 안전 격상"
        }

    def _build_prompt(
        self,
        camera_id: str,
        vlm_result: Dict[str, Any],
        task_metadata: Dict[str, Any]
    ) -> str:
        """
        검증용 프롬프트를 구성합니다.
        """
        vlm_class1 = vlm_result.get("class1", "unknown")
        vlm_class2 = vlm_result.get("class2", "unknown")
        vlm_raw = vlm_result.get("raw_output", "N/A")

        context = f"""
## 입력 정보
- 카메라 ID: {camera_id}
- 1차 VLM 분석 결과: class1={vlm_class1}, class2={vlm_class2}
- 발생 시각: {task_metadata.get('occurred_at', 'N/A')}
- 분석 구간: {task_metadata.get('window_start', 0)} ~ {task_metadata.get('window_end', 0)}

## VLM 원본 응답
{vlm_raw[:500]}
"""
        return self.system_prompt + context

    def _parse_response(self, raw_response: str) -> Optional[Dict[str, Any]]:
        """
        OpenAI 응답에서 JSON을 파싱합니다.
        """
        try:
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

            # 필수 필드 검증
            risk_level = result.get("risk_level", "ABNORMAL").upper()
            reason = result.get("reason", "")

            # risk_level 유효성 검사
            if risk_level not in ["ABNORMAL", "SUSPICIOUS"]:
                risk_level = "ABNORMAL"  # 안전하게 격상

            return {
                "risk_level": risk_level,
                "reason": reason
            }

        except json.JSONDecodeError as e:
            self.logger.error(f"JSON 파싱 오류: {e}")
            return None
        except Exception as e:
            self.logger.error(f"응답 처리 오류: {e}")
            return None

    def get_stats(self) -> Dict[str, Any]:
        """클라이언트 통계 조회"""
        return {
            "total_requests": self.total_requests,
            "total_success": self.total_success,
            "total_failures": self.total_failures,
            "success_rate": (
                100 * self.total_success / self.total_requests
                if self.total_requests > 0
                else 0
            ),
        }
