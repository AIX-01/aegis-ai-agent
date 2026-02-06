"""
Step 1: Qdrant 컬렉션 생성

이 스크립트는 Qdrant에 예시 컬렉션을 생성합니다.
벡터 DB를 처음 사용할 때 이 스크립트를 먼저 실행하세요.

실행 방법:
    cd aegis-ai-agent
    python -m scripts.1_create_collection

사전 준비:
    1. .env 파일에 OPENAI_API_KEY 설정
    2. Qdrant 컨테이너 실행 (aegis-infra docker-compose)
"""
import sys
import os

# 프로젝트 루트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import Config
from src.clients.vector_store_client import VectorStoreClient


def create_collections():
    """예시 컬렉션들을 생성합니다."""
    print("=" * 60)
    print("Step 1: Qdrant 컬렉션 생성")
    print("=" * 60)

    # 클라이언트 초기화
    try:
        config = Config()
        client = VectorStoreClient(config)
        print(f"Qdrant 연결 성공: {client.qdrant_host}:{client.qdrant_port}")
        print(f"임베딩 모델: {client.embedding_model}")
        print(f"벡터 차원: {client.embedding_dimension}")
    except Exception as e:
        print(f"[실패] Qdrant 연결 실패: {e}")
        print("\n문제 해결:")
        print("  1. .env 파일에 OPENAI_API_KEY가 설정되어 있는지 확인")
        print("  2. Qdrant 컨테이너가 실행 중인지 확인")
        print("     cd aegis-infra && docker-compose up -d qdrant")
        return False

    print()

    # 생성할 컬렉션 목록
    collections = [
        ("manuals", "대응 매뉴얼 컬렉션"),
        ("past_events", "과거 이벤트 컬렉션"),
    ]

    print("컬렉션 생성 중...\n")
    success_count = 0

    for collection_name, description in collections:
        # 이미 존재하는지 확인
        if client.collection_exists(collection_name):
            print(f"  [존재] {collection_name}: {description}")
            success_count += 1
        else:
            # 새로 생성
            if client.create_collection(collection_name):
                print(f"  [생성] {collection_name}: {description}")
                success_count += 1
            else:
                print(f"  [실패] {collection_name}: {description}")

    print()
    print("=" * 60)
    print(f"컬렉션 생성 완료! ({success_count}/{len(collections)})")
    print("=" * 60)

    # 현재 상태 출력
    print("\n현재 Qdrant 컬렉션 상태:")
    stats = client.get_stats()
    if stats:
        for name, stat in stats.items():
            print(f"  - {name}: {stat['points_count']}개 문서")
    else:
        print("  (컬렉션 없음)")

    print("\n다음 단계: python -m scripts.2_add_documents")
    return True


if __name__ == "__main__":
    create_collections()
