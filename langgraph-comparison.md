# LangGraph 도입 방식 비교 분석

## 현재 아키텍처 요약

```
[Producer] → [WindowManager] → [Queue] → [Consumer] → [VLM] → [Backend] → [정밀분석]
   │              │              │           │
   │              │              │           └── "에이전트 로직" (분기/판단)
   │              │              │
   └──────────────┴──────────────┴── "인프라/데이터 파이프라인" (스레드, I/O)
```

## 🎯 명확한 경계 구분

```
┌─────────────────────────────────────────────────────────────────────┐
│  일반 Python (기존 유지)                                              │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                                     │
│  ┌────────────┐   ┌────────────┐   ┌────────────┐                 │
│  │ Producer   │   │  Window    │   │   Queue    │                 │
│  │ (CV2/RTSP) │──▶│  Manager   │──▶│  Manager   │                 │
│  │            │   │ (버퍼 생성)  │   │            │                 │
│  └────────────┘   └────────────┘   └────────────┘                 │
│       │                 │                 │                        │
│       │                 │                 │                        │
│       └─────────────────┴─────────────────┘                        │
│                         ▼                                          │
│                  ┌────────────┐                                    │
│                  │ Consumer   │ ◀─── 스레드 풀에서 작업 가져옴       │
│                  │ 워커 스레드  │                                   │
│                  └────────────┘                                    │
│                         │                                          │
└─────────────────────────┼──────────────────────────────────────────┘
                          │
                          ▼ task = queue.get()
┌─────────────────────────┼──────────────────────────────────────────┐
│  LangGraph (새로 작성)    │                                          │
│  ━━━━━━━━━━━━━━━━━━━━━━▼━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                                     │
│            graph.invoke({                                          │
│                camera_id: task['camera_id'],                       │
│                frames: task['low_res_frames']                      │
│            })                                                       │
│                         │                                          │
│                         ▼                                          │
│            ┌──────────────────────────┐                            │
│            │   vlm_analysis_node      │ ◀─── VLM API 호출          │
│            └──────────────────────────┘                            │
│                         │                                          │
│                         ▼                                          │
│            ┌──────────────────────────┐                            │
│            │   backend_report_node    │ ◀─── 백엔드 전송            │
│            └──────────────────────────┘                            │
│                         │                                          │
│                         ▼                                          │
│            ┌──────────────────────────┐                            │
│            │   conditional_router     │ ◀─── 조건 분기 (이상 여부)   │
│            └──────────────────────────┘                            │
│                    /          \                                    │
│                   /            \                                   │
│         [정상]   /              \  [이상]                            │
│                 /                \                                 │
│                ▼                  ▼                                │
│            ┌────┐    ┌──────────────────────────┐                 │
│            │END │    │  precision_agent_node    │ ◀─── LLM 에이전트│
│            └────┘    │  (LLM 기반 의사결정 +    │                  │
│                      │   정밀 분석 API 호출)     │                  │
│                      └──────────────────────────┘                  │
│                                  │                                 │
│                                  ▼                                 │
│                              ┌────┐                                │
│                              │END │                                │
│                              └────┘                                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 💡 코드 레벨에서 보는 경계

### ✅ 일반 Python으로 유지 (기존 코드)

```python
# producer.py - CV2로 RTSP 프레임 캡처
class FrameProducer(threading.Thread):
    def run(self):
        while not self.shutdown_event.is_set():
            ret, frame = self.capture.read()  # ← CV2 사용
            if ret:
                # 리사이징, JPEG 인코딩
                encoded_frame = self._encode_frame(frame)
                # WindowManager에 전달
                self.frame_callback(self.camera_id, encoded_frame, timestamp)

# windowing.py - 슬라이딩 윈도우 버퍼 관리
class WindowManager:
    def add_frame(self, camera_id, frame, timestamp):
        self.buffers[camera_id].append((frame, timestamp))  # ← deque 사용
        
    def _generate_window(self, camera_id):
        frames = list(self.buffers[camera_id])  # ← N개 프레임 수집
        task = {
            'camera_id': camera_id,
            'low_res_frames': frames,
            'window_start': start_time,
            'window_end': end_time
        }
        self.queue_manager.put(task)  # ← 큐에 넣기

