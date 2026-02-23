"""
Step 2: 예시 문서 추가

이 스크립트는 Qdrant 컬렉션에 예시 문서들을 추가합니다.
1_create_collection.py 실행 후 이 스크립트를 실행하세요.

실행 방법:
    cd aegis-ai-agent
    python -m scripts.2_add_documents

옵션:
    python -m scripts.2_add_documents --manuals   # 매뉴얼만 추가
    python -m scripts.2_add_documents --events    # 이벤트만 추가
"""
import sys
import os
import argparse

# 프로젝트 루트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import Config
from src.clients.vector_store_client import VectorStoreClient


# 예시 매뉴얼 데이터
SAMPLE_MANUALS = [
    {
        "manual_id": "manual_assault_001",
        "title": "폭행 사건 대응 절차",
        "content": """
1. 즉시 상황실에 보고
2. CCTV로 현장 모니터링 지속
3. 경비원 2명 이상 현장 출동
4. 필요시 경찰(112) 신고
5. 사건 경위 기록 및 관련 영상 보존
6. 피해자 응급조치 확인
7. 목격자 진술 확보
        """.strip(),
        "category": "emergency",
        "event_types": ["ASSAULT"],
        "priority": "high"
    },
    {
        "manual_id": "manual_swoon_001",
        "title": "실신/쓰러짐 사고 대응 절차",
        "content": """
1. 즉시 119 신고
2. 경비원 즉시 현장 출동
3. 환자 상태 확인 (의식, 호흡, 맥박)
4. 기도 확보 및 회복 자세 유지
5. 필요시 심폐소생술(CPR) 실시
6. 구급차 도착 시까지 환자 관찰 지속
7. CCTV 영상 보존 (사고 원인 파악용)
8. 보호자/비상연락처 확인 및 연락
        """.strip(),
        "category": "emergency",
        "event_types": ["SWOON"],
        "priority": "critical"
    },
    {
        "manual_id": "manual_dump_001",
        "title": "무단 투기 대응 절차",
        "content": """
1. 투기자 신원 확인 (CCTV 확인)
2. 관리사무소에 보고
3. 투기 일시, 장소, 내용물 기록
4. 해당 구역 관리자에게 알림
5. 반복 적발 시 경고문 발송
6. 3회 이상 적발 시 과태료 부과 절차 진행
7. 정기 순찰 강화 요청
        """.strip(),
        "category": "violation",
        "event_types": ["DUMP"],
        "priority": "medium"
    },
    {
        "manual_id": "manual_fire_001",
        "title": "화재 발생 시 대응 절차",
        "content": """
1. 화재경보 즉시 작동
2. 즉시 소방서(119) 신고
3. 초기 진압 가능 시 소화기 사용
4. 엘리베이터 사용 금지, 비상계단 이용
5. 대피 방송 및 유도
6. 대피 인원 확인 (명부 대조)
7. 소방대 도착 시 상황 브리핑
8. 2차 피해 방지 조치
        """.strip(),
        "category": "emergency",
        "event_types": ["FIRE"],
        "priority": "critical"
    },
]

# 예시 과거 이벤트 데이터
SAMPLE_EVENTS = [
    {
        "event_id": "EVT-2026-001",
        "summary": "주차장 B구역에서 두 남성이 격렬하게 다투다가 한 명이 다른 한 명을 밀침",
        "event_type": "ASSAULT",
        "location": "주차장 B구역",
        "resolution": "경비원 출동하여 상황 종료, 경찰 신고",
        "timestamp": "2026-01-15T14:30:00"
    },
    {
        "event_id": "EVT-2026-002",
        "summary": "1층 로비에서 노인 한 명이 갑자기 쓰러짐, 의식은 있으나 움직이지 못함",
        "event_type": "SWOON",
        "location": "1층 로비",
        "resolution": "119 신고 후 병원 이송",
        "timestamp": "2026-01-20T09:15:00"
    },
    {
        "event_id": "EVT-2026-003",
        "summary": "지하 1층 쓰레기장 앞에 대형 가구를 무단으로 투기하는 남성 발견",
        "event_type": "DUMP",
        "location": "지하 1층 쓰레기장",
        "resolution": "CCTV 확인 후 해당 세대에 경고 조치",
        "timestamp": "2026-01-22T22:40:00"
    },
    {
        "event_id": "EVT-2026-004",
        "summary": "3층 복도에서 두 여성이 언쟁 후 한 명이 상대방의 머리채를 잡음",
        "event_type": "ASSAULT",
        "location": "3층 복도",
        "resolution": "경비원 현장 출동, 쌍방 분리 후 경찰 인계",
        "timestamp": "2026-01-25T18:20:00"
    },
    {
        "event_id": "EVT-2026-005",
        "summary": "지하 주차장에서 차량 유리창이 깨진 채 발견됨, 차량 털이 의심",
        "event_type": "VANDALISM",
        "location": "지하 주차장 C구역",
        "resolution": "차량 소유자에게 연락, CCTV 확인 중",
        "timestamp": "2026-01-28T07:30:00"
    },
]


