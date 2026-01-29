# LangGraph 도입 방식 비교 분석

## 현재 아키텍처 요약

```
[Producer] → [WindowManager] → [Queue] → [Consumer] → [VLM] → [Backend] → [정밀분석]
   │              │              │           │
   │              │              │           └── "에이전트 로직" (분기/판단)
   │              │              │
   └──────────────┴──────────────┴── "인프라/데이터 파이프라인" (스레드, I/O)
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

### 적용 위치

```
현재 Consumer._worker_loop()의 이 부분:
├── 1단계: VLM 분석
├── 2단계: 백엔드 전송
└── 3단계: 트리거 조건 확인 → 정밀 분석

↓ LangGraph로 전환

class AnalysisGraph:
    nodes = [vlm_node, backend_node, router_node, precision_agent_node]
```

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