# consumer.py - 워커 스레드에서 큐 소비
class ConsumerPool:
    def _worker_loop(self, worker_id):
        while not self.shutdown_event.is_set():
            task = self.queue_manager.get(timeout=1.0)  # ← 큐에서 가져오기
            
            # ========== 여기부터 LangGraph로 전환 ==========
            result = self.analysis_graph.invoke(task)  # ← LangGraph 호출
            # ========== 여기까지 LangGraph ==========
```

### ⚡ LangGraph로 전환 (새로 작성)

```python
# analysis_graph.py - 새로 만들 파일
from langgraph.graph import StateGraph, END
from typing import TypedDict, List, Optional

class AnalysisState(TypedDict):
    camera_id: str
    frames: List[bytes]
    window_start: str
    window_end: str
    vlm_result: Optional[dict]
    backend_sent: bool
    precision_result: Optional[dict]

class AnalysisGraph:
    def __init__(self, vlm_client, backend_client, precision_client):
        self.vlm_client = vlm_client
        self.backend_client = backend_client
        self.precision_client = precision_client
        
        # 그래프 구성
        graph = StateGraph(AnalysisState)
        
        # 노드 추가
        graph.add_node("vlm_analysis", self.vlm_node)
        graph.add_node("backend_report", self.backend_node)
        graph.add_node("precision_agent", self.precision_agent_node)
        
        # 엣지 연결
        graph.set_entry_point("vlm_analysis")
        graph.add_edge("vlm_analysis", "backend_report")
        graph.add_conditional_edges(
            "backend_report",
            self.should_escalate,
            {
                "precision": "precision_agent",
                "end": END
            }
        )
        graph.add_edge("precision_agent", END)
        
        self.graph = graph.compile()
    
    def vlm_node(self, state: AnalysisState) -> AnalysisState:
        """VLM API 호출 노드"""
        vlm_result = self.vlm_client.analyze_frames(
            state['camera_id'],
            state['frames'],
            {'window_start': state['window_start'], 'window_end': state['window_end']}
        )
        return {**state, 'vlm_result': vlm_result}
    
    def backend_node(self, state: AnalysisState) -> AnalysisState:
        """백엔드 전송 노드"""
        self.backend_client.send_vlm_result(
            state['camera_id'],
            state['vlm_result'],
            {}
        )
        return {**state, 'backend_sent': True}
    
    def should_escalate(self, state: AnalysisState) -> str:
        """조건 분기: 정밀 분석 필요 여부 판단"""
        primary_category = state['vlm_result'].get('primary_category', '').lower()
        is_abnormal = any(cat in primary_category for cat in ['fire', 'smoke', 'intrusion'])
        return "precision" if is_abnormal else "end"
    
    def precision_agent_node(self, state: AnalysisState) -> AnalysisState:
        """정밀 분석 에이전트 노드 (추후 LLM 기반으로 업그레이드)"""
        precision_result = self.precision_client.send_for_analysis(
            state['camera_id'],
            state['frames'],
            state['vlm_result'],
            {}
        )
        return {**state, 'precision_result': precision_result}
    
    def invoke(self, task: dict) -> dict:
        """Consumer에서 호출하는 메인 진입점"""
        initial_state = {
            'camera_id': task['camera_id'],
            'frames': task['low_res_frames'],
            'window_start': task.get('window_start', ''),
            'window_end': task.get('window_end', ''),
            'vlm_result': None,
            'backend_sent': False,
            'precision_result': None
        }
        return self.graph.invoke(initial_state)
```

---

## 방식 1️⃣: 전체 시스템을 LangGraph로 만들기

### 구조
```python
# LangGraph State
class PipelineState(TypedDict):
    camera_id: str
    frames: List[bytes]
    vlm_result: Optional[dict]
    event_id: Optional[str]
    ...

