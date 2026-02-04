"""
재시도 및 타임아웃 처리를 포함한 VLM API 클라이언트
"""
import logging
import time
import base64
from typing import List, Dict, Any, Optional
import requests
from requests.exceptions import RequestException, Timeout
from openai import OpenAI

# utils가 src/utils.py에 위치하므로 상위 디렉토리에서 import
from ..utils import exponential_backoff


class VLMClient:
    """VLM(Vision Language Model) API와 통신하기 위한 클라이언트"""

    # VLM 분석을 위한 기본 시스템 프롬프트
    DEFAULT_PROMPT = """You are a video incident classifier.

        Input: frames at 1 FPS in chronological order. Predict what situation is occurring next.
        
        Output exactly:
        class1=<normal|suspicious|abnormal>
        class2=<assault|burglary|dump|swoon|vandalism>
        
        No extra text."""

    def __init__(self, config, prompt: str = None):
        """
        VLM 클라이언트 초기화

        Args:
            config: 시스템 설정
            prompt: VLM에 전송할 시스템 프롬프트 (None이면 기본 프롬프트 사용)
        """
        self.config = config
        self.logger = logging.getLogger("aegis-agent.vlm_client")

        self.endpoint = config.vlm_endpoint
        self.api_key = getattr(config, "vlm_api_key", None)
        self.timeout = config.vlm_timeout
        self.max_retries = config.vlm_max_retries
        self.retry_delay = config.vlm_retry_delay
        
        # 프롬프트 설정 (사용자 지정 또는 기본값 사용)
        self.prompt = prompt if prompt is not None else self.DEFAULT_PROMPT

        # OpenAI 클라이언트 초기화 (실제 VLM 모드일 때만)
        self.client = None
        self.model_id = getattr(config, "vlm_model_id", "vlm")
        
        is_real_mode = getattr(config, "real_vlm", False)
        if is_real_mode:
            self.logger.info(f"실제 VLM 서버를 사용합니다: {self.endpoint} (Model: {self.model_id})")
            try:
                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.endpoint
                )
                self.logger.info(f"VLM 클라이언트 초기화 완료")
            except Exception as e:
                self.logger.error(f"VLM 클라이언트 초기화 실패: {e}")
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

        if self.client and self.model_id:
            return self._analyze_via_openai(camera_id, frames, task_metadata)
        
        return self._analyze_via_requests(camera_id, frames, task_metadata)

    def _analyze_via_openai(
        self,
        camera_id: str,
        frames: List[bytes],
        task_metadata: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """OpenAI SDK를 사용한 분석 수행"""
        content = [{"type": "text", "text": self.prompt}]
        
        for frame in frames:
            base64_image = base64.b64encode(frame).decode("utf-8")
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{base64_image}"
                }
            })

        for attempt in range(self.max_retries):
            try:
                start_time = time.time()
                response = self.client.chat.completions.create(
                    model=self.model_id,
                    messages=[{"role": "user", "content": content}],
                    timeout=self.timeout
                )
                duration = time.time() - start_time
                
                raw_text = response.choices[0].message.content
                self.logger.info(f"VLM 분석 완료: {camera_id}, 소요 시간: {duration:.2f}초")
                self.logger.info(f"VLM Raw Response: \n{raw_text}")
                
                result = {"raw_output": raw_text, "analysis_duration": duration}
                
                # 결과 파싱 강화
                lines = raw_text.replace(',', '\n').split('\n')
                for line in lines:
                    if '=' in line:
                        parts = line.split('=', 1)
                        if len(parts) == 2:
                            key = parts[0].strip().lower()
                            # 값에서 공백 및 꺽쇠 괄호(< >) 제거
                            val = parts[1].strip().lower().strip('<>')
                            result[key] = val
                
                # class1이 없을 경우 키워드 검색
                if "class1" not in result:
                    if "normal" in raw_text.lower(): result["class1"] = "normal"
                    elif "abnormal" in raw_text.lower(): result["class1"] = "abnormal"
                    elif "suspicious" in raw_text.lower(): result["class1"] = "suspicious"

                self.total_success += 1
                return result

            except Exception as e:
                self.logger.warning(f"VLM(OpenAI SDK) 요청 실패: {e} (시도 {attempt + 1}/{self.max_retries})")
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
        """기존 requests 방식을 사용한 분석 수행 (Mock 서버용)"""
        payload = self._prepare_payload(camera_id, frames, task_metadata)
        for attempt in range(self.max_retries):
            try:
                start_time = time.time()
                response = requests.post(self.endpoint, json=payload, timeout=self.timeout)
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
        encoded_frames = [base64.b64encode(frame).decode("utf-8") for frame in frames]
        return {
            "camera_id": camera_id,
            "frames": encoded_frames,
            "num_frames": len(frames),
            "timestamp": str(metadata.get("timestamp", "")),
            "window_start": metadata.get("window_start", 0),
            "window_end": metadata.get("window_end", 0),
        }

    def get_stats(self) -> Dict[str, int]:
        return {
            "total_requests": self.total_requests,
            "total_success": self.total_success,
            "total_failures": self.total_failures,
            "success_rate": (100 * self.total_success / self.total_requests if self.total_requests > 0 else 0),
        }