"""
Qdrant 유사 사례 검색 테스트 스크립트

실행 방법:
  cd aegis-ai-agent
  python -m scripts.test_qdrant_search
"""
import sys
import os

# 프로젝트 루트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 로컬 테스트를 위해 환경변수 설정
os.environ["QDRANT_HOST"] = "localhost"
os.environ["QDRANT_PORT"] = "6333"


def test_search():
    """유사 사례 검색 테스트"""
    print("=" * 60)
    print("🔍 AEGIS Qdrant 유사 사례 검색 테스트")
    print("=" * 60)

    try:
        from src.clients.vector_store_client import VectorStoreClient
        client = VectorStoreClient(host="localhost", port=6333)
        print(f"✓ Qdrant 연결 성공: {client.host}:{client.port}\n")
    except Exception as e:
        print(f"✗ Qdrant 연결 실패: {e}")
        return False

    # 1. 샘플 이벤트 데이터 추가
    print("📝 1. 샘플 이벤트 데이터 추가")
    print("-" * 40)

    sample_events = [
        {
            "event_id": "EVT-2026-001",
            "data": {
                "summary": "주차장 B구역에서 두 남성이 격렬하게 다투다가 한 명이 다른 한 명을 밀침",
                "event_type": "ASSAULT",
                "location": "주차장 B구역",
                "resolution": "경비원 출동하여 상황 종료, 경찰 신고",
                "timestamp": "2026-01-15T14:30:00"
            }
        },
        {
            "event_id": "EVT-2026-002",
            "data": {
                "summary": "1층 로비에서 노인 한 명이 갑자기 쓰러짐",
                "event_type": "SWOON",
                "location": "1층 로비",
                "resolution": "119 신고 후 병원 이송",
                "timestamp": "2026-01-20T09:15:00"
            }
        },
        {
            "event_id": "EVT-2026-003",
            "data": {
                "summary": "지하 1층 쓰레기장 앞에 대형 가구를 무단으로 투기하는 남성",
                "event_type": "DUMP",
                "location": "지하 1층 쓰레기장",
                "resolution": "CCTV 확인 후 해당 세대에 경고 조치",
                "timestamp": "2026-01-22T22:40:00"
            }
        },
        {
            "event_id": "EVT-2026-004",
            "data": {
                "summary": "3층 복도에서 두 여성이 언쟁 후 한 명이 상대방을 폭행",
                "event_type": "ASSAULT",
                "location": "3층 복도",
                "resolution": "경비원 현장 출동, 쌍방 분리 후 경찰 인계",
                "timestamp": "2026-01-25T18:20:00"
            }
        },
        {
            "event_id": "EVT-2026-005",
            "data": {
                "summary": "지하 주차장에서 차량 유리창이 깨진 채 발견됨",
                "event_type": "VANDALISM",
                "location": "지하 주차장 C구역",
                "resolution": "차량 소유자에게 연락, CCTV 확인 중",
                "timestamp": "2026-01-28T07:30:00"
            }
        }
    ]

    for event in sample_events:
        success = client.add_event(event["event_id"], event["data"])
        status = "✓" if success else "✗"
        print(f"  {status} {event['event_id']}: {event['data']['summary'][:40]}...")

    print()

    # 2. 유사 사례 검색 테스트
    print("🔎 2. 유사 사례 검색 테스트")
    print("-" * 40)

    test_queries = [
        "두 사람이 싸우고 있다",
        "사람이 쓰러져 있다",
        "쓰레기를 버리고 있다",
        "차량에 손상이 발생했다"
    ]

    for query in test_queries:
        print(f"\n📌 쿼리: \"{query}\"")
        results = client.search_similar_events(query, limit=3, min_score=0.3)

        if results:
            for i, result in enumerate(results, 1):
                score = result["score"]
                data = result["data"]
                print(f"   {i}. [{score:.2%}] {data.get('summary', 'N/A')[:50]}...")
                print(f"      유형: {data.get('event_type')}, 위치: {data.get('location')}")
        else:
            print("   결과 없음")

    print()

    # 3. 이벤트 타입 필터 검색 테스트
    print("🏷️ 3. 이벤트 타입 필터 검색 (ASSAULT만)")
    print("-" * 40)

    results = client.search_similar_events(
        "폭력 상황",
        limit=5,
        event_type="ASSAULT",
        min_score=0.2
    )

    if results:
        for i, result in enumerate(results, 1):
            score = result["score"]
            data = result["data"]
            print(f"  {i}. [{score:.2%}] {data.get('summary', 'N/A')[:50]}...")
    else:
        print("  결과 없음")

    print()

    # 4. 통계 확인
    print("📊 4. Qdrant 컬렉션 통계")
    print("-" * 40)

    stats = client.get_stats()
    for collection, stat in stats.items():
        print(f"  - {collection}: {stat.get('points_count', 0)}개 포인트")

    print("\n" + "=" * 60)
    print("✅ 테스트 완료!")
    print("=" * 60)

    return True


if __name__ == "__main__":
    test_search()

