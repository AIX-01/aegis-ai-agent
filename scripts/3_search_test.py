"""
Step 3: 벡터 검색 테스트

이 스크립트는 Qdrant에 저장된 문서를 검색하는 테스트를 실행합니다.
2_add_documents.py 실행 후 이 스크립트를 실행하세요.

실행 방법:
    cd aegis-ai-agent
    python -m scripts.3_search_test
"""
import sys
import os

# 프로젝트 루트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import Config
from src.clients.vector_store_client import VectorStoreClient


def test_manual_search(client: VectorStoreClient):
    """매뉴얼 검색 테스트"""
    print("\n[테스트 1] 매뉴얼 검색")
    print("-" * 40)

    if not client.collection_exists("manuals"):
        print("  [건너뜀] 'manuals' 컬렉션이 없습니다.")
        return

    test_queries = [
        "사람이 쓰러졌을 때 어떻게 해야 하나요?",
        "폭행 사건 발생 시 대응 방법",
        "불이 났을 때 대피 절차",
        "쓰레기 무단 투기 처리",
    ]

    for query in test_queries:
        print(f"\n  Query: \"{query}\"")
        results = client.search(
            collection_name="manuals",
            query=query,
            limit=2,
            min_score=0.3
        )

        if results:
            for i, r in enumerate(results, 1):
                title = r["data"].get("title", "N/A")
                score = r["score"]
                print(f"    {i}. [{score:.1%}] {title}")
        else:
            print("    (결과 없음)")


def test_event_search(client: VectorStoreClient):
    """과거 이벤트 검색 테스트"""
    print("\n[테스트 2] 과거 이벤트 검색")
    print("-" * 40)

    if not client.collection_exists("past_events"):
        print("  [건너뜀] 'past_events' 컬렉션이 없습니다.")
        return

    test_queries = [
        "두 사람이 싸우고 있다",
        "누군가 쓰러져 있다",
        "쓰레기를 버리는 사람",
        "차량 파손",
    ]

    for query in test_queries:
        print(f"\n  Query: \"{query}\"")
        results = client.search(
            collection_name="past_events",
            query=query,
            limit=2,
            min_score=0.3
        )

        if results:
            for i, r in enumerate(results, 1):
                summary = r["data"].get("summary", "N/A")[:50]
                event_type = r["data"].get("event_type", "N/A")
                score = r["score"]
                print(f"    {i}. [{score:.1%}] [{event_type}] {summary}...")
        else:
            print("    (결과 없음)")


def test_filtered_search(client: VectorStoreClient):
    """필터를 사용한 검색 테스트"""
    print("\n[테스트 3] 필터 검색 (이벤트 타입: ASSAULT)")
    print("-" * 40)

    if not client.collection_exists("past_events"):
        print("  [건너뜀] 'past_events' 컬렉션이 없습니다.")
        return

    query = "폭력 상황"
    print(f"\n  Query: \"{query}\" (필터: event_type=ASSAULT)")

    results = client.search(
        collection_name="past_events",
        query=query,
        limit=3,
        filters={"event_type": "ASSAULT"},
        min_score=0.2
    )

    if results:
        for i, r in enumerate(results, 1):
            summary = r["data"].get("summary", "N/A")[:50]
            score = r["score"]
            print(f"    {i}. [{score:.1%}] {summary}...")
    else:
        print("    (결과 없음)")


def show_stats(client: VectorStoreClient):
    """컬렉션 통계 출력"""
    print("\n[컬렉션 통계]")
    print("-" * 40)

    stats = client.get_stats()
    if stats:
        for name, stat in stats.items():
            print(f"  - {name}: {stat['points_count']}개 문서")
    else:
        print("  (컬렉션 없음)")


def main():
    print("=" * 60)
    print("Step 3: 벡터 검색 테스트")
    print("=" * 60)

    # 클라이언트 초기화
    try:
        config = Config()
        client = VectorStoreClient(config)
        print(f"Qdrant 연결 성공: {client.qdrant_host}:{client.qdrant_port}")
    except Exception as e:
        print(f"[실패] 초기화 실패: {e}")
        return

    # 통계 확인
    show_stats(client)

    # 검색 테스트 실행
    test_manual_search(client)
    test_event_search(client)
    test_filtered_search(client)

    print()
    print("=" * 60)
    print("검색 테스트 완료!")
    print("=" * 60)
    print("\n이제 VectorStoreClient를 사용하여 자신만의 컬렉션을 만들어보세요.")
    print("참고: src/clients/vector_store_client.py")


if __name__ == "__main__":
    main()