# 전체가 LangGraph 노드
graph = StateGraph(PipelineState)
graph.add_node("capture_frames", capture_frames_node)      # 일반 노드
graph.add_node("create_window", window_manager_node)       # 일반 노드
graph.add_node("vlm_analysis", vlm_node)                   # 일반 노드
graph.add_node("send_to_backend", backend_node)            # 일반 노드
graph.add_node("precision_agent", precision_agent)         # AI 에이전트 노드
```

### ✅ 장점
1. **통합 오케스트레이션**: 전체 워크플로우가 하나의 그래프로 관리됨
2. **시각화 용이**: LangGraph Studio에서 전체 파이프라인 시각화 가능
3. **체크포인팅**: 중간 상태 저장/복구가 용이 (장애 복구)
4. **일관된 에러 처리**: LangGraph의 에러 핸들링 메커니즘 활용

### ❌ 단점
1. **오버헤드**: 프레임 캡처 같은 저수준 I/O 작업에 LangGraph는 불필요한 추상화
2. **성능 저하 우려**: 
   - Producer는 초당 수십 프레임 처리 필요
   - LangGraph 상태 관리 오버헤드가 부담
3. **복잡한 병렬 처리**: 다중 카메라 스트림을 LangGraph로 관리하기 어려움
4. **기존 코드 대규모 리팩토링 필요**: 스레드 기반 코드 전체 재작성

---

## 방식 2️⃣: 에이전트 부분만 LangGraph 적용 (권장)

### 구조
```
[기존 파이프라인 유지]                    [LangGraph 적용]
Producer → WindowManager → Queue → ┌──────────────────────────┐
                                   │  LangGraph Agent         │
                                   │  ┌─────────────────────┐  │
                                   │  │ vlm_analysis        │  │
                                   │  │ → backend_report    │  │
                                   │  │ → conditional_router│  │
                                   │  │ → precision_agent   │  │
                                   │  └─────────────────────┘  │
                                   └──────────────────────────┘
```

```python
# Consumer 내부에서 LangGraph 호출
class AnalysisGraph:
    def __init__(self):
        self.graph = StateGraph(AnalysisState)
        self.graph.add_node("vlm_analysis", self.vlm_node)
        self.graph.add_node("backend_report", self.backend_node)
        self.graph.add_node("precision_analysis", self.precision_agent)  # LLM 기반 에이전트
        self.graph.add_conditional_edges("backend_report", self.route_by_category)
```

### ✅ 장점
1. **관심사 분리**: 
   - 데이터 파이프라인(Producer, Window): 기존 스레드 기반 유지
   - 분석 로직(VLM→분기→정밀분석): LangGraph로 관리
2. **점진적 도입**: 기존 코드 최소 변경으로 LangGraph 통합 가능
3. **성능 유지**: 고빈도 I/O 작업은 기존 최적화된 코드 사용
4. **확장성**: 에이전트 로직만 독립적으로 발전 가능
   - 추후 복잡한 의사결정 추가 용이 (예: multi-agent 협업)
5. **실용적 LangGraph 활용**:
   - 조건부 라우팅 (정상/이상 분기)
   - 에이전트 Tool 호출 (정밀 분석)
   - 상태 추적 및 체크포인팅

### ❌ 단점
1. 두 가지 패러다임 공존 (스레드 + LangGraph)
2. 전체 워크플로우를 한눈에 보기 어려울 수 있음

---

## 🏆 결론: 방식 2️⃣ (에이전트 부분만 LangGraph) 권장

### 이유

| 기준 | 전체 LangGraph | 에이전트만 LangGraph |
|------|---------------|---------------------|
| **성능** | ❌ 오버헤드 | ✅ 최적 |
| **개발 비용** | ❌ 전체 재작성 | ✅ 최소 변경 |
| **LangGraph 적합성** | ⚠️ I/O에 부적합 | ✅ 의사결정에 최적 |
| **확장성** | ⚠️ 복잡 | ✅ 에이전트만 발전 |
| **유지보수** | ❌ 높은 복잡도 | ✅ 관심사 분리 |

### 적용 위치 - 두 가지 옵션

#### 🔵 옵션 A: 첫 VLM 요청부터 LangGraph (권장)

```python
# consumer.py 86-123 라인 전체를 LangGraph로 전환
# 현재 코드:
vlm_result = self.vlm_client.analyze_frames(...)          # 1단계
self.backend_client.send_vlm_result(...)                  # 2단계
if is_abnormal:                                           # 3단계
    self.precision_client.send_for_analysis(...)