def add_manuals(client: VectorStoreClient) -> int:
    """매뉴얼 데이터를 추가합니다."""
    print("\n[매뉴얼 데이터 추가]")
    print("-" * 40)

    # 컬렉션 존재 확인
    if not client.collection_exists("manuals"):
        print("  [오류] 'manuals' 컬렉션이 없습니다.")
        print("  먼저 python -m scripts.1_create_collection 실행하세요.")
        return 0

    success_count = 0
    for manual in SAMPLE_MANUALS:
        manual_id = manual["manual_id"]
        # content 필드를 임베딩하여 저장
        if client.add_document(
            collection_name="manuals",
            doc_id=manual_id,
            data=manual,
            text_field="content"
        ):
            print(f"  [추가] {manual['title']}")
            success_count += 1
        else:
            print(f"  [실패] {manual['title']}")

    print(f"\n  매뉴얼 {success_count}/{len(SAMPLE_MANUALS)}개 추가 완료")
    return success_count


def add_events(client: VectorStoreClient) -> int:
    """과거 이벤트 데이터를 추가합니다."""
    print("\n[과거 이벤트 데이터 추가]")
    print("-" * 40)

    # 컬렉션 존재 확인
    if not client.collection_exists("past_events"):
        print("  [오류] 'past_events' 컬렉션이 없습니다.")
        print("  먼저 python -m scripts.1_create_collection 실행하세요.")
        return 0

    success_count = 0
    for event in SAMPLE_EVENTS:
        event_id = event["event_id"]
        # summary 필드를 임베딩하여 저장
        if client.add_document(
            collection_name="past_events",
            doc_id=event_id,
            data=event,
            text_field="summary"
        ):
            print(f"  [추가] [{event['event_type']}] {event['summary'][:40]}...")
            success_count += 1
        else:
            print(f"  [실패] {event_id}")

    print(f"\n  이벤트 {success_count}/{len(SAMPLE_EVENTS)}개 추가 완료")
    return success_count


def main():
    parser = argparse.ArgumentParser(description="Qdrant에 예시 문서 추가")
    parser.add_argument("--manuals", action="store_true", help="매뉴얼만 추가")
    parser.add_argument("--events", action="store_true", help="이벤트만 추가")
    args = parser.parse_args()

    # 기본: 둘 다 추가
    if not args.manuals and not args.events:
        args.manuals = True
        args.events = True

    print("=" * 60)
    print("Step 2: 예시 문서 추가")
    print("=" * 60)

    # 클라이언트 초기화
    try:
        config = Config()
        client = VectorStoreClient(config)
        print(f"Qdrant 연결 성공: {client.qdrant_host}:{client.qdrant_port}")
    except Exception as e:
        print(f"[실패] 초기화 실패: {e}")
        return

    # 문서 추가
    total_success = 0
    total_count = 0

    if args.manuals:
        total_success += add_manuals(client)
        total_count += len(SAMPLE_MANUALS)

    if args.events:
        total_success += add_events(client)
        total_count += len(SAMPLE_EVENTS)

    # 결과 출력
    print()
    print("=" * 60)
    print(f"문서 추가 완료! (총 {total_success}/{total_count}개)")
    print("=" * 60)

    # 현재 상태 출력
    print("\n현재 Qdrant 컬렉션 상태:")
    stats = client.get_stats()
    for name, stat in stats.items():
        print(f"  - {name}: {stat['points_count']}개 문서")

    print("\n다음 단계: python -m scripts.3_search_test")


if __name__ == "__main__":
    main()
