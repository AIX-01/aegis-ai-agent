"""
AEGIS AI Agent의 메인 진입점 - LangGraph 기반 분석 파이프라인 (FastAPI 기반)
"""
import argparse
import threading
import time
import asyncio
import json
from typing import Dict, Optional, List, Set
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .config import Config
from .utils import setup_logging
from .core.queue_manager import QueueManager
from .core.windowing import WindowManager
from .core.producer import FrameProducer
from .core.consumer import ConsumerPool
from .core.redis_manager import RedisManager
from .core.approval_manager import approval_manager
from .api.mock_server import MockVLMServer, MockPrecisionServer, MockBackendServer


class AegisAgent:
    """AEGIS AI Agent의 메인 오케스트레이터 - LangGraph 파이프라인"""

    def __init__(self, config: Config):
        """
        AEGIS Agent를 초기화합니다.

        Args:
            config: 시스템 설정 객체
        """
        self.config = config
        self.logger = setup_logging(config.log_level)

        # 핵심 컴포넌트
        self.queue_manager = QueueManager(max_size=config.queue_max_size)
        self.window_manager = WindowManager(config, self.queue_manager)
        
        # [신규] 카메라별 리소스 공유를 위한 딕셔너리
        self.packet_buffers = {}
        self.source_streams = {}

        # LangGraph 기반 컨슈머 풀
        self.consumer_pool = ConsumerPool(
            config=config,
            queue_manager=self.queue_manager,
            packet_buffers=self.packet_buffers,
            source_streams=self.source_streams
        )

        # 동적 스트림 설정을 위한 Redis 매니저
        self.redis_manager = RedisManager(config, self._update_producers)

        # 프로듀서 관리 (카메라 ID를 키로 사용)
        self.producers: Dict[str, FrameProducer] = {}
        self.producer_lock = threading.Lock()
        self.shutdown_event = threading.Event()

        # 모의 서버 스레드
        self.mock_vlm_server_thread = None
        self.mock_precision_server_thread = None
        self.mock_backend_server_thread = None

    def start(self):
        """모든 컴포넌트를 시작합니다."""
        self.logger.info("=" * 80)
        self.logger.info("AEGIS AI Agent - LangGraph 기반 분석 파이프라인")
        real_components = [name for name, flag in [("VLM", self.config.real_vlm), ("Precision", self.config.real_precision), ("Backend", self.config.real_backend)] if flag]
        self.logger.info(f"실제 서버: {', '.join(real_components) if real_components else '없음 (전체 Mock)'}")
        self.logger.info("=" * 80)

        self._start_mock_servers()

        self.consumer_pool.start()
        self.redis_manager.start()

        self.logger.info("Redis에서 초기 카메라 설정을 수행합니다...")
        self._update_producers()

        self.logger.info("시스템이 시작되었습니다.")

    def _start_mock_servers(self):
        """모의 모드에서 선택적으로 모의 서버를 시작합니다."""
        
        # VLM 모의 서버
        if not self.config.real_vlm:
            self.logger.info(f"모의 VLM 서버를 {self.config.mock_vlm_port} 포트에서 시작합니다.")
            mock_vlm_server = MockVLMServer(self.config.mock_vlm_port)
            self.mock_vlm_server_thread = threading.Thread(target=mock_vlm_server.run, daemon=True)
            self.mock_vlm_server_thread.start()
        else:
            self.logger.info("실제 VLM 서버를 사용합니다. (Mock VLM 서버 실행 안 함)")

        # 정밀 분석 모의 서버
        if not self.config.real_precision:
            self.logger.info(f"모의 정밀 분석 서버를 {self.config.mock_precision_port} 포트에서 시작합니다.")
            mock_precision_server = MockPrecisionServer(self.config.mock_precision_port)
            self.mock_precision_server_thread = threading.Thread(target=mock_precision_server.run, daemon=True)
            self.mock_precision_server_thread.start()
        else:
            self.logger.info("실제 정밀 분석 서버를 사용합니다. (Mock 정밀 분석 서버 실행 안 함)")

        # 백엔드 모의 서버
        if not self.config.real_backend:
            self.logger.info(f"모의 백엔드 서버를 {self.config.mock_backend_port} 포트에서 시작합니다.")
            mock_backend_server = MockBackendServer(self.config.mock_backend_port)
            self.mock_backend_server_thread = threading.Thread(target=mock_backend_server.run, daemon=True)
            self.mock_backend_server_thread.start()
        else:
            self.logger.info("실제 백엔드 서버를 사용합니다. (Mock 백엔드 서버 실행 안 함)")
        
        time.sleep(2) # 서버가 시작될 때까지 잠시 대기

    def _update_producers(self):
        """
        Redis의 최신 카메라 목록을 기반으로 프로듀서를 업데이트하는 콜백 함수입니다.
        """
        with self.producer_lock:
            self.logger.info("Redis 카메라 목록을 기반으로 프로듀서를 업데이트합니다...")
            try:
                target_cameras_list = self.redis_manager.get_analysis_cameras()
                target_cameras = {cam['id']: cam for cam in target_cameras_list if 'id' in cam}
                
                current_camera_ids = set(self.producers.keys())
                target_camera_ids = set(target_cameras.keys())

                ids_to_add = target_camera_ids - current_camera_ids
                ids_to_remove = current_camera_ids - target_camera_ids

                for cam_id in ids_to_add:
                    if self.shutdown_event.is_set(): break
                    camera_info = target_cameras[cam_id]
                    self.logger.info(f"새로운 프로듀서를 시작합니다: {cam_id} (이름: {camera_info.get('name', 'unknown')})")
                    producer = FrameProducer(
                        camera_info=camera_info,
                        config=self.config,
                        frame_callback=self.window_manager.add_frame,
                        shutdown_event=self.shutdown_event,
                        source_streams_dict=self.source_streams # 공유 딕셔너리 전달
                    )
                    
                    # PacketBuffer를 공유 딕셔너리에 등록
                    self.packet_buffers[cam_id] = producer.packet_buffer

                    producer.start()
                    self.producers[cam_id] = producer

                for cam_id in ids_to_remove:
                    self.logger.info(f"프로듀서를 중지합니다: {cam_id}")
                    producer = self.producers.pop(cam_id, None)
                    if producer:
                        producer.stop()
                    # 리소스 정리
                    self.packet_buffers.pop(cam_id, None)
                    self.source_streams.pop(cam_id, None)

                self.logger.info(f"프로듀서 업데이트 완료. 총 프로듀서 수: {len(self.producers)}")

            except Exception as e:
                self.logger.error(f"프로듀서 업데이트 중 오류 발생: {e}", exc_info=True)

    def shutdown(self):
        """모든 컴포넌트를 정상적으로 종료합니다."""
        if self.shutdown_event.is_set():
            return
        self.logger.info("정상 종료를 시작합니다...")
        self.shutdown_event.set()

        self.redis_manager.shutdown()

        with self.producer_lock:
            self.logger.info(f"{len(self.producers)}개의 프로듀서를 중지합니다...")
            for producer in self.producers.values():
                if producer.is_alive():
                    producer.stop()
                    producer.join(timeout=5)
            self.producers.clear()

        self.window_manager.shutdown()
        self.consumer_pool.shutdown()

        self.logger.info("종료 완료")

    def get_status(self) -> Dict:
        """에이전트의 현재 상태를 반환합니다."""
        return {
            "producers": len(self.producers),
            "queue_size": self.queue_manager.size(),
            "consumer_stats": self.consumer_pool.get_stats(),
            "window_stats": self.window_manager.get_stats(),
        }