# LangGraph로 전환:
class AnalysisGraph:
    def __init__(self):
        self.graph = StateGraph(AnalysisState)
        self.graph.add_node("vlm_analysis", self.vlm_node)        # VLM API 호출
        self.graph.add_node("backend_report", self.backend_node)  # 백엔드 전송
        self.graph.add_node("decision_router", self.router)       # 조건 분기
        self.graph.add_node("precision_agent", self.precision_node)  # 정밀 분석
        
        self.graph.add_edge("vlm_analysis", "backend_report")
        self.graph.add_conditional_edges(
            "backend_report",
            self.should_escalate,  # is_abnormal 판단
            {
                "precision": "precision_agent",
                "end": END
            }
        )
```

**장점**:
- 전체 분석 플로우가 하나의 그래프로 통합
- VLM 실패 시 재시도 로직을 LangGraph에서 관리 가능
- 상태 체크포인팅으로 중단 지점부터 재개 가능

**단점**:
- VLM API 호출 자체는 "에이전트"가 아니므로 약간 오버킬

---

#### 🟢 옵션 B: VLM 결과 받은 후부터만 LangGraph (최소 변경)

```python
# consumer.py 86-99 라인: 기존 유지
vlm_result = self.vlm_client.analyze_frames(...)  # 기존 코드 유지
self.backend_client.send_vlm_result(...)          # 기존 코드 유지

# 101-123 라인만 LangGraph로 전환
class DecisionGraph:
    def __init__(self):
        self.graph = StateGraph(DecisionState)
        self.graph.add_node("analyze_severity", self.llm_decision_node)  # LLM이 심각도 분석
        self.graph.add_node("precision_agent", self.precision_node)
        
        self.graph.add_conditional_edges(
            "analyze_severity",
            self.route_by_decision,
            {
                "escalate": "precision_agent",
                "end": END
            }
        )

# 호출 방식:
decision_result = self.decision_graph.invoke({
    "vlm_result": vlm_result,
    "camera_id": camera_id,
    "frames": low_res_frames
})
```

**장점**:
- 최소한의 코드 변경
- 진짜 "의사결정" 부분만 LangGraph 적용
- 단순 if문이 LLM 기반 판단으로 업그레이드

**단점**:
- VLM 호출과 에이전트 부분이 분리되어 있음
- 전체 플로우 시각화가 부분적

---

### 🎯 최종 권장: 옵션 A

**이유**:
1. VLM API 호출도 "외부 도구 사용"의 일종이므로 LangGraph 노드로 적합
2. 나중에 VLM 결과가 불확실할 때 재분석 요청 같은 로직 추가 용이
3. 전체 분석 파이프라인을 하나의 그래프로 관리하면 디버깅/모니터링 용이
4. LangGraph의 체크포인팅 기능을 최대한 활용 가능

### 실제 이점
1. **정밀 분석을 에이전트로**: 단순 API 호출 대신 LLM이 상황 판단
2. **유연한 라우팅**: 단순 if문 대신 LangGraph 조건부 엣지로 복잡한 분기 가능
3. **Tool 통합**: 정밀 분석, 알림 전송 등을 에이전트 Tool로 정의
4. **Human-in-the-loop**: 필요시 사람 개입 지점 추가 용이

---

## 추천 구현 단계

1. **Phase 1**: Consumer 내부 로직을 LangGraph StateGraph로 분리
2. **Phase 2**: 정밀 분석을 LLM 기반 에이전트로 전환
3. **Phase 3**: 필요시 multi-agent 구조 확장 (예: 검증 에이전트 추가)
