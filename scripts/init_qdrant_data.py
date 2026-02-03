"""
Qdrant에 초기 매뉴얼 데이터를 추가하는 스크립트

실행 방법:
  docker exec -it aegis-agent python -m scripts.init_qdrant_data

  또는 로컬에서:
  cd aegis-ai-agent
  python -m scripts.init_qdrant_data
"""
import sys
import os

# 프로젝트 루트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.clients.vector_store_client import VectorStoreClient


def init_manuals():
    """대응 매뉴얼 초기 데이터를 추가합니다."""
    print("=" * 60)
    print("📚 AEGIS 대응 매뉴얼 초기화")
    print("=" * 60)

    try:
        client = VectorStoreClient()
        print(f"✓ Qdrant 연결 성공: {client.host}:{client.port}\n")
    except Exception as e:
        print(f"✗ Qdrant 연결 실패: {e}")
        print("  → Qdrant 컨테이너가 실행 중인지 확인하세요.")
        print("  → docker-compose up -d qdrant")
        return

    manuals = [
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
            "manual_id": "manual_burglary_001",
            "title": "절도 사건 대응 절차",
            "content": """
1. 즉시 경찰(112) 신고
2. 용의자의 도주 경로 CCTV 추적
3. 관련 영상 즉시 백업 (MinIO 저장)
4. 현장 접근 제한 및 증거 보존
5. 피해자 확인 및 피해 목록 작성
6. 출입구 CCTV 특별 모니터링
7. 경찰 도착 시 상황 브리핑
            """.strip(),
            "category": "emergency",
            "event_types": ["BURGLARY"],
            "priority": "high"
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
            "manual_id": "manual_vandalism_001",
            "title": "기물 파손 대응 절차",
            "content": """
1. 현장 상황 확인 및 기록
2. 파손자 신원 확인 (CCTV 확인)
3. 추가 파손 방지를 위한 현장 통제
4. 파손 내역 사진 촬영 및 기록
5. 관리사무소에 보고
6. 피해 규모에 따라 경찰 신고 검토
7. 보험 처리를 위한 서류 준비
8. 수리 일정 조율
            """.strip(),
            "category": "violation",
            "event_types": ["VANDALISM"],
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
        {
            "manual_id": "manual_suspicious_001",
            "title": "의심 행동 감시 절차",
            "content": """
1. 해당 인물 지속 모니터링
2. 이동 경로 추적 및 기록
3. 특이 행동 발생 시 즉시 보고
4. 경비원 대기 상태 유지
5. 상황 악화 시 긴급 대응 절차로 전환
6. 관련 영상 클립 저장
7. 30분 이상 의심 행동 지속 시 현장 확인
            """.strip(),
            "category": "monitoring",
            "event_types": ["SUSPICIOUS"],
            "priority": "low"
        },
        {
            "manual_id": "manual_general_001",
            "title": "일반 이상 행동 대응 절차",
            "content": """
1. 상황 확인 및 분류
2. 위험도에 따른 대응 수준 결정
3. 관련 부서에 알림
4. 현장 상황 지속 모니터링
5. 필요시 경비원 현장 확인
6. 상황 종료 후 보고서 작성
7. 재발 방지 대책 검토
            """.strip(),
            "category": "general",
            "event_types": ["UNKNOWN"],
            "priority": "medium"
        }
    ]

    print("매뉴얼 데이터 추가 중...\n")
    success_count = 0

    for manual in manuals:
        manual_id = manual.pop("manual_id")
        if client.add_manual(manual_id, manual):
            print(f"  ✓ {manual['title']}")
            success_count += 1
        else:
            print(f"  ✗ {manual['title']} (실패)")

    print(f"\n{'=' * 60}")
    print(f"✅ 매뉴얼 데이터 추가 완료! ({success_count}/{len(manuals)})")

    # 통계 확인
    stats = client.get_stats()
    print(f"\n📊 현재 Qdrant 통계:")
    for collection, stat in stats.items():
        print(f"  - {collection}: {stat['points_count']}개")

    print("=" * 60)


