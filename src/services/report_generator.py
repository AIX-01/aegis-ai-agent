"""
보고서 생성 서비스

CCTV 이상 상황 대응 보고서를 HTML, PDF, DOCX, PPTX 형식으로 생성합니다.
템플릿 기반으로 플레이스홀더를 치환하고 이미지를 삽입합니다.
"""
import io
import os
import base64
import logging
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Literal

logger = logging.getLogger(__name__)


class ReportGeneratorService:
    """보고서 생성 서비스"""

    def __init__(self, template_dir: Optional[Path] = None):
        """
        보고서 생성기 초기화

        Args:
            template_dir: 템플릿 디렉토리 경로 (None이면 기본 경로 사용)
        """
        if template_dir is None:
            # 기본 경로: src/services/../templates/reports
            self.template_dir = Path(__file__).resolve().parent.parent.parent / "templates" / "reports"
        else:
            self.template_dir = Path(template_dir)

        logger.info(f"ReportGeneratorService 초기화: 템플릿 경로={self.template_dir}")

    def generate(
        self,
        report_data: Dict[str, Any],
        frames: List[bytes],
        formats: List[Literal["html", "pdf", "docx", "pptx"]] = None
    ) -> Dict[str, Optional[bytes]]:
        """
        보고서를 생성합니다.

        Args:
            report_data: 보고서 데이터
                - occurred_at: 발생 일시 (datetime 또는 str)
                - event_type: 이벤트 유형
                - camera_name: 카메라 이름
                - camera_location: 카메라 위치
                - risk_level: 위험 등급
                - risk_score: 위험 점수
                - summary: 상황 요약
                - actions: 대응 조치 리스트 [{"type": str, "description": str}, ...]
            frames: CCTV 캡처 이미지 리스트 (JPEG bytes, 최대 8장)
            formats: 생성할 형식 리스트 (기본값: ["html", "pdf", "docx", "pptx"])

        Returns:
            {
                "html": bytes or None,
                "pdf": bytes or None,
                "docx": bytes or None,
                "pptx": bytes or None
            }
        """
        if formats is None:
            formats = ["html", "pdf", "docx", "pptx"]

        result = {"html": None, "pdf": None, "docx": None, "pptx": None}

        # 데이터 정규화
        normalized_data = self._normalize_data(report_data, frames)

        try:
            if "html" in formats or "pdf" in formats:
                html_bytes = self._generate_html(normalized_data, frames)
                if html_bytes:
                    result["html"] = html_bytes
                    if "pdf" in formats:
                        result["pdf"] = self._html_to_pdf(html_bytes)

            if "docx" in formats:
                result["docx"] = self._generate_docx(normalized_data, frames)

            if "pptx" in formats:
                result["pptx"] = self._generate_pptx(normalized_data, frames)

        except Exception as e:
            logger.error(f"보고서 생성 실패: {e}", exc_info=True)

        return result

    def _normalize_data(self, report_data: Dict[str, Any], frames: List[bytes]) -> Dict[str, Any]:
        """데이터를 템플릿용으로 정규화합니다."""
        # 발생 일시 포맷팅
        occurred_at = report_data.get("occurred_at", "")
        if isinstance(occurred_at, datetime):
            occurred_at_str = occurred_at.strftime("%Y년 %m월 %d일 %H:%M:%S")
        else:
            occurred_at_str = str(occurred_at)

        # 위험 점수 포맷팅
        risk_score = report_data.get("risk_score", 0)
        if isinstance(risk_score, float):
            risk_score_str = f"{risk_score:.2f}"
        else:
            risk_score_str = str(risk_score)

        # actions 포맷팅
        actions = report_data.get("actions", [])
        actions_html = "\n".join([f"        <li>{a.get('description', '')}</li>" for a in actions])
        actions_text = "\n".join([f"• {a.get('description', '')}" for a in actions])

        # HTML용 이미지 태그
        frames_html = self._frames_to_html(frames)

        return {
            "occurred_at": occurred_at_str,
            "event_type": report_data.get("event_type", ""),
            "camera_name": report_data.get("camera_name", ""),
            "camera_location": report_data.get("camera_location", ""),
            "risk_level": report_data.get("risk_level", ""),
            "risk_score": risk_score_str,
            "summary": report_data.get("summary", ""),
            "actions": actions_html,
            "actions_text": actions_text,
            "frames": frames_html,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _frames_to_html(self, frames: List[bytes]) -> str:
        """프레임들을 HTML 테이블로 변환 (4x2 그리드)"""
        if not frames:
            return "<p>이미지 없음</p>"

        html_parts = ['<table style="width: 100%; border-collapse: collapse; table-layout: fixed;">']

        for row in range(2):
            html_parts.append('<tr>')
            for col in range(4):
                idx = row * 4 + col
                if idx < len(frames):
                    b64 = base64.b64encode(frames[idx]).decode('utf-8')
                    html_parts.append(
                        f'<td style="width: 25%; padding: 4px; text-align: center; vertical-align: top;">'
                        f'<img src="data:image/jpeg;base64,{b64}" '
                        f'alt="Frame {idx+1}" '
                        f'style="width: 100%; max-width: 180px; border: 1px solid #ddd;">'
                        f'</td>'
                    )
                else:
                    html_parts.append('<td></td>')
            html_parts.append('</tr>')

        html_parts.append('</table>')
        return '\n'.join(html_parts)

    def _generate_html(self, data: Dict[str, Any], frames: List[bytes]) -> Optional[bytes]:
        """HTML 보고서 생성"""
        template_path = self.template_dir / "report_template.html"

        if not template_path.exists():
            logger.warning(f"HTML 템플릿 없음: {template_path}")
            return None

        try:
            with open(template_path, "r", encoding="utf-8") as f:
                template = f.read()

            # 플레이스홀더 치환
            result = template
            for key, value in data.items():
                result = result.replace(f"{{{{{key}}}}}", str(value))

            logger.info("HTML 보고서 생성 완료")
            return result.encode("utf-8")

        except Exception as e:
            logger.error(f"HTML 생성 실패: {e}")
            return None

    def _html_to_pdf(self, html_bytes: bytes) -> Optional[bytes]:
        """HTML을 PDF로 변환"""
        try:
            import pdfkit
            import platform

            # Windows에서 wkhtmltopdf 경로 지정
            config = None
            if platform.system() == "Windows":
                wkhtmltopdf_path = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
                if os.path.exists(wkhtmltopdf_path):
                    config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)

            options = {
                'encoding': 'UTF-8',
                'enable-local-file-access': ''
            }

            # 임시 파일로 변환
            with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp_html:
                tmp_html.write(html_bytes)
                tmp_html_path = tmp_html.name

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
                tmp_pdf_path = tmp_pdf.name

            try:
                if config:
                    pdfkit.from_file(tmp_html_path, tmp_pdf_path, configuration=config, options=options)
                else:
                    pdfkit.from_file(tmp_html_path, tmp_pdf_path, options=options)

                with open(tmp_pdf_path, "rb") as f:
                    pdf_bytes = f.read()

                logger.info("PDF 보고서 생성 완료")
                return pdf_bytes

            finally:
                os.unlink(tmp_html_path)
                os.unlink(tmp_pdf_path)

        except ImportError:
            logger.warning("pdfkit 설치 필요: pip install pdfkit")
            return None
        except Exception as e:
            logger.error(f"PDF 변환 실패: {e}")
            return None

    def _generate_docx(self, data: Dict[str, Any], frames: List[bytes]) -> Optional[bytes]:
        """DOCX 보고서 생성"""
        try:
            from docx import Document
            from docx.shared import Inches
            from docx.enum.table import WD_TABLE_ALIGNMENT
            from docx.enum.text import WD_ALIGN_PARAGRAPH
        except ImportError:
            logger.warning("python-docx 설치 필요: pip install python-docx")
            return None

        template_path = self.template_dir / "report_template.docx"

        if not template_path.exists():
            logger.warning(f"DOCX 템플릿 없음: {template_path}")
            return None

        try:
            doc = Document(template_path)

            def replace_placeholders_in_paragraph(para, data, frames):
                """단락에서 플레이스홀더를 치환합니다. run이 나뉘어진 경우도 처리."""
                # 전체 텍스트 추출 (모든 run을 합침)
                full_text = "".join([run.text for run in para.runs])

                if not full_text.strip():
                    return False

                # 이미지 플레이스홀더 처리
                if "{{frames}}" in full_text:
                    for run in para.runs:
                        run.text = ""
                    for i, frame in enumerate(frames[:8]):
                        run = para.add_run()
                        run.add_picture(io.BytesIO(frame), width=Inches(1.2))
                    return True  # 이미지 처리됨

                # Frame 1 ~ Frame 8 처리
                for i in range(1, 9):
                    if f"Frame {i}" in full_text and i <= len(frames):
                        for run in para.runs:
                            run.text = ""
                        run = para.add_run()
                        run.add_picture(io.BytesIO(frames[i-1]), width=Inches(1.8))
                        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        return True  # 이미지 처리됨

                # 텍스트 플레이스홀더 치환
                new_text = full_text
                for key, value in data.items():
                    if key == "frames":
                        continue
                    placeholder = f"{{{{{key}}}}}"
                    if placeholder in new_text:
                        if key == "actions":
                            value = data["actions_text"]
                        new_text = new_text.replace(placeholder, str(value))

                # 텍스트가 변경된 경우에만 업데이트
                if new_text != full_text:
                    # 첫 번째 run에 전체 텍스트 넣고 나머지는 비움
                    if para.runs:
                        para.runs[0].text = new_text
                        for run in para.runs[1:]:
                            run.text = ""
                    else:
                        para.add_run(new_text)

                return False  # 이미지 아님

            # 단락에서 플레이스홀더 치환
            for para in doc.paragraphs:
                replace_placeholders_in_paragraph(para, data, frames)

            # 테이블에서 플레이스홀더 치환
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for para in cell.paragraphs:
                            image_processed = replace_placeholders_in_paragraph(para, data, frames)
                            if image_processed:
                                cell.vertical_alignment = WD_TABLE_ALIGNMENT.CENTER

            # 머리글(Header)과 바닥글(Footer)에서 플레이스홀더 치환
            for section in doc.sections:
                # 머리글 처리
                for header in [section.header, section.first_page_header, section.even_page_header]:
                    if header is not None:
                        for para in header.paragraphs:
                            replace_placeholders_in_paragraph(para, data, frames)
                        for table in header.tables:
                            for row in table.rows:
                                for cell in row.cells:
                                    for para in cell.paragraphs:
                                        replace_placeholders_in_paragraph(para, data, frames)

                # 바닥글 처리
                for footer in [section.footer, section.first_page_footer, section.even_page_footer]:
                    if footer is not None:
                        for para in footer.paragraphs:
                            replace_placeholders_in_paragraph(para, data, frames)
                        for table in footer.tables:
                            for row in table.rows:
                                for cell in row.cells:
                                    for para in cell.paragraphs:
                                        replace_placeholders_in_paragraph(para, data, frames)

            # BytesIO에 저장
            buffer = io.BytesIO()
            doc.save(buffer)
            buffer.seek(0)

            logger.info("DOCX 보고서 생성 완료")
            return buffer.getvalue()

        except Exception as e:
            logger.error(f"DOCX 생성 실패: {e}", exc_info=True)
            return None

    def _generate_pptx(self, data: Dict[str, Any], frames: List[bytes]) -> Optional[bytes]:
        """PPTX 보고서 생성"""
        try:
            from pptx import Presentation
            from pptx.util import Inches
        except ImportError:
            logger.warning("python-pptx 설치 필요: pip install python-pptx")
            return None

        template_path = self.template_dir / "report_template.pptx"

        if not template_path.exists():
            logger.warning(f"PPTX 템플릿 없음: {template_path}")
            return None

        try:
            prs = Presentation(template_path)

            def replace_placeholders_in_pptx_paragraph(para, data):
                """
                PPTX 단락에서 플레이스홀더를 치환합니다.
                run이 나뉘어진 경우도 처리합니다.

                Args:
                    para: PPTX의 paragraph 객체
                    data: 치환할 데이터 딕셔너리
                """
                # 전체 텍스트 추출 (모든 run을 합침)
                full_text = "".join([run.text for run in para.runs])

                if not full_text.strip():
                    return

                # 텍스트 플레이스홀더 치환
                new_text = full_text
                for key, value in data.items():
                    if key == "frames":
                        continue
                    placeholder = f"{{{{{key}}}}}"
                    if placeholder in new_text:
                        # actions 키의 경우 actions_text 사용
                        if key == "actions" and "actions_text" in data:
                            value = data["actions_text"]
                        new_text = new_text.replace(placeholder, str(value))

                # 텍스트가 변경된 경우에만 업데이트
                if new_text != full_text:
                    # 첫 번째 run에 전체 텍스트 넣고 나머지는 비움
                    if para.runs:
                        para.runs[0].text = new_text
                        for run in para.runs[1:]:
                            run.text = ""

            for slide in prs.slides:
                # 텍스트 프레임에서 플레이스홀더 치환
                for shape in slide.shapes:
                    if hasattr(shape, "text_frame"):
                        for para in shape.text_frame.paragraphs:
                            replace_placeholders_in_pptx_paragraph(para, data)

                    # 테이블 처리
                    if shape.has_table:
                        for row in shape.table.rows:
                            for cell in row.cells:
                                for para in cell.text_frame.paragraphs:
                                    replace_placeholders_in_pptx_paragraph(para, data)

                # {{frames}} 플레이스홀더에 이미지 삽입
                for shape in slide.shapes:
                    if hasattr(shape, "text_frame"):
                        if "{{frames}}" in shape.text_frame.text:
                            shape_left = shape.left
                            shape_top = shape.top
                            shape_width = shape.width
                            shape_height = shape.height

                            for para in shape.text_frame.paragraphs:
                                for run in para.runs:
                                    run.text = run.text.replace("{{frames}}", "")

                            # 4x2 그리드 이미지 배치
                            gap = Inches(0.08)
                            img_width = (shape_width - gap * 3) / 4
                            img_height = (shape_height - gap) / 2

                            for i, frame in enumerate(frames[:8]):
                                row = i // 4
                                col = i % 4
                                left = shape_left + col * (img_width + gap)
                                top = shape_top + row * (img_height + gap)
                                slide.shapes.add_picture(
                                    io.BytesIO(frame),
                                    left, top,
                                    width=img_width
                                )

            # BytesIO에 저장
            buffer = io.BytesIO()
            prs.save(buffer)
            buffer.seek(0)

            logger.info("PPTX 보고서 생성 완료")
            return buffer.getvalue()

        except Exception as e:
            logger.error(f"PPTX 생성 실패: {e}", exc_info=True)
            return None