# 전역 변수로 agent 인스턴스 관리 (FastAPI에서 접근하기 위함)
agent: Optional[AegisAgent] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 앱의 수명 주기 관리 (시작 및 종료 시 실행)"""
    global agent
    
    # 설정 로드 및 에이전트 초기화
    args = parse_args()
    config = Config()
    if args.workers:
        config.num_workers = args.workers
    
    if args.real_vlm:
        config.real_vlm = True
    if args.real_precision:
        config.real_precision = True
    if args.real_backend:
        config.real_backend = True
    if args.real_backend_events_only:
        config.real_backend_events_only = True

    if args.log_level:
        config.log_level = args.log_level.upper()
    
    config.__post_init__()

    agent = AegisAgent(config)
    agent.start()
    
    yield
    
    # 종료 시 실행
    if agent:
        agent.shutdown()


# FastAPI 앱 생성
app = FastAPI(title="AEGIS AI Agent API", lifespan=lifespan)


@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy"}


@app.get("/status")
async def get_agent_status():
    """에이전트 상태 조회 엔드포인트"""
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    return agent.get_status()


# =========================================
# SSE (Server-Sent Events) - 승인 요청 전송용
# =========================================
# [Human-in-the-Loop 전체 흐름]
#
# 1. LangGraph에서 emergency_call 도구 호출 감지
#    └→ response_agent.py의 should_continue() → "check_approval" 분기
#
# 2. check_approval_node 실행
#    └→ approval_manager.request_approval() 호출
#       └→ request_id = uuid.uuid4() 생성 (AI Agent가 관리)
#       └→ _requests Dict에 저장 (메모리)
#       └→ broadcast_sse_event() 콜백 호출
#
# 3. SSE로 브라우저에 승인 요청 전송
#    └→ 이벤트: "approval_request"
#    └→ 데이터: {request_id, event_id, camera_name, agency_name, ...}
#
# 4. 브라우저에서 모달 표시 → 사용자가 [승인]/[거부] 클릭
#    └→ POST /api/approval/{request_id} 호출
#
# 5. handle_approval() 처리
#    └→ approval_manager.set_approval_result() 호출
#       └→ threading.Event.set() → check_approval_node 대기 해제
#    └→ (선택) Spring Boot 백엔드에 승인 이력 전송
#
# 6. LangGraph 그래프 재개
#    └→ 승인: tools 노드 → emergency_call 실행
#    └→ 거부: skip_emergency 노드 → 스킵 메시지 생성
# =========================================

# 연결된 SSE 클라이언트 목록 (Queue 기반)
sse_clients: List[asyncio.Queue] = []
sse_clients_lock = threading.Lock()


def broadcast_sse_event(event_type: str, data: dict):
    """
    모든 SSE 클라이언트에게 이벤트 브로드캐스트

    approval_manager에서 콜백으로 호출됩니다.

    Args:
        event_type: 이벤트 타입 (approval_request, approval_timeout 등)
        data: 전송할 데이터
    """
    message = f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    with sse_clients_lock:
        for queue in sse_clients:
            try:
                # 비동기 Queue에 메시지 추가 (non-blocking)
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass  # 큐가 가득 찬 경우 무시


# approval_manager에 SSE 콜백 등록
approval_manager.set_sse_callback(broadcast_sse_event)


@app.get("/api/sse/approval")
async def sse_approval_endpoint():
    """
    Human-in-the-Loop 승인 요청을 위한 SSE 엔드포인트

    프론트엔드에서 이 엔드포인트에 연결하면:
    1. emergency_call 승인 요청 시 "approval_request" 이벤트 수신
    2. 타임아웃 시 "approval_timeout" 이벤트 수신

    사용 예시 (프론트엔드):
        const eventSource = new EventSource('/api/sse/approval');
        eventSource.addEventListener('approval_request', (e) => {
            const data = JSON.parse(e.data);
            showApprovalModal(data);
        });
    """
    # 클라이언트별 메시지 큐 생성
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    with sse_clients_lock:
        sse_clients.append(queue)

    async def event_generator():
        try:
            # 연결 유지를 위한 초기 메시지
            yield f"event: connected\ndata: {json.dumps({'status': 'connected'})}\n\n"

            while True:
                try:
                    # 메시지 대기 (30초 타임아웃 후 heartbeat)
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield message
                except asyncio.TimeoutError:
                    # 연결 유지를 위한 heartbeat
                    yield f"event: heartbeat\ndata: {json.dumps({'timestamp': time.time()})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            # 클라이언트 연결 해제 시 목록에서 제거
            with sse_clients_lock:
                if queue in sse_clients:
                    sse_clients.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx 버퍼링 비활성화
        }
    )


# =========================================
# Human-in-the-Loop 승인 REST API
# =========================================
# [UUID 관리]
# - request_id는 approval_manager.request_approval()에서 uuid.uuid4()로 생성
# - approval_manager._requests Dict에 메모리 저장 (request_id → ApprovalRequest)
# - approval_manager._event_requests Dict로 event_id별 그룹 관리
# - 오래된 요청은 cleanup_old_requests()로 5분 후 자동 정리
#
# [흐름]
# 1. check_approval_node → approval_manager.request_approval() → request_id 생성
# 2. SSE로 브라우저에 request_id 포함하여 전송
# 3. 브라우저에서 POST /api/approval/{request_id} 호출
# 4. approval_manager.set_approval_result() → threading.Event.set() → 그래프 재개
# =========================================
class ApprovalRequestBody(BaseModel):
    """승인/거부 요청 바디"""
    approved: bool              # True: 승인, False: 거부
    user_id: str = None         # 응답한 사용자 ID (선택)


@app.post("/api/approval/{request_id}")
async def handle_approval(request_id: str, body: ApprovalRequestBody):
    """
    긴급 신고 승인/거부 처리 엔드포인트

    프론트엔드 모달에서 승인/거부 버튼 클릭 시 호출됩니다.

    [흐름]
    1. 승인 요청 존재 확인
    2. approval_manager에 결과 설정 (threading.Event.set() → 그래프 재개)
    3. Spring Boot 백엔드에 승인 이력 전송 (DB 저장용)

    Args:
        request_id: 승인 요청 ID (UUID, AI Agent가 생성)
        body: 승인 여부 및 사용자 ID
            - approved: True(승인) / False(거부)
            - user_id: 승인/거부한 사용자 ID

    Returns:
        처리 결과
    """
    import httpx
    from datetime import datetime

    # 승인 요청 존재 확인
    existing = approval_manager.get_request(request_id)
    if not existing:
        raise HTTPException(status_code=404, detail="승인 요청을 찾을 수 없습니다")

    # 승인 결과 설정 (그래프 재개)
    success = approval_manager.set_approval_result(
        request_id=request_id,
        approved=body.approved,
        user_id=body.user_id,
    )

    if not success:
        raise HTTPException(status_code=400, detail="이미 처리된 요청입니다")

    # =========================================
    # Spring Boot 백엔드에 승인 이력 전송 (DB 저장)
    # =========================================
    # TODO: 백엔드 API 엔드포인트 구현 필요
    # POST /api/approval-logs
    # {
    #     "request_id": "uuid",
    #     "event_id": "이벤트 ID",
    #     "action_type": "emergency_call",
    #     "agency_type": "112_POLICE",
    #     "approved": true/false,
    #     "user_id": "승인한 사용자 ID",
    #     "responded_at": "2026-02-11T12:00:00"
    # }
    # =========================================
    try:
        if agent and agent.config.real_backend:
            backend_url = f"http://{agent.config.backend_host}:{agent.config.backend_port}"

            approval_log = {
                "request_id": request_id,
                "event_id": existing.get("event_id"),
                "action_type": existing.get("action_type"),
                "agency_type": existing.get("action_detail", {}).get("agency_type"),
                "approved": body.approved,
                "user_id": body.user_id,
                "responded_at": datetime.now().isoformat(),
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{backend_url}/api/approval-logs",
                    json=approval_log,
                    timeout=5.0
                )
                if response.status_code == 201:
                    pass  # 성공
                else:
                    # 로그만 남기고 계속 진행 (승인 처리는 이미 완료됨)
                    pass
    except Exception as e:
        # 백엔드 전송 실패해도 승인 처리는 완료된 상태
        # 로그만 남기고 계속 진행
        pass

    status_str = "승인" if body.approved else "거부"
    return {
        "success": True,
        "message": f"긴급 신고가 {status_str}되었습니다",
        "request_id": request_id,
        "approved": body.approved,
    }


@app.get("/api/approval/pending")
async def get_pending_approvals(event_id: str = None):
    """
    대기 중인 승인 요청 목록 조회

    Args:
        event_id: 특정 이벤트의 요청만 조회 (선택)

    Returns:
        대기 중인 승인 요청 리스트
    """
    pending = approval_manager.get_pending_requests(event_id=event_id)
    return {"pending_requests": pending, "count": len(pending)}



def parse_args():
    """커맨드 라인 인자를 파싱합니다."""
    parser = argparse.ArgumentParser(description="AEGIS AI Agent - LangGraph 기반 분석 파이프라인")
    parser.add_argument("--workers", type=int, help="컨슈머 워커 스레드 수")
    parser.add_argument("--real-vlm", action="store_true", help="VLM 실제 서버 사용")
    parser.add_argument("--real-precision", action="store_true", help="정밀 분석 실제 서버 사용")
    parser.add_argument("--real-backend", action="store_true", help="백엔드 실제 서버 사용")
    parser.add_argument("--real-backend-events-only", action="store_true", help="1차/2차 갱신 + 클립은 실제 백엔드, 보고서만 Mock")
    parser.add_argument("--log-level", type=str, help="로깅 레벨 (DEBUG, INFO, WARNING, ERROR)")
    return parser.parse_args()


def main():
    """메인 진입점"""
    # Uvicorn을 사용하여 FastAPI 앱 실행
    # 주의: uvicorn.run은 블로킹 호출이므로, 에이전트 로직은 lifespan에서 백그라운드로 실행됨
    
    # 인자 파싱은 lifespan 내부에서 다시 수행하거나, 
    # 여기서 파싱한 후 환경 변수 등을 통해 전달해야 하지만,
    # 간단하게 lifespan 내부에서 다시 파싱하도록 구현함.
    # (uvicorn 실행 시 인자를 직접 전달받기 어려움)
    
    # Config에서 포트 설정 가져오기 (기본값 사용)
    config = Config()
    
    print(f"AEGIS AI Agent API 서버를 {config.agent_api_port} 포트에서 시작합니다.")
    uvicorn.run("src.app:app", host=config.agent_api_host, port=config.agent_api_port, reload=False)


if __name__ == "__main__":
    main()