def init_sample_events():
    """샘플 과거 이벤트를 추가합니다."""
    print("\n" + "=" * 60)
    print("📝 샘플 과거 이벤트 초기화")
    print("=" * 60)

    try:
        client = VectorStoreClient()
    except Exception as e:
        print(f"✗ Qdrant 연결 실패: {e}")
        return

    sample_events = [
        {
            "event_id": "sample_evt_001",
            "data": {
                "camera_id": "cam_entrance_01",
                "camera_name": "정문 카메라",
                "camera_location": "아파트 정문",
                "event_type": "ASSAULT",
                "risk_level": "ABNORMAL",
                "risk_score": 0.85,
                "summary": "두 남성이 정문 앞에서 격렬하게 다투다 한 명이 상대방을 밀침",
                "occurred_at": "2026-01-15 14:30:00",
                "resolution": "경비원 출동, 당사자 분리, 경찰 신고"
            }
        },
        {
            "event_id": "sample_evt_002",
            "data": {
                "camera_id": "cam_parking_02",
                "camera_name": "지하주차장 B2",
                "camera_location": "지하 2층 주차장",
                "event_type": "SWOON",
                "risk_level": "ABNORMAL",
                "risk_score": 0.92,
                "summary": "노인 1명이 주차장에서 갑자기 쓰러짐, 의식 있으나 움직이지 못함",
                "occurred_at": "2026-01-20 09:15:00",
                "resolution": "119 신고, 경비원 응급조치, 구급차 이송"
            }
        },
        {
            "event_id": "sample_evt_003",
            "data": {
                "camera_id": "cam_trash_01",
                "camera_name": "쓰레기장 카메라",
                "camera_location": "단지 내 쓰레기장",
                "event_type": "DUMP",
                "risk_level": "ABNORMAL",
                "risk_score": 0.65,
                "summary": "야간에 외부인이 대형 폐기물을 무단 투기",
                "occurred_at": "2026-01-25 23:45:00",
                "resolution": "CCTV 캡처, 관리사무소 보고, 경고문 발송"
            }
        },
        {
            "event_id": "sample_evt_004",
            "data": {
                "camera_id": "cam_lobby_01",
                "camera_name": "로비 카메라",
                "camera_location": "1층 로비",
                "event_type": "VANDALISM",
                "risk_level": "ABNORMAL",
                "risk_score": 0.72,
                "summary": "청소년 2명이 로비 화분을 넘어뜨리고 도주",
                "occurred_at": "2026-01-28 16:20:00",
                "resolution": "CCTV로 신원 확인, 보호자 연락, 변상 처리"
            }
        }
    ]

    print("샘플 이벤트 추가 중...\n")
    success_count = 0

    for event in sample_events:
        if client.add_event(event["event_id"], event["data"]):
            print(f"  ✓ [{event['data']['event_type']}] {event['data']['summary'][:40]}...")
            success_count += 1
        else:
            print(f"  ✗ {event['event_id']} (실패)")

    print(f"\n✅ 샘플 이벤트 추가 완료! ({success_count}/{len(sample_events)})")
    print("=" * 60)


def test_search():
    """검색 기능을 테스트합니다."""
    print("\n" + "=" * 60)
    print("🔍 검색 기능 테스트")
    print("=" * 60)

    try:
        client = VectorStoreClient()
    except Exception as e:
        print(f"✗ Qdrant 연결 실패: {e}")
        return

    # 유사 이벤트 검색 테스트
    print("\n[테스트 1] 유사 이벤트 검색: '사람이 싸움을 함'")
    results = client.search_similar_events("사람이 싸움을 함", limit=2)
    for r in results:
        print(f"  → [{r['data'].get('event_type')}] {r['data'].get('summary', 'N/A')[:50]}... (유사도: {r['score']:.2%})")

    # 매뉴얼 검색 테스트
    print("\n[테스트 2] 매뉴얼 검색: '쓰러진 사람 대응'")
    results = client.search_manuals("쓰러진 사람 대응", limit=2)
    for r in results:
        print(f"  → {r['data'].get('title', 'N/A')} (관련도: {r['score']:.2%})")

    print("\n✅ 검색 테스트 완료!")
    print("=" * 60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AEGIS Qdrant 초기 데이터 설정")
    parser.add_argument("--manuals", action="store_true", help="매뉴얼 데이터만 추가")
    parser.add_argument("--events", action="store_true", help="샘플 이벤트만 추가")
    parser.add_argument("--test", action="store_true", help="검색 테스트 실행")
    parser.add_argument("--all", action="store_true", help="모든 작업 실행 (기본값)")

    args = parser.parse_args()

    # 기본값: 모든 작업 실행
    if not any([args.manuals, args.events, args.test]):
        args.all = True

    if args.manuals or args.all:
        init_manuals()

    if args.events or args.all:
        init_sample_events()

    if args.test or args.all:
        test_search()

