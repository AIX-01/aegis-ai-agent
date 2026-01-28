"""
VLM 응답을 분석하고 트리거 조건을 결정합니다.
"""
import logging
from typing import Dict, Any, Optional
from .config import TRIGGER_CATEGORIES


class TriggerAnalyzer:
    """VLM 응답 분석기"""

    def __init__(self, config):
        """
        트리거 분석기 초기화

        인자:
            config: 시스템 설정
        """
        self.config = config
        self.logger = logging.getLogger("aegis-agent.trigger")

        # 통계
        self.total_analyzed = 0
        self.total_triggered = 0
        self.total_normal = 0

        # 카테고리별 통계
        self.primary_categories = {}
        self.secondary_categories = {}

    def should_trigger(self, vlm_response: Optional[Dict[str, Any]]) -> bool:
        """
        VLM 응답을 기반으로 트리거 조건이 충족되었는지 확인

        인자:
            vlm_response: VLM API 응답 딕셔너리

        반환값:
            정밀 분석을 트리거해야 하면 True
        """
        if vlm_response is None:
            self.logger.warning("VLM 응답 없음 - 트리거 안 함")
            return False

        self.total_analyzed += 1

        # 1차 카테고리 추출
        primary = vlm_response.get("primary_category", "").lower()

        # 통계 업데이트
        self.primary_categories[primary] = self.primary_categories.get(primary, 0) + 1

        # 2차 카테고리 추출 (존재하는 경우)
        secondary = vlm_response.get("secondary_category", "").lower()
        if secondary:
            self.secondary_categories[secondary] = (
                self.secondary_categories.get(secondary, 0) + 1
            )

        # 트리거 조건 확인
        is_triggered = primary in TRIGGER_CATEGORIES

        if is_triggered:
            self.total_triggered += 1
            confidence = vlm_response.get("confidence", 0.0)

            self.logger.info(
                f"[트리거] 발동! - "
                f"1차: {primary}, "
                f"2차: {secondary or 'N/A'}, "
                f"신뢰도: {confidence:.2f}, "
                f"발동률: {self.total_triggered}/{self.total_analyzed} "
                f"({100 * self.total_triggered / self.total_analyzed:.1f}%)"
            )
        else:
            self.total_normal += 1
            self.logger.debug(
                f"[정상] - "
                f"1차: {primary}, "
                f"2차: {secondary or 'N/A'}"
            )

        return is_triggered

    def parse_response(self, vlm_response: Dict[str, Any]) -> Dict[str, Any]:
        """
        VLM 응답 파싱 및 구조화

        인자:
            vlm_response: 원본 VLM 응답

        반환값:
            구조화된 응답 딕셔너리
        """
        return {
            "primary_category": vlm_response.get("primary_category", "unknown"),
            "secondary_category": vlm_response.get("secondary_category", ""),
            "confidence": vlm_response.get("confidence", 0.0),
            "description": vlm_response.get("description", ""),
            "timestamp": vlm_response.get("timestamp", ""),
        }

    def get_stats(self) -> Dict[str, Any]:
        """트리거 통계 조회"""
        trigger_rate = (
            100 * self.total_triggered / self.total_analyzed
            if self.total_analyzed > 0
            else 0
        )

        return {
            "total_analyzed": self.total_analyzed,
            "total_triggered": self.total_triggered,
            "total_normal": self.total_normal,
            "trigger_rate": trigger_rate,
            "primary_categories": dict(self.primary_categories),
            "secondary_categories": dict(self.secondary_categories),
        }

    def log_summary(self):
        """통계 요약 로그 출력"""
        stats = self.get_stats()

        self.logger.info("=" * 80)
        self.logger.info("트리거 분석 통계")
        self.logger.info("=" * 80)
        self.logger.info(f"총 분석: {stats['total_analyzed']}")
        self.logger.info(f"트리거 발동: {stats['total_triggered']}")
        self.logger.info(f"정상: {stats['total_normal']}")
        self.logger.info(f"발동률: {stats['trigger_rate']:.1f}%")

        if stats['primary_categories']:
            self.logger.info("1차 카테고리 분포:")
            for category, count in sorted(
                stats['primary_categories'].items(), key=lambda x: x[1], reverse=True
            ):
                percentage = 100 * count / stats['total_analyzed']
                self.logger.info(f"  {category}: {count} ({percentage:.1f}%)")

        if stats['secondary_categories']:
            self.logger.info("2차 카테고리 분포:")
            for category, count in sorted(
                stats['secondary_categories'].items(), key=lambda x: x[1], reverse=True
            ):
                percentage = 100 * count / stats['total_analyzed']
                self.logger.info(f"  {category}: {count} ({percentage:.1f}%)")

        self.logger.info("=" * 80)
