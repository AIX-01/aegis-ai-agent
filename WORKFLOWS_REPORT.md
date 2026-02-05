# AEGIS 보고서 생성 워크플로우

> JSON 구조화 보고서 설계 및 구현 계획

**작성일**: 2026-02-05  
**대상 시스템**: AEGIS AI Agent - LangGraph 분석 파이프라인

---

## 목차

1. [배경 및 목표](#1-배경-및-목표)
2. [보고서 생성 방식 비교](#2-보고서-생성-방식-비교)
3. [선택된 방식: JSON 구조화](#3-선택된-방식-json-구조화)
4. [DB 스키마와의 통합](#4-db-스키마와의-통합)
5. [JSON 스키마 설계](#5-json-스키마-설계)
6. [백엔드 구현 (Python/LangGraph)](#6-백엔드-구현-pythonlanggraph)
7. [프론트엔드 구현 (Next.js)](#7-프론트엔드-구현-nextjs)
8. [Qdrant RAG 통합](#8-qdrant-rag-통합)
9. [구현 로드맵](#9-구현-로드맵)
10. [참고 자료](#10-참고-자료)

---

## 1. 배경 및 목표

### 1.1 현재 상황

AEGIS AI Agent는 LangGraph 기반으로 실시간 영상 분석을 수행하며, 다음 컴포넌트로 구성됩니다:

- **VLM 1차 분석**: 이상 행동 감지 (NORMAL/SUSPICIOUS/ABNORMAL)
- **정밀 분석 (Precision LLM)**: 상세 위험도 분석
- **백엔드 연동**: 이벤트 생성 및 업데이트
- **RAG 참조**: Qdrant 벡터 DB에서 유사 매뉴얼/사례 검색 (예정)

### 1.2 DB 스키마 (events 테이블)

| Column Name | Data Type | Nullable | Description |
|-------------|-----------|----------|-------------|
| id | UUID | NO | 이벤트 기본키 |
| camera_id | UUID | NO | 카메라 외래키 (→ cameras.id) |
| risk | EVENT_RISK | NO | 1차 분류 (NORMAL, SUSPICIOUS, ABNORMAL) |
| type | EVENT_TYPE | NO | 2차 분류 (ASSAULT, BURGLARY, DUMP, SWOON, VANDALISM) |
| status | EVENT_STATUS | NO | 처리 상태 (PROCESSING, ANALYZED) |
| occurred_at | TIMESTAMP | NO | 발생 시각 |
| clip_url | TEXT | YES | S3 증거 영상 URL (clips/{eventId}.mp4) |
| summary | TEXT | YES | AI 요약문 |
| risk_score | VARCHAR(10) | YES | 위험도 점수 (0.0 ~ 1.0) |
| **rag_references** | **JSONB** | **YES** | **RAG 참조 매뉴얼 목록 (Qdrant 검색 결과)** |
| **report** | **TEXT** | **YES** | **상세 사건 보고서 (JSON 문자열)** |
| created_at | TIMESTAMP | NO | DB 레코드 생성 시각 |
| updated_at | TIMESTAMP | NO | DB 레코드 수정 시각 |

**Note**: 
- `actions`는 별도 테이블(`event_actions`)로 분리되어 있음
- `rag_references`는 PostgreSQL JSONB 타입
- `report`는 TEXT 타입에 JSON 문자열 저장

### 1.3 목표

1. **`report` 컬럼 활용**: 구조화된 JSON 문자열로 보고서 저장
2. **Qdrant 통합**: RAG 검색 결과를 `rag_references`에 저장
3. **프론트엔드 렌더링**: Next.js에서 동적 UI로 보고서 표시
4. **확장성 확보**: 향후 차트, 모달, 필터링 등 추가 용이

---

## 2. 보고서 생성 방식 비교

### 2.1 방식 1: Markdown + react-markdown

#### 장점
- ✅ 구현 간단 (라이브러리 1개)
- ✅ 가독성 좋은 원본 (버전 관리 용이)
- ✅ 백엔드 부담 최소화

#### 단점
- ❌ UI 커스터마이징 제한적
- ❌ 동적 기능 추가 어려움 (버튼, 모달 등)
- ❌ 데이터 재가공 불가 (검색/필터링 불가)

#### 적합한 경우
- 보고서가 읽기 전용 문서 형태
- 빠른 MVP 구현 필요

---

### 2.2 방식 2: 백엔드 HTML 직접 생성

#### 장점
- ✅ SEO 친화적
- ✅ 프론트엔드 부담 감소

#### 단점
- ❌ 백엔드 복잡도 증가
- ❌ 프론트-백엔드 스타일 중복 관리
- ❌ XSS 취약점 위험
- ❌ Next.js 장점 활용 못함

#### 적합한 경우
- PDF 변환 필요
- 레거시 시스템 통합

---

### 2.3 방식 3: JSON 구조화 (✅ 선택)

#### 장점
- ✅ **최고의 유연성** (섹션별 자유로운 UI)
- ✅ **재사용 가능** (다른 화면에서도 활용)
- ✅ **데이터 중심 설계** (검색, 필터링, 정렬 가능)
- ✅ **동적 기능 추가 용이** (차트, 버튼, 모달)
- ✅ **테스트 용이** (JSON 검증만)
- ✅ **타입 안전성** (TypeScript 인터페이스)

#### 단점
- ❌ 초기 구현 비용 높음
- ❌ 백엔드-프론트 계약 필요
- ❌ JSON 크기 증가 가능

#### 적합한 경우
- **대시보드 UI** (복잡한 인터랙션)
- **차트/그래프** (시각화)
- **필터링/검색** (사용자 조작)
- **장기 유지보수** (확장성)

---

## 3. 선택된 방식: JSON 구조화

### 3.1 선택 이유

1. **DB 스키마와 완벽 호환**
   - `rag_references` (JSONB) 타입으로 JSON 저장
   - `report` (TEXT)에 JSON 문자열 저장 가능
   - `actions`는 별도 `event_actions` 테이블로 관리

2. **Qdrant RAG 통합 자연스러움**
   - 검색 결과를 바로 JSON 배열로 저장
   - 관련도 점수, 메타데이터 포함

3. **Next.js + TypeScript 최적 활용**
   - shadcn/ui 컴포넌트와 조화
   - Accordion, Badge, Card 등으로 풍부한 UI

4. **프로젝트 특성 부합**
   - 통계 페이지에 시각화 필요
   - `rag_references` 클릭 시 모달/사이드바 표시
   - `actions`를 체크리스트/버튼으로 표현

---

## 4. DB 스키마와의 통합

### 4.1 데이터 저장 전략

```python
# LangGraph 노드 실행 결과
{
    "report": "JSON 문자열",           # TEXT 컬럼 (전체 구조화 보고서)
    "rag_references": [...],           # JSONB 컬럼 (Qdrant 검색 결과)
    "summary": "AI 요약",
    "risk_score": "0.92"
}
```

**백엔드 테이블 구조:**
- `events` 테이블: report (TEXT), rag_references (JSONB), summary (TEXT), risk_score (VARCHAR)
- `event_actions` 테이블: 실제 실행된 조치 기록 (별도 관리)

### 4.2 PostgreSQL 저장 쿼리

```sql
-- AI Agent가 PATCH /internal/agent/events/{id}/analysis 호출 시
UPDATE events
SET
    summary = $1,
    risk_score = $2,
    rag_references = $3::jsonb,      -- JSONB로 저장
    report = $4::text,                -- JSON 문자열로 저장
    status = 'ANALYZED',
    updated_at = NOW()
WHERE id = $5;
```

**Note**: 백엔드 내부 API 명세 참고
- `POST /internal/agent/events` - 이벤트 생성
- `PATCH /internal/agent/events/{id}/analysis` - 분석 결과 추가
- `POST /internal/agent/events/{id}/clip/confirm` - 클립 URL 확정

### 4.3 조회 쿼리 (JSONB 활용)

```sql
-- 위험도가 ABNORMAL인 이벤트 검색
SELECT * FROM events
WHERE report::jsonb @> '{"analysis": {"risk_level": "ABNORMAL"}}';

-- RAG 참조가 있는 이벤트 검색
SELECT * FROM events
WHERE rag_references IS NOT NULL AND jsonb_array_length(rag_references) > 0;
```

---

## 5. JSON 스키마 설계

### 5.1 전체 구조

```json
{
  "version": "1.0",
  "generated_at": "2026-02-05T12:34:56.789Z",
  
  "event": {
    "id": "uuid-123",
    "occurred_at": "2026-02-05T12:30:00.000Z",
    "camera": {
      "id": "camera-uuid",
      "name": "출입구 카메라 A",
      "location": "1층 로비"
    }
  },
  
  "analysis": {
    "risk_level": "ABNORMAL",
    "event_type": "ASSAULT",
    "risk_score": "0.92",
    "summary": "2인의 격렬한 신체 접촉이 감지되었습니다.",
    "status": "ANALYZED"
  },
  
  "precision_analysis": {
    "risk": "ABNORMAL",
    "summary": "1층 로비에서 폭행 사건이 발생...",
    "risk_score": "0.92",
    "event_type": "ASSAULT"
  },
  
  "rag_references": [
    {
      "id": "doc-uuid",
      "source": "안전 매뉴얼 v2.1",
      "title": "폭행 사건 대응 절차",
      "content": "1. 즉시 보안팀에 연락...",
      "category": "ASSAULT",
      "relevance_score": 0.92,
      "metadata": {
        "page": 15,
        "last_updated": "2025-12-01"
      }
    }
  ],
  
  "recommended_actions": [
    {
      "priority": "HIGH",
      "category": "EMERGENCY_RESPONSE",
      "title": "보안팀 즉시 출동",
      "description": "현장 확인 및 초기 대응",
      "estimated_time": "5분 이내"
    }
  ],
  
  "clip": {
    "url": "clips/uuid-123.mp4",
    "confirmed": true
  }
}
```

**Note**: 
- `recommended_actions`는 권장 조치 (실제 실행된 actions는 `event_actions` 테이블에 별도 저장)
- `event_actions` 테이블 스키마: `{id, event_id, log, triggered_at, created_at}`

### 5.2 주요 필드 설명

| 섹션 | 필드 | 타입 | 설명 |
|------|------|------|------|
| `version` | - | string | 스키마 버전 (마이그레이션용) |
| `generated_at` | - | ISO 8601 | 보고서 생성 시각 |
| `event` | `id` | UUID | 이벤트 ID |
|  | `occurred_at` | ISO 8601 | 발생 시각 |
|  | `camera` | object | 카메라 정보 |
| `analysis` | `risk_level` | enum | NORMAL/SUSPICIOUS/ABNORMAL |
|  | `event_type` | enum | ASSAULT/BURGLARY/... |
|  | `risk_score` | string | "0.0" ~ "1.0" |
|  | `summary` | string | 요약문 |
|  | `status` | enum | PROCESSING/ANALYZED |
| `rag_references` | - | array | Qdrant 검색 결과 배열 (JSONB 컬럼) |
|  | `relevance_score` | float | 유사도 점수 |
| `recommended_actions` | - | array | AI 권장 조치 배열 |
|  | `priority` | enum | HIGH/MEDIUM/LOW |
| `clip` | `url` | string | S3 클립 경로 |
|  | `confirmed` | boolean | 클립 확정 여부 |

---

## 6. 백엔드 구현 (Python/LangGraph)

### 6.1 파일 구조

```
aegis-ai-agent/src/graph/nodes/
├── generate_report.py       # 보고서 생성 노드 (수정 필요)
├── precision_analysis.py    # RAG 검색 추가 필요
└── ...
```

### 6.2 generate_report_node 구현

```python
# graph/nodes/generate_report.py
import json
from datetime import datetime
from typing import Dict, Any, List
from graph.state import AnalysisState

def generate_report_node(state: AnalysisState) -> Dict[str, Any]:
    """
    JSON 구조화 보고서 생성
    
    Args:
        state: LangGraph 분석 상태
        
    Returns:
        report (JSON 문자열), rag_references (JSONB)
    """
    
    # 1. RAG 참조 포맷팅
    rag_references = _format_rag_references(state.get('rag_references', []))
    
    # 2. 권장 조치 포맷팅
    recommended_actions = _format_recommended_actions(state.get('recommended_actions', []))
    
    # 3. 전체 보고서 JSON 구조 생성
    report_data = {
        "version": "1.0",
        "generated_at": datetime.now().isoformat(),
        
        "event": {
            "id": state['event_id'],
            "occurred_at": state['occurred_at'].isoformat(),
            "camera": {
                "id": state['camera_id'],
                "name": state['camera_name'],
                "location": state['camera_location']
            }
        },
        
        "analysis": {
            "risk_level": state['risk_level'],
            "event_type": state['event_type'],
            "risk_score": state.get('risk_score'),
            "summary": state.get('summary', ''),
            "status": "ANALYZED"
        },
        
        "precision_analysis": state.get('precision_result', {}),
        "rag_references": rag_references,
        "recommended_actions": recommended_actions,
        
        "clip": {
            "url": state.get('clip_url'),
            "confirmed": state.get('clip_confirmed', False)
        }
    }
    
    # 4. JSON 문자열로 직렬화
    report_json = json.dumps(report_data, ensure_ascii=False, indent=2)
    
    return {
        "report": report_json,
        "rag_references": rag_references  # JSONB 컬럼용
    }


def _format_rag_references(references: List[Dict]) -> List[Dict]:
    """
    Qdrant 검색 결과를 표준 형식으로 변환
    
    입력 예시:
    [
        {
            "id": "uuid-123",
            "score": 0.92,
            "payload": {
                "source": "안전 매뉴얼 v2.1",
                "title": "폭행 사건 대응 절차",
                "content": "...",
                "category": "ASSAULT",
                "page": 15
            }
        }
    ]
    """
    if not references:
        return []
    
    formatted = []
    for ref in references:
        formatted.append({
            "id": ref.get('id'),
            "source": ref.get('payload', {}).get('source', 'Unknown'),
            "title": ref.get('payload', {}).get('title', 'No Title'),
            "content": ref.get('payload', {}).get('content', ''),
            "category": ref.get('payload', {}).get('category'),
            "relevance_score": round(ref.get('score', 0), 2),
            "metadata": {
                "page": ref.get('payload', {}).get('page'),
                "last_updated": ref.get('payload', {}).get('last_updated')
            }
        })
    
    return formatted


def _format_recommended_actions(actions: List[Dict]) -> List[Dict]:
    """
    권장 조치를 표준 형식으로 변환
    
    Note: 실제 실행된 조치는 event_actions 테이블에 별도 저장
    """
    if not actions:
        return []
    
    formatted = []
    for action in actions:
        formatted.append({
            "priority": action.get('priority', 'MEDIUM'),
            "category": action.get('category', 'GENERAL'),
            "title": action.get('title', ''),
            "description": action.get('description', ''),
            "estimated_time": action.get('estimated_time')
        })
    
    return formatted
```

### 6.3 precision_analysis_node 수정 (RAG 통합)

```python
# graph/nodes/precision_analysis.py
async def precision_analysis_node(state: AnalysisState) -> Dict[str, Any]:
    """정밀 분석 + Qdrant RAG 검색"""
    
    # 1. 기존 정밀 분석
    precision_result = await precision_client.send_for_analysis(...)
    
    # 2. Qdrant 검색
    query_text = f"{state['summary']} {precision_result.get('summary', '')}"
    query_vector = embed_text(query_text)  # 임베딩 모델 필요
    
    rag_references = await qdrant_retriever.search_references(
        query_vector=query_vector,
        event_type=state['event_type'],
        limit=5
    )
    
    return {
        "precision_result": precision_result,
        "rag_references": rag_references,  # 상태에 추가
        "risk_level": precision_result.get('risk', 'UNKNOWN'),
        "summary": precision_result.get('summary', ''),
        "risk_score": precision_result.get('risk_score')
    }
```

### 6.4 DB 업데이트 (update_backend_node)

```python
# graph/nodes/update_backend.py
async def update_backend_node(state: AnalysisState) -> Dict[str, Any]:
    """백엔드 이벤트 갱신"""
    
    # generate_report_node 결과 사용
    report_json = state.get('report')
    rag_references = state.get('rag_references', [])
    
    # 백엔드 내부 API 호출: PATCH /internal/agent/events/{id}/analysis
    response = await backend_client.update_event_analysis(
        event_id=state['event_id'],
        data={
            "risk": state.get('risk_level'),
            "type": state.get('event_type'),
            "summary": state.get('summary'),
            "riskScore": state.get('risk_score')
        }
    )
    
    # rag_references와 report는 별도 API로 업데이트 (백엔드에서 지원 시)
    # 또는 DB 직접 업데이트
    await db.execute("""
        UPDATE events
        SET rag_references = $1::jsonb, report = $2::text
        WHERE id = $3
    """, rag_references, report_json, state['event_id'])
    
    return {"updated": True}
```

**Note**: 백엔드 내부 API 명세
- `PATCH /internal/agent/events/{id}/analysis`는 `{risk, type, summary, riskScore}` 필드만 지원
- `rag_references`, `report` 필드는 현재 API에서 미지원 (직접 DB 업데이트 또는 백엔드 API 확장 필요)

---

## 7. 프론트엔드 구현 (Next.js)

### 7.1 TypeScript 타입 정의

```typescript
// types/report.ts
export interface EventReport {
  version: string;
  generated_at: string;
  event: {
    id: string;
    occurred_at: string;
    camera: {
      id: string;
      name: string;
      location: string;
    };
  };
  analysis: {
    risk_level: 'NORMAL' | 'SUSPICIOUS' | 'ABNORMAL';
    event_type: 'ASSAULT' | 'BURGLARY' | 'DUMP' | 'SWOON' | 'VANDALISM';
    risk_score?: string;
    summary: string;
    status: 'PROCESSING' | 'ANALYZED';
  };
  precision_analysis: Record<string, any>;
  rag_references: RAGReference[];
  recommended_actions: RecommendedAction[];
  clip?: {
    url?: string;
    confirmed: boolean;
  };
}

export interface RAGReference {
  id: string;
  source: string;
  title: string;
  content: string;
  category?: string;
  relevance_score: number;
  metadata?: {
    page?: number;
    last_updated?: string;
  };
}

export interface RecommendedAction {
  priority: 'HIGH' | 'MEDIUM' | 'LOW';
  category: string;
  title: string;
  description: string;
  estimated_time?: string;
}

// 실제 실행된 조치 (별도 테이블, 필요 시 API로 조회)
export interface EventAction {
  id: string;
  eventId: string;
  log: string;
  triggeredAt: string;
  createdAt: string;
}
```

### 7.2 보고서 컴포넌트

```typescript
// components/EventReport.tsx
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
import { CheckCircle2, AlertTriangle, Info, BookOpen } from 'lucide-react';
import type { EventReport, RAGReference, Action } from '@/types/report';

interface EventReportProps {
  reportJson: string; // DB TEXT 컬럼 값
}

export default function EventReport({ reportJson }: EventReportProps) {
  const report: EventReport = JSON.parse(reportJson);
  
  return (
    <div className="space-y-6">
      {/* 헤더 - 기본 정보 */}
      <Card>
        <CardHeader className="space-y-2">
          <div className="flex items-center justify-between">
            <div>
              <Badge variant={getRiskVariant(report.analysis.risk_level)} className="mb-2">
                {report.analysis.risk_level}
              </Badge>
              <Badge variant="outline">{report.analysis.event_type}</Badge>
            </div>
            {report.analysis.risk_score && (
              <div className="text-right">
                <p className="text-sm text-muted-foreground">위험도 점수</p>
                <p className="text-2xl font-bold">{report.analysis.risk_score}</p>
              </div>
            )}
          </div>
          <div className="text-sm text-muted-foreground">
            <p>{new Date(report.event.occurred_at).toLocaleString('ko-KR')}</p>
            <p>{report.event.camera.name} ({report.event.camera.location})</p>
          </div>
        </CardHeader>
        <CardContent>
          <Alert>
            <Info className="h-4 w-4" />
            <AlertDescription>{report.analysis.summary}</AlertDescription>
          </Alert>
        </CardContent>
      </Card>

      {/* 정밀 분석 결과 */}
      {report.precision_analysis && Object.keys(report.precision_analysis).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>정밀 분석 결과</CardTitle>
          </CardHeader>
          <CardContent>
            <PrecisionResult data={report.precision_analysis} />
          </CardContent>
        </Card>
      )}

      {/* RAG 참조 매뉴얼 */}
      {report.rag_references && report.rag_references.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BookOpen className="h-5 w-5" />
              참조 매뉴얼 및 유사 사례
            </CardTitle>
          </CardHeader>
          <CardContent>
            <RAGReferences references={report.rag_references} />
          </CardContent>
        </Card>
      )}

      {/* 권장 대응 조치 */}
      {report.recommended_actions && report.recommended_actions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>AI 권장 대응 조치</CardTitle>
          </CardHeader>
          <CardContent>
            <RecommendedActionsList actions={report.recommended_actions} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// RAG 참조 컴포넌트
function RAGReferences({ references }: { references: RAGReference[] }) {
  return (
    <Accordion type="single" collapsible className="w-full">
      {references.map((ref, idx) => (
        <AccordionItem key={ref.id} value={`ref-${idx}`}>
          <AccordionTrigger className="hover:no-underline">
            <div className="flex items-center justify-between w-full pr-4">
              <div className="flex items-center gap-3">
                <span className="font-medium text-left">{ref.title}</span>
                {ref.category && (
                  <Badge variant="outline" className="text-xs">
                    {ref.category}
                  </Badge>
                )}
              </div>
              <Badge variant="secondary" className="ml-auto">
                관련도 {(ref.relevance_score * 100).toFixed(0)}%
              </Badge>
            </div>
          </AccordionTrigger>

          <AccordionContent className="pt-4">
            <div className="space-y-3 text-sm">
              <div className="flex items-center gap-2 text-muted-foreground">
                <span>출처: {ref.source}</span>
                {ref.metadata?.page && <span>• 페이지 {ref.metadata.page}</span>}
              </div>

              <div className="p-4 bg-muted rounded-md">
                <p className="whitespace-pre-wrap">{ref.content}</p>
              </div>

              {ref.metadata?.last_updated && (
                <p className="text-xs text-muted-foreground">
                  최종 수정: {new Date(ref.metadata.last_updated).toLocaleDateString('ko-KR')}
                </p>
              )}
            </div>
          </AccordionContent>
        </AccordionItem>
      ))}
    </Accordion>
  );
}

// 권장 조치 컴포넌트
function RecommendedActionsList({ actions }: { actions: RecommendedAction[] }) {
  return (
    <ul className="space-y-3">
      {actions.map((action, idx) => (
        <li key={idx} className="flex items-start gap-3 p-3 border rounded-lg">
          <AlertTriangle className="h-5 w-5 text-yellow-600 mt-0.5" />
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-1">
              <span className="font-semibold">{action.title}</span>
              <Badge variant={getPriorityVariant(action.priority)}>
                {action.priority}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">{action.description}</p>
            {action.estimated_time && (
              <p className="text-xs text-muted-foreground mt-1">
                예상 시간: {action.estimated_time}
              </p>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

// 유틸리티 함수
function getRiskVariant(risk: string) {
  switch (risk) {
    case 'ABNORMAL': return 'destructive';
    case 'SUSPICIOUS': return 'default';
    default: return 'secondary';
  }
}

function getPriorityVariant(priority: string) {
  switch (priority) {
    case 'HIGH': return 'destructive';
    case 'MEDIUM': return 'default';
    default: return 'secondary';
  }
}

function PrecisionResult({ data }: { data: Record<string, any> }) {
  return (
    <div className="space-y-2 text-sm">
      <p><strong>위험 수준:</strong> {data.risk || 'N/A'}</p>
      <p><strong>분석 내용:</strong> {data.summary || 'N/A'}</p>
      <p><strong>위험도 점수:</strong> {data.risk_score || 'N/A'}</p>
    </div>
  );
}
```

### 7.3 API Route

```typescript
// app/api/events/[id]/report/route.ts
import { NextResponse } from 'next/server';
import { db } from '@/lib/db'; // Prisma 또는 PostgreSQL 클라이언트

export async function GET(
  request: Request,
  { params }: { params: { id: string } }
) {
  try {
    const event = await db.events.findUnique({
      where: { id: params.id },
      select: {
        id: true,
        report: true,           // TEXT (JSON 문자열)
        rag_references: true,   // JSONB
        created_at: true,
        updated_at: true
      }
    });

    if (!event) {
      return NextResponse.json(
        { error: '이벤트를 찾을 수 없습니다.' },
        { status: 404 }
      );
    }

    // 실제 실행된 조치는 별도 API로 조회 (필요 시)
    // const actions = await db.eventActions.findMany({
    //   where: { eventId: params.id }
    // });

    return NextResponse.json({
      ...event,
      // report는 이미 JSON 문자열이므로 그대로 전달
      // 프론트엔드에서 JSON.parse() 수행
    });
  } catch (error) {
    console.error('Report fetch error:', error);
    return NextResponse.json(
      { error: '서버 오류가 발생했습니다.' },
      { status: 500 }
    );
  }
}
```

---

## 8. Qdrant RAG 통합

### 8.1 Qdrant 클라이언트

```python
# retrieval/retriever.py
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from typing import List, Dict

class QdrantRetriever:
    def __init__(self, url: str, collection: str):
        self.client = QdrantClient(url=url)
        self.collection = collection
    
    async def search_references(
        self,
        query_vector: List[float],
        event_type: str,
        limit: int = 5
    ) -> List[Dict]:
        """
        Qdrant에서 유사 매뉴얼/사례 검색
        
        Args:
            query_vector: 쿼리 임베딩 벡터
            event_type: 이벤트 유형 (ASSAULT, BURGLARY 등)
            limit: 반환 개수
            
        Returns:
            RAG 참조 리스트
        """
        results = self.client.search(
            collection_name=self.collection,
            query_vector=query_vector,
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="category",
                        match=MatchValue(value=event_type)
                    )
                ]
            ),
            limit=limit,
            with_payload=True
        )
        
        return [
            {
                "id": str(hit.id),
                "score": hit.score,
                "payload": hit.payload
            }
            for hit in results
        ]
```

### 8.2 임베딩 모델

```python
# utils.py (추가)
from sentence_transformers import SentenceTransformer

# 전역 모델 (애플리케이션 시작 시 로드)
_embedding_model = None

def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    return _embedding_model

def embed_text(text: str) -> List[float]:
    """텍스트를 벡터로 임베딩"""
    model = get_embedding_model()
    return model.encode(text).tolist()
```

### 8.3 Qdrant 컬렉션 스키마

```python
# scripts/setup_qdrant.py
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance

client = QdrantClient(url="http://localhost:6333")

# 컬렉션 생성
client.create_collection(
    collection_name="safety_manuals",
    vectors_config=VectorParams(
        size=384,  # MiniLM 임베딩 차원
        distance=Distance.COSINE
    )
)

# 샘플 데이터 삽입
client.upsert(
    collection_name="safety_manuals",
    points=[
        {
            "id": "doc-001",
            "vector": [0.1, 0.2, ...],  # 384차원 벡터
            "payload": {
                "source": "안전 매뉴얼 v2.1",
                "title": "폭행 사건 대응 절차",
                "content": "1. 즉시 보안팀에 연락...",
                "category": "ASSAULT",
                "page": 15,
                "last_updated": "2025-12-01"
            }
        }
    ]
)
```

---

## 9. 구현 로드맵

### Phase 1: 백엔드 JSON 구조화 (1-2일)

- [ ] `graph/nodes/generate_report.py` 구현
- [ ] `_format_rag_references()` 헬퍼 함수 작성
- [ ] `_format_recommended_actions()` 헬퍼 함수 작성
- [ ] `graph/nodes/update_backend.py` 수정
  - `PATCH /internal/agent/events/{id}/analysis` API 호출
  - `rag_references`, `report` 필드 DB 직접 업데이트 또는 백엔드 API 확장
- [ ] 단위 테스트 작성

**백엔드 API 확장 필요 (선택):**
- `PATCH /internal/agent/events/{id}/analysis`에 `ragReferences`, `report` 필드 추가

### Phase 2: Qdrant RAG 통합 (2-3일)

- [ ] `retrieval/retriever.py` 구현
- [ ] 임베딩 모델 통합 (`utils.py`)
- [ ] `graph/nodes/precision_analysis.py` 수정 (RAG 검색 추가)
- [ ] Qdrant 컬렉션 생성 스크립트
- [ ] 샘플 매뉴얼 데이터 삽입
- [ ] 통합 테스트

### Phase 3: 프론트엔드 UI (3-4일)

- [ ] `types/report.ts` 타입 정의
- [ ] `components/EventReport.tsx` 메인 컴포넌트
- [ ] `components/RAGReferences.tsx` Accordion 컴포넌트
- [ ] `components/ActionsList.tsx` 대응 조치 컴포넌트
- [ ] `app/api/events/[id]/report/route.ts` API Route
- [ ] 이벤트 상세 페이지에 통합
- [ ] 스타일링 및 반응형 대응

### Phase 4: 테스트 및 최적화 (1-2일)

- [ ] E2E 테스트 (Playwright)
- [ ] 성능 테스트 (JSON 파싱 속도)
- [ ] PostgreSQL JSONB 인덱스 추가
- [ ] 에러 핸들링 강화
- [ ] 문서화 업데이트

---

## 10. 참고 자료

### 기술 문서

- [LangGraph 공식 문서](https://langchain-ai.github.io/langgraph/)
- [Qdrant Python Client](https://qdrant.tech/documentation/frameworks/python/)
- [PostgreSQL JSONB Functions](https://www.postgresql.org/docs/current/functions-json.html)
- [Next.js 15 Documentation](https://nextjs.org/docs)
- [shadcn/ui Components](https://ui.shadcn.com/)

### 관련 파일

- `aegis-ai-agent/README.md` - AI Agent 전체 아키텍처
- `WORKFLOWS.md` - AEGIS 프로젝트 전체 워크플로우
- `WORKFLOWS-QDRANT.md` - Qdrant 벡터 검색 상세 가이드
- `aegis-backend/src/main/java/.../event/Event.java` - 백엔드 엔티티
- `aegis-frontend/src/types/` - 프론트엔드 타입 정의

### 코드 예시

- `graph/nodes/` - LangGraph 노드 구현
- `clients/backend_client.py` - 백엔드 API 통신
- `components/EventReport.tsx` - 보고서 UI 컴포넌트

---

## 부록: 마이그레이션 가이드

### 기존 이벤트 데이터 변환

기존에 `report` 컬럼이 비어있거나 텍스트로 저장된 경우:

```python
# scripts/migrate_reports.py
import json
from datetime import datetime

def migrate_event_report(event):
    """기존 이벤트를 JSON 구조로 변환"""
    
    report_data = {
        "version": "1.0",
        "generated_at": event.updated_at.isoformat(),
        "event": {
            "id": str(event.id),
            "occurred_at": event.occurred_at.isoformat(),
            "camera": {
                "id": str(event.camera_id),
                "name": event.camera.name,
                "location": event.camera.location
            }
        },
        "analysis": {
            "risk_level": event.risk,
            "event_type": event.type,
            "risk_score": event.risk_score,
            "summary": event.summary or '',
            "status": event.status
        },
        "precision_analysis": {},
        "rag_references": event.rag_references or [],
        "recommended_actions": [],
        "clip": {
            "url": event.clip_url,
            "confirmed": bool(event.clip_url)
        }
    }
    
    return json.dumps(report_data, ensure_ascii=False)

# 실행
for event in db.query(Event).filter(Event.report.is_(None)):
    event.report = migrate_event_report(event)
    db.commit()
```

### 백엔드 API 확장 (권장)

현재 `PATCH /internal/agent/events/{id}/analysis` API는 `{risk, type, summary, riskScore}` 필드만 지원합니다.

**확장 제안:**

```java
// EventDto.java (요청 DTO 수정)
public record UpdateAnalysisRequest(
    EventRisk risk,
    EventType type,
    String summary,
    String riskScore,
    List<Map<String, Object>> ragReferences,  // 추가
    String report                              // 추가
) {}

// EventService.java
public void updateEventAnalysis(UUID eventId, UpdateAnalysisRequest request) {
    Event event = eventRepository.findById(eventId)
        .orElseThrow(() -> new BusinessException(ErrorCode.EVENT_NOT_FOUND));
    
    if (request.risk() != null) event.setRisk(request.risk());
    if (request.type() != null) event.setType(request.type());
    if (request.summary() != null) event.setSummary(request.summary());
    if (request.riskScore() != null) event.setRiskScore(request.riskScore());
    if (request.ragReferences() != null) event.setRagReferences(request.ragReferences());
    if (request.report() != null) event.setReport(request.report());
    
    event.setStatus(EventStatus.ANALYZED);
    eventRepository.save(event);
}
```

---

**작성자**: AEGIS AI Team  
**최종 수정**: 2026-02-05  
**버전**: 1.1 (백엔드 README 기반 수정)

