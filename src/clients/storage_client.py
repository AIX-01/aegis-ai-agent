"""
S3 저장소 클라이언트 모듈
"""
import logging
import io
import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

class StorageClient:
    """
    S3 표준 API를 사용하여 영상 클립을 업로드하는 클라이언트입니다.
    
    [호환성: AWS S3 & MinIO]
    - 'endpoint_url' 설정을 통해 AWS 공식 S3뿐만 아니라 로컬 MinIO와도 완벽히 호환됩니다.
    - Boto3의 's3v4' 시그니처 버전을 사용하여 최신 보안 규격을 따릅니다.

    [업로드 경로 규칙]
    - Python: aegis 버킷의 temp/clips/{event_id}.mp4 에 임시 저장
    - Spring: POST /events/{id}/clip 호출 시 clips/{event_id}.mp4 로 이동
    """

    def __init__(self, config):
        """
        Args:
            config: 시스템 설정 (s3_endpoint, s3_access_key, s3_bucket 등)
        """
        self.config = config
        self.logger = logging.getLogger("aegis-agent.storage")
        
        self.bucket_name = config.s3_bucket
        self.temp_path = config.clip_temp_path.strip("/")
        
        # S3 클라이언트 초기화
        self.s3_client = boto3.client(
            's3',
            endpoint_url=config.s3_endpoint,
            aws_access_key_id=config.s3_access_key,
            aws_secret_access_key=config.s3_secret_key,
            use_ssl=config.s3_secure,
            config=BotoConfig(signature_version='s3v4'),
            region_name='us-east-1'
        )
        
        # 버킷 존재 여부 확인 및 생성 (aegis 버킷)
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        """aegis 버킷이 없으면 생성합니다."""
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            self.logger.info(f"버킷 확인 완료: {self.bucket_name}")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                self.logger.info(f"버킷 '{self.bucket_name}'이 없어 새로 생성합니다.")
                self.s3_client.create_bucket(Bucket=self.bucket_name)
                self.logger.info(f"버킷 생성 완료: {self.bucket_name}")
            else:
                self.logger.error(f"버킷 확인 중 오류 발생: {e}")

    def upload_clip(self, file_obj: io.BytesIO, event_id: str) -> str:
        """
        생성된 MP4 영상을 임시 경로에 업로드합니다.

        Args:
            file_obj: MP4 데이터가 담긴 BytesIO
            event_id: 이벤트 고유 ID

        Returns:
            S3 키 (예: temp/clips/{event_id}.mp4)
        """
        object_key = f"{self.temp_path}/{event_id}.mp4"

        try:
            file_obj.seek(0)
            
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=object_key,
                Body=file_obj,
                ContentType='video/mp4'
            )
            
            self.logger.info(f"클립 업로드 성공: {self.bucket_name}/{object_key}")
            return object_key

        except Exception as e:
            self.logger.error(f"클립 업로드 실패 ({event_id}): {e}")
            return None
