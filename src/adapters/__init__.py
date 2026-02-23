"""
Adapters 패키지: 인프라 추상화 계층

로컬(Docker Compose)과 AWS(ECS Fargate) 환경 간 전환을 위한 어댑터.
- QueueAdapter: queue.Queue (local) / SQS (AWS)
- EFS Buffer: 패킷 공유를 위한 EFS 읽기/쓰기
"""

from .queue_adapter import QueueAdapter, LocalQueueAdapter, SQSQueueAdapter
from .efs_buffer import EFSPacketWriter, EFSPacketReader

__all__ = [
    "QueueAdapter",
    "LocalQueueAdapter",
    "SQSQueueAdapter",
    "EFSPacketWriter",
    "EFSPacketReader",
]
