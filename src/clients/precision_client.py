"""
정밀 분석 API 클라이언트 (OpenAI Chat API 사용)
"""
import logging
import time
import base64
import json
from typing import List, Dict, Any, Optional
from datetime import datetime

from .openai_client import get_vision_completion
from ..utils import exponential_backoff


class PrecisionClient:
    """정밀 분석 API 클라이언트 (OpenAI Chat 기반)"""

    def __init__(self, config):
        """
        정밀 분석 클라이언트 초기화

        Args:
            config: 시스템 설정
        """
        self.config = config
        self.logger = logging.getLogger("aegis-agent.precision")

        # OpenAI 설정
        self.api_key = config.openai_api_key
        self.model = config.openai_chat_model
        self.timeout = config.openai_chat_timeout
        self.max_retries = config.precision_max_retries
        self.retry_delay = config.precision_retry_delay

        # 시스템 프롬프트
        self.system_prompt = config.precision_system_prompt

        # 통계
        self.total_requests = 0
        self.total_success = 0
        self.total_failures = 0
        self.total_tokens_used = 0

        self.logger.info(
            f"PrecisionClient 초기화됨: 모델={self.model}, 타임아웃={self.timeout}초"
        )

    def send_for_analysis(
        self,
        camera_id: str,
        frames: List[bytes],
        vlm_metadata: Dict[str, Any],
        task_metadata: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        프레임을 정밀 분석 API로 전송

        Args:
            camera_id: 카메라 식별자
            frames: JPEG 프레임 바이트 리스트
            vlm_metadata: VLM 분석 결과 메타데이터
            task_metadata: 추가 작업 정보

        Returns:
            분석 결과 딕셔너리 또는 실패 시 None
            {
                "event_type": str,
                "summary": str,
                "risk_score": float
            }
        """
        self.total_requests += 1

        # 프롬프트 구성
        prompt = self._build_prompt(camera_id, vlm_metadata, task_metadata)

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
                        f"[성공] 정밀 분석 완료 - "
                        f"카메라: {camera_id}, "
                        f"이벤트: {result.get('event_type', 'N/A')}, "
                        f"소요시간: {duration:.2f}초"
                    )
                    return result
                else:
                    self.logger.warning(
                        f"정밀 분석 응답 파싱 실패: {raw_response[:200]}..."
                    )

            except Exception as e:
                self.logger.warning(
                    f"정밀 분석 요청 실패 - "
                    f"카메라: {camera_id}: {e}, "
                    f"시도: {attempt + 1}/{self.max_retries}"
                )

            # 지수 백오프
            if attempt < self.max_retries - 1:
                delay = exponential_backoff(attempt, self.retry_delay)
                self.logger.debug(f"{delay:.1f}초 후 재시도합니다...")
                time.sleep(delay)

        # 모든 재시도 실패
        self.total_failures += 1
        self.logger.error(
            f"정밀 분석 최종 실패 - "
            f"카메라: {camera_id}, "
            f"재시도 횟수: {self.max_retries}"
        )
        return None

    def _build_prompt(
        self,
        camera_id: str,
        vlm_metadata: Dict[str, Any],
        task_metadata: Dict[str, Any]
    ) -> str:
        """
        분석용 프롬프트를 구성합니다.

        Args:
            camera_id: 카메라 ID
            vlm_metadata: VLM 1차 분석 결과
            task_metadata: 작업 메타데이터

        Returns:
            완성된 프롬프트 문자열
        """
        vlm_risk = vlm_metadata.get("risk_level", "")
        vlm_event = vlm_metadata.get("event_type", "")

        # 카메라 정보
        camera_name = task_metadata.get("camera_name", camera_id)
        camera_location = task_metadata.get("camera_location", "")

        # 프레임별 타임스탬프 정보 구성
        frame_timestamps = task_metadata.get("frame_timestamps", [])
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
- 카메라 ID: {camera_id}
- 카메라 이름: {camera_name}
- 카메라 위치: {camera_location}

## 1차 VLM 분석 결과
- 위험도: {vlm_risk}
- 이벤트 유형: {vlm_event}

## 시간 정보
- 발생 시각: {task_metadata.get('occurred_at', 'N/A')}
- 분석 구간: {task_metadata.get('window_start', 0)} ~ {task_metadata.get('window_end', 0)}

## 프레임별 시간 정보
{frame_time_info}
"""
        return self.system_prompt + context

    def _parse_response(self, raw_response: str) -> Optional[Dict[str, Any]]:
        """
        OpenAI 응답에서 JSON을 파싱합니다.

        Args:
            raw_response: OpenAI 응답 텍스트

        Returns:
            파싱된 딕셔너리 또는 None
        """
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

            # 필수 필드 검증
            event_type = result.get("event_type", "").upper()
            summary = result.get("summary", "")
            risk_score = float(result.get("risk_score", 0.0))

            # risk_score 범위 제한
            risk_score = max(0.0, min(1.0, risk_score))

            return {
                "event_type": event_type,
                "summary": summary,
                "risk_score": risk_score
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
