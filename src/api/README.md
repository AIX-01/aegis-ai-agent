# Mock 서버 단독 실행 (개발/테스트용)

```bash
cd aegis-ai-agent/src

# 모든 Mock 서버 실행 (기본값, --all과 동일)
python -m api.mock_server

# 특정 서버만 실행
python -m api.mock_server --vlm         # VLM Mock 서버만 (포트 8001)
python -m api.mock_server --backend     # 백엔드 Mock 서버만 (포트 8088)
python -m api.mock_server --all         # 모든 Mock 서버 (기본값)
```

> **참고:** 실제 서비스 실행 시(`python -m src.app`)에는 위 arg를 사용하지 않고,
> `config.py`의 `real_vlm`, `real_backend` 플래그로 Mock 서버 실행 여부를 제어합니다.

## Mock 서버 엔드포인트 현황

| 서버 | 포트 | 엔드포인트 | 설명 |
|------|------|-----------|------|
| VLM (`--vlm`) | 8001 | `POST /analyze` | VLM 1차 분석 (랜덤 risk_level 반환) |
| | | `GET /health` | 헬스 체크 |
| Backend (`--backend`) | 8088 | `POST /api/vlm-results` | 이벤트 생성 (UUID 발급) |
| | | `PATCH /api/vlm-results/{event_id}` | 이벤트 갱신 (분석결과+보고서+상태) |
| | | `GET /api/vlm-results/{event_id}/clip/upload-url` | 클립 업로드 URL 발급 |
| | | `PUT /api/vlm-results/{event_id}/clip/upload` | 클립 업로드 수신 |
| | | `POST /api/vlm-results/{event_id}/clip/confirm` | 클립 업로드 확정 |
| | | `GET /health` | 헬스 체크 |
