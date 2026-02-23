"""
Step 4: 컬렉션 내 모든 레코드 삭제

이 스크립트는 Qdrant 컬렉션의 모든 레코드(포인트)를 삭제합니다.
컬렉션 자체는 유지되며, 레코드만 비워집니다.

실행 방법:
    cd aegis-ai-agent
    python -m scripts.4_delete_records

옵션:
    python -m scripts.4_delete_records --manuals       # manuals 컬렉션만
    python -m scripts.4_delete_records --events        # past_events 컬렉션만
    python -m scripts.4_delete_records --collection my_col  # 특정 컬렉션 지정
"""
import sys
import os
import argparse

# 프로젝트 루트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import Config
from src.clients.vector_store_client import VectorStoreClient


def clear_collection(client: VectorStoreClient, collection_name: str) -> bool:
    """컬렉션 내 모든 레코드를 삭제합니다."""
    if not client.collection_exists(collection_name):
        print(f"  [건너뜀] '{collection_name}' 컬렉션이 존재하지 않습니다.")
        return False

    # 삭제 전 레코드 수 확인
    info = client.get_collection_info(collection_name)
    before_count = info["points_count"] if info else 0

    if before_count == 0:
        print(f"  [건너뜀] '{collection_name}': 이미 비어있음 (0개)")
        return True

    # 확인 프롬프트
    answer = input(f"  '{collection_name}' 컬렉션의 {before_count}개 레코드를 모두 삭제할까요? (y/N): ")
    if answer.lower() != "y":
        print(f"  [취소] '{collection_name}' 삭제 취소됨")
        return False

    # 삭제 실행
    if client.clear_collection(collection_name):
        print(f"  [완료] '{collection_name}': {before_count}개 레코드 삭제됨")
        return True
    else:
        print(f"  [실패] '{collection_name}' 레코드 삭제 실패")
        return False


def main():
    parser = argparse.ArgumentParser(description="Qdrant 컬렉션 내 모든 레코드 삭제")
    parser.add_argument("--manuals", action="store_true", help="manuals 컬렉션 레코드 삭제")
    parser.add_argument("--events", action="store_true", help="past_events 컬렉션 레코드 삭제")
    parser.add_argument("--collection", type=str, help="특정 컬렉션 이름 지정")
    args = parser.parse_args()

    print("=" * 60)
    print("Step 4: 컬렉션 내 모든 레코드 삭제")
    print("=" * 60)

    # 클라이언트 초기화
    try:
        config = Config()
        client = VectorStoreClient(config)
        print(f"Qdrant 연결 성공: {client.qdrant_host}:{client.qdrant_port}")
    except Exception as e:
        print(f"[실패] 초기화 실패: {e}")
        return

    # 삭제 전 상태 출력
    print("\n[삭제 전 상태]")
    stats = client.get_stats()
    if stats:
        for name, stat in stats.items():
            print(f"  - {name}: {stat['points_count']}개 문서")
    else:
        print("  (컬렉션 없음)")

    print()

    # 대상 컬렉션 결정
    if args.collection:
        targets = [args.collection]
    elif args.manuals or args.events:
        targets = []
        if args.manuals:
            targets.append("manuals")
        if args.events:
            targets.append("past_events")
    else:
        # 기본: 둘 다
        targets = ["manuals", "past_events"]

    # 레코드 삭제
    print("[레코드 삭제]")
    print("-" * 40)
    success_count = 0
    for target in targets:
        if clear_collection(client, target):
            success_count += 1

    # 결과 출력
    print()
    print("=" * 60)
    print(f"레코드 삭제 완료! ({success_count}/{len(targets)}개 컬렉션)")
    print("=" * 60)

    # 삭제 후 상태 출력
    print("\n현재 Qdrant 컬렉션 상태:")
    stats = client.get_stats()
    if stats:
        for name, stat in stats.items():
            print(f"  - {name}: {stat['points_count']}개 문서")
    else:
        print("  (컬렉션 없음)")

    print("\n레코드를 다시 추가하려면: python -m scripts.2_add_documents")


if __name__ == "__main__":
    main()
