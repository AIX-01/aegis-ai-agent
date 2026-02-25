"""
큐 어댑터: 로컬 queue.Queue와 AWS SQS를 동일한 인터페이스로 추상화

AGENT_MODE에 따라 적절한 어댑터가 선택됩니다:
- all: LocalQueueAdapter (기존 QueueManager 래핑)
- ingest/worker: SQSQueueAdapter (AWS SQS + S3 하이브리드)
"""
import base64
import json
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

logger = logging.getLogger("aegis-agent.queue_adapter")

# SQS 메시지 최대 크기 256KB, 안전 마진으로 200KB 기준
SQS_INLINE_THRESHOLD = 200 * 1024


class QueueAdapter(ABC):
    """큐 추상 인터페이스"""

    @abstractmethod
    def put(self, task: dict) -> bool:
        """태스크를 큐에 추가. 성공 시 True."""
        ...

    @abstractmethod
    def get(self, timeout: float = None) -> Optional[dict]:
        """큐에서 태스크를 가져옴. 없으면 None."""
        ...

    @abstractmethod
    def size(self) -> int:
        """현재 큐 크기 (approximate)."""
        ...


class LocalQueueAdapter(QueueAdapter):
    """
    기존 QueueManager를 래핑하는 로컬 어댑터 (AGENT_MODE=all)

    기존 코드와 100% 동일한 동작을 보장합니다.
    """

    def __init__(self, queue_manager):
        self.queue_manager = queue_manager

    def put(self, task: dict) -> bool:
        return self.queue_manager.put(task)

    def get(self, timeout: float = None) -> Optional[dict]:
        return self.queue_manager.get(timeout=timeout)

    def size(self) -> int:
        return self.queue_manager.size()


class SQSQueueAdapter(QueueAdapter):
    """
    AWS SQS를 사용하는 큐 어댑터 (AGENT_MODE=ingest/worker)

    하이브리드 전송 방식:
    - 200KB 이하: SQS 메시지에 직접 인라인 전송
    - 200KB 초과: frames를 S3에 업로드하고, SQS에는 S3 키만 전송

    frames(JPG bytes 리스트)는 base64로 인코딩하여 JSON 직렬화합니다.
    """

    def __init__(self, queue_url: str, s3_bucket: str, region: str = "ap-northeast-2"):
        import boto3

        self.sqs = boto3.client("sqs", region_name=region)
        self.s3 = boto3.client("s3", region_name=region)
        self.queue_url = queue_url
        self.s3_bucket = s3_bucket

    def put(self, task: dict) -> bool:
        """
        태스크를 SQS에 전송합니다.

        frames(bytes 리스트)를 base64 인코딩 후 크기를 판단:
        - inline: SQS 메시지에 직접 포함
        - s3: S3에 업로드 후 SQS에는 참조만 전송
        """
        try:
            # datetime 객체를 ISO 문자열로 변환
            sqs_task = self._serialize_task(task)

            # 인라인 전송 시도를 위한 JSON 크기 측정
            sqs_task["transfer_mode"] = "inline"
            payload = json.dumps(sqs_task, ensure_ascii=False)

            if len(payload.encode("utf-8")) <= SQS_INLINE_THRESHOLD:
                # 인라인 전송 (대부분의 경우)
                self.sqs.send_message(
                    QueueUrl=self.queue_url,
                    MessageBody=payload,
                )
            else:
                # S3 경유 전송 (큰 프레임 데이터)
                s3_key = f"sqs-frames/{uuid.uuid4().hex}.json"
                frames_data = sqs_task.pop("low_res_frames", [])

                self.s3.put_object(
                    Bucket=self.s3_bucket,
                    Key=s3_key,
                    Body=json.dumps(frames_data).encode("utf-8"),
                    ContentType="application/json",
                )

                sqs_task["transfer_mode"] = "s3"
                sqs_task["s3_frames_key"] = s3_key
                payload = json.dumps(sqs_task, ensure_ascii=False)

                self.sqs.send_message(
                    QueueUrl=self.queue_url,
                    MessageBody=payload,
                )

            return True

        except Exception as e:
            logger.error(f"SQS 전송 실패: {e}", exc_info=True)
            return False

    def get(self, timeout: float = 20.0) -> Optional[dict]:
        """
        SQS에서 메시지를 수신합니다 (long polling).

        transfer_mode에 따라:
        - inline: 메시지 본문에서 직접 frames 복원
        - s3: S3에서 frames 다운로드 후 복원

        처리 완료 후 SQS 메시지를 삭제합니다.
        """
        try:
            wait_time = min(int(timeout), 20) if timeout else 20
            response = self.sqs.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=wait_time,
            )

            messages = response.get("Messages", [])
            if not messages:
                return None

            msg = messages[0]
            receipt_handle = msg["ReceiptHandle"]
            body = json.loads(msg["Body"])

            transfer_mode = body.pop("transfer_mode", "inline")

            if transfer_mode == "s3":
                # S3에서 프레임 데이터 다운로드
                s3_key = body.pop("s3_frames_key")
                s3_obj = self.s3.get_object(Bucket=self.s3_bucket, Key=s3_key)
                frames_data = json.loads(s3_obj["Body"].read().decode("utf-8"))
                body["low_res_frames"] = frames_data

                # S3 임시 파일 정리
                try:
                    self.s3.delete_object(Bucket=self.s3_bucket, Key=s3_key)
                except Exception:
                    pass

            # base64 디코딩으로 frames(bytes 리스트) 복원
            task = self._deserialize_task(body)

            # 처리 완료: SQS 메시지 삭제
            self.sqs.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle,
            )

            return task

        except Exception as e:
            logger.error(f"SQS 수신 실패: {e}", exc_info=True)
            return None

    def size(self) -> int:
        """SQS 큐의 대략적인 메시지 수를 반환합니다."""
        try:
            response = self.sqs.get_queue_attributes(
                QueueUrl=self.queue_url,
                AttributeNames=["ApproximateNumberOfMessages"],
            )
            return int(response["Attributes"]["ApproximateNumberOfMessages"])
        except Exception:
            return 0

    def _serialize_task(self, task: dict) -> dict:
        """태스크를 SQS 전송용으로 직렬화합니다."""
        sqs_task = {}
        for key, value in task.items():
            if key == "low_res_frames":
                # bytes 리스트 → base64 문자열 리스트
                sqs_task[key] = [
                    base64.b64encode(f).decode("ascii") if isinstance(f, bytes) else f
                    for f in value
                ]
            elif hasattr(value, "isoformat"):
                # datetime → ISO 문자열
                sqs_task[key] = value.isoformat()
            elif isinstance(value, list):
                # 리스트 내 datetime 객체도 ISO 문자열로 변환
                sqs_task[key] = [
                    v.isoformat() if hasattr(v, "isoformat") else v
                    for v in value
                ]
            else:
                sqs_task[key] = value
        return sqs_task

    def _deserialize_task(self, body: dict) -> dict:
        """SQS 메시지를 원래 태스크 딕셔너리로 복원합니다."""
        task = {}
        for key, value in body.items():
            if key == "low_res_frames":
                # base64 문자열 리스트 → bytes 리스트
                task[key] = [
                    base64.b64decode(f) if isinstance(f, str) else f
                    for f in value
                ]
            else:
                task[key] = value
        return task
