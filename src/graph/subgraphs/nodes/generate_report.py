"""
보고서 생성 노드 (generate_report)

최종 보고서를 생성하고 업로드합니다.
PDF, DOCX, PPTX 형식을 지원합니다.
"""
import logging
from datetime import datetime
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ....config import Config
    from ..state import ResponseAgentState

logger = logging.getLogger(__name__)


def generate_report_node(state: "ResponseAgentState", app_config: "Config") -> Dict[str, Any]:
    """
    최종 보고서를 생성하고 업로드합니다.

    Args:
        state: 현재 에이전트 상태
        app_config: 시스템 설정

    Returns:
        업데이트된 상태 (report)
    """
    from ....services.report_generator import ReportGeneratorService
    from ....clients.backend_client import BackendClient

    camera_name = state.get("camera_name", "")
    camera_location = state.get("camera_location", "")
    event_type = state.get("event_type", "")
    risk_level = state.get("risk_level", "")
    risk_score = state.get("risk_score", 0)
    summary = state.get("summary", "")
    occurred_at = state.get("occurred_at", "")
    actions = state.get("actions", [])
    frames = state.get("frames", [])
    event_id = state.get("event_id", "")

    # 위험 점수 포맷팅
    risk_score_str = f"{risk_score:.2f}" if isinstance(risk_score, (int, float)) else str(risk_score)

    # 마크다운 보고서 내용 생성
    content = f"""# 이상 상황 대응 보고서

## 1. 개요
- **발생 일시**: {occurred_at}
- **위치**: {camera_name} ({camera_location})
- **이벤트 유형**: {event_type}
- **위험도**: {risk_level} (점수: {risk_score_str})

## 2. 상황 요약
{summary}

## 3. 대응 조치
"""

    if actions:
        for i, action in enumerate(actions, 1):
            content += f"{i}. {action.get('description', '조치 내용 없음')}\n"
    else:
        content += "- 결정된 조치 없음\n"

    content += f"""
## 4. 비고
- 보고서 생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 담당 시스템: AEGIS AI Agent
"""

    # 보고서 파일 URL (업로드 후 채워짐)
    file_urls = {"pdf": None, "docx": None, "pptx": None, "hwp": None}

    try:
        # 1. 보고서 파일 생성
        report_generator = ReportGeneratorService()

        report_data = {
            "occurred_at": occurred_at,
            "event_type": event_type,
            "camera_name": camera_name,
            "camera_location": camera_location,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "summary": summary,
            "actions": actions,
        }

        generated_files = report_generator.generate(
            report_data=report_data,
            frames=frames,
            formats=["pdf", "docx", "pptx"]
        )

        logger.info(f"보고서 파일 생성 완료: PDF={generated_files.get('pdf') is not None}, DOCX={generated_files.get('docx') is not None}, PPTX={generated_files.get('pptx') is not None}")

        # 2. 보고서 파일 업로드 (Mock 서버 또는 MinIO)
        if event_id:
            backend_client = BackendClient(app_config)

            # 업로드할 파일들과 Content-Type 매핑
            content_types = {
                "pdf": "application/pdf",
                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            }

            for fmt, file_bytes in generated_files.items():
                if file_bytes and fmt in content_types:
                    try:
                        # presigned URL 획득
                        url_info = backend_client.get_report_upload_url(event_id, fmt)
                        if url_info:
                            upload_url = url_info.get("upload_url")
                            report_path = url_info.get("report_path")

                            # 파일 업로드
                            if backend_client.upload_report(upload_url, file_bytes, content_types[fmt]):
                                file_urls[fmt] = report_path
                                logger.info(f"✅ [{event_id}] {fmt.upper()} 보고서 업로드 완료: {report_path}")
                            else:
                                logger.error(f"❌ [{event_id}] {fmt.upper()} 보고서 업로드 실패")
                        else:
                            logger.error(f"❌ [{event_id}] {fmt.upper()} 업로드 URL 획득 실패")
                    except Exception as e:
                        logger.error(f"❌ [{event_id}] {fmt.upper()} 보고서 업로드 중 오류: {e}")
        else:
            logger.warning("event_id가 없어 보고서 업로드를 건너뜁니다.")

    except Exception as e:
        logger.error(f"보고서 파일 생성/업로드 실패: {e}", exc_info=True)

    # 보고서 Dict 구조 (files에 URL 저장)
    report = {
        "content": content,
        "files": file_urls,
        "generated_at": datetime.now().isoformat()
    }

    logger.info(f"보고서 생성 완료: {len(content)} 자, 업로드된 파일: {[k for k, v in file_urls.items() if v]}")

    return {"report": report}

