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
    - 파일은 '{버킷}/temp/{event_id}.mp4' 경로로 저장됩니다.
    - 반환값은 백엔드에서 즉시 사용할 수 있도록 '/clips/temp/ID.mp4'와 같은 
      버킷명이 포함된 절대 경로 형태를 따릅니다.
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
        
        # S3 클라이언트 초기화: endpoint_url이 있으면 MinIO로, 없으면 AWS로 동작합니다.
        self.s3_client = boto3.client(
            's3',
            endpoint_url=config.s3_endpoint,
            aws_access_key_id=config.s3_access_key,
            aws_secret_access_key=config.s3_secret_key,
            use_ssl=config.s3_secure,
            config=BotoConfig(signature_version='s3v4'),
            region_name='us-east-1'
        )
        
        # 시스템 시작 시 버킷 존재 여부를 체크하여 데이터 누락을 방지합니다.
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
        생성된 MP4 영상을 업로드하고 접근 경로를 반환합니다.

        Args:
            file_obj: MP4 데이터가 담긴 BytesIO (메모리 객체)
            event_id: 파일 이름의 기준이 되는 이벤트 고유 ID
        """
        object_name = f"{self.temp_path}/{event_id}.mp4"
        
        try:
            # BytesIO 객체의 포인터를 처음으로 되돌려 모든 데이터를 업로드하도록 보장합니다.
            file_obj.seek(0)
            
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=object_name,
                Body=file_obj,
                ContentType='video/mp4'
            )
            
            # 백엔드(Spring)와 약속된 형식인 '/버킷명/경로' 형태로 반환합니다.
            full_path = f"/{self.bucket_name}/{object_name}"
            self.logger.info(f"클립 업로드 성공: {full_path}")
            return full_path
            
        except Exception as e:
            self.logger.error(f"클립 업로드 실패 ({event_id}): {e}")
            return None
