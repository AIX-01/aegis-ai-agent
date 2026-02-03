"""
MinIO (S3 호환) 저장소 클라이언트 모듈
"""
import logging
import io
import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

class StorageClient:
    """MinIO 저장소에 영상 클립을 업로드하는 클라이언트"""

    def __init__(self, config):
        """
        Args:
            config: 시스템 설정 (minio_endpoint, access_key 등)
        """
        self.config = config
        self.logger = logging.getLogger("aegis-agent.storage")
        
        self.bucket_name = config.minio_bucket
        self.temp_path = config.clip_temp_path.strip("/")
        
        # S3 클라이언트 초기화 (MinIO 설정 적용)
        self.s3_client = boto3.client(
            's3',
            endpoint_url=config.minio_endpoint,
            aws_access_key_id=config.minio_access_key,
            aws_secret_access_key=config.minio_secret_key,
            config=BotoConfig(signature_version='s3v4'),
            region_name='us-east-1' # MinIO는 region이 필수적이지 않으나 boto3 호환을 위해 설정
        )
        
        # 시작 시 버킷 존재 여부 확인 및 생성
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        """버킷이 없으면 생성합니다."""
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                self.logger.info(f"버킷 '{self.bucket_name}'이 없어 새로 생성합니다.")
                self.s3_client.create_bucket(Bucket=self.bucket_name)
            else:
                self.logger.error(f"버킷 확인 중 오류 발생: {e}")

    def upload_clip(self, file_obj: io.BytesIO, event_id: str) -> str:
        """
        MP4 메모리 객체를 MinIO의 /clips/temp/{event_id}.mp4 경로로 업로드합니다.

        Args:
            file_obj: 업로드할 MP4 데이터 (BytesIO)
            event_id: 파일명이 될 이벤트 ID

        Returns:
            저장된 객체의 상대 경로 (성공 시) 또는 None
        """
        object_name = f"{self.temp_path}/{event_id}.mp4"
        
        try:
            # 포인터가 처음인지 확인
            file_obj.seek(0)
            
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=object_name,
                Body=file_obj,
                ContentType='video/mp4'
            )
            
            self.logger.info(f"클립 업로드 성공: {object_name}")
            return f"/{object_name}" # 절대 경로 형태로 반환 (요구사항 반영)
            
        except Exception as e:
            self.logger.error(f"클립 업로드 실패 ({event_id}): {e}")
            return None
