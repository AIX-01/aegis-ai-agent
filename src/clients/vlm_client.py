"""
재시도 및 타임아웃 처리를 포함한 VLM API 클라이언트
"""
import logging
import time
import base64
from typing import List, Dict, Any, Optional
import requests

from .openai_client import get_vision_completion
from ..utils import exponential_backoff


class VLMClient:
    """VLM(Vision Language Model) API와 통신하기 위한 클라이언트"""

    def __init__(self, config, prompt: str = None):
        """
        VLM 클라이언트 초기화

        Args:
            config: 시스템 설정
            prompt: VLM에 전송할 시스템 프롬프트 (None이면 config에서 로드)
        """
        self.config = config
        self.logger = logging.getLogger("aegis-agent.vlm_client")

        # 설정에서 엔드포인트 및 API 키 로드
        self.endpoint = config.vlm_endpoint
        self.api_key = config.vlm_api_key
        self.timeout = config.vlm_timeout
        self.max_retries = config.vlm_max_retries
        self.retry_delay = config.vlm_retry_delay
        self.model_id = config.vlm_model_id

        # 프롬프트 설정 (인자 > config)
        self.prompt = prompt if prompt is not None else config.vlm_system_prompt

        # 실제 VLM 모드 여부
        self.is_real_mode = getattr(config, "real_vlm", False)

        if self.is_real_mode:
            self.logger.info(f"실제 VLM 서버를 사용합니다: {self.endpoint} (Model: {self.model_id})")
        else:
            self.logger.info("VLM 클라이언트가 Mock 모드(모의 서버)로 동작합니다.")

        self.total_requests = 0
        self.total_success = 0
        self.total_failures = 0

    def analyze_frames(
        self,
        camera_id: str,
        frames: List[bytes],
        task_metadata: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        분석을 위해 VLM API로 프레임 전송
        """
        self.total_requests += 1

        if self.is_real_mode and self.model_id:
            return self._analyze_via_openai(camera_id, frames, task_metadata)

        return self._analyze_via_requests(camera_id, frames, task_metadata)

    def _analyze_via_openai(
        self,
        camera_id: str,
        frames: List[bytes],
        task_metadata: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """OpenAI 호환 API를 사용한 분석 수행"""
        # 프레임을 base64로 인코딩
        images_base64 = [base64.b64encode(frame).decode("utf-8") for frame in frames]
        window_range = f"({task_metadata.get('window_start', 0)}-{task_metadata.get('window_end', 0)})"

        for attempt in range(self.max_retries):
            try:
                start_time = time.time()

                # OpenAI 호환 API 호출
                raw_text = get_vision_completion(
                    prompt=self.prompt,
                    images_base64=images_base64,
                    api_key=self.api_key,
                    model=self.model_id,
                    base_url=self.endpoint,
                    timeout=self.timeout
                )

                duration = time.time() - start_time

                # 결과 딕셔너리 생성
                result = {"raw_output": raw_text, "analysis_duration": duration}

                # 결과 파싱 (class1, class2 추출 및 정규화)
                lines = raw_text.replace(',', '\n').split('\n')
                for line in lines:
                    if '=' in line:
                        parts = line.split('=', 1)
                        if len(parts) == 2:
                            key = parts[0].strip().lower()
                            val = parts[1].strip().lower().strip('<>')
                            result[key] = val

                # class1이 없을 경우 키워드 검색으로 보완
                if "class1" not in result:
                    if "normal" in raw_text.lower():
                        result["class1"] = "normal"
                    elif "abnormal" in raw_text.lower():
                        result["class1"] = "abnormal"
                    elif "suspicious" in raw_text.lower():
                        result["class1"] = "suspicious"

                # class2가 없을 경우 키워드 검색으로 보완
                if "class2" not in result:
                    if "assault" in raw_text.lower():
                        result["class2"] = "assault"
                    elif "dump" in raw_text.lower():
                        result["class2"] = "dump"
                    elif "burglary" in raw_text.lower():
                        result["class2"] = "burglary"
                    elif "swoon" in raw_text.lower():
                        result["class2"] = "swoon"
                    elif "vandalism" in raw_text.lower():
                        result["class2"] = "vandalism"

                # 로그 출력
                if result.get("class1") == "normal":
                    self.logger.info(
                        f"[{camera_id}] {window_range} VLM 분석 결과: NORMAL입니다. "
                        f"(소요: {duration:.2f}초)"
                    )
                else:
                    self.logger.info(
                        f"[{camera_id}] {window_range} VLM 분석 완료, "
                        f"소요 시간: {duration:.2f}초"
                    )
                    self.logger.info(
                        f"[{camera_id}] {window_range} VLM Raw Response: \n{raw_text}"
                    )

                self.total_success += 1
                return result

            except Exception as e:
                self.logger.warning(
                    f"VLM(OpenAI SDK) 요청 실패: {e} "
                    f"(시도 {attempt + 1}/{self.max_retries})"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(exponential_backoff(attempt, self.retry_delay))

        self.total_failures += 1
        return None

    def _analyze_via_requests(
        self,
        camera_id: str,
        frames: List[bytes],
        task_metadata: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """기존 requests 방식을 사용한 분석 수행 (주로 Mock 서버용)"""
        payload = self._prepare_payload(camera_id, frames, task_metadata)
        for attempt in range(self.max_retries):
            try:
                start_time = time.time()
                response = requests.post(
                    self.endpoint, json=payload, timeout=self.timeout
                )
                response.raise_for_status()
                duration = time.time() - start_time
                result = response.json()
                result["analysis_duration"] = duration
                self.total_success += 1
                return result
            except Exception as e:
                if attempt < self.max_retries - 1:
                    time.sleep(exponential_backoff(attempt, self.retry_delay))
        self.total_failures += 1
        return None

    def _prepare_payload(
        self,
        camera_id: str,
        frames: List[bytes],
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """VLM API를 위한 일반 JSON 페이로드 준비"""
        encoded_frames = [
            base64.b64encode(frame).decode("utf-8") for frame in frames
        ]
        return {
            "camera_id": camera_id,
            "frames": encoded_frames,
            "num_frames": len(frames),
            "timestamp": str(metadata.get("timestamp", "")),
            "window_start": metadata.get("window_start", 0),
            "window_end": metadata.get("window_end", 0),
        }

    def get_stats(self) -> Dict[str, int]:
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
