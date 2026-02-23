"""
EFS 패킷 버퍼: Ingest/Worker 간 패킷 공유를 위한 EFS 읽기/쓰기

Ingest 모드: PacketBuffer 내용을 주기적으로 EFS에 덤프
Worker 모드: EFS에서 패킷을 읽어 MP4로 muxing

파일 구조:
  /efs/buffers/{camera_id}/packets.bin  - 직렬화된 패킷 데이터
  /efs/buffers/{camera_id}/meta.json    - 스트림 메타데이터 (codec, resolution 등)
"""
import io
import json
import logging
import os
import pickle
import time
import threading
from typing import Dict, Any, Optional, List

logger = logging.getLogger("aegis-agent.efs_buffer")


class EFSPacketWriter:
    """
    Ingest 모드: PacketBuffer → EFS 파일 덤프

    Producer가 주기적으로 호출하여 현재 PacketBuffer 내용을
    EFS 공유 스토리지에 직렬화하여 저장합니다.
    """

    def __init__(self, base_path: str):
        """
        Args:
            base_path: EFS 마운트 경로 (예: /efs/buffers)
        """
        self.base_path = base_path
        os.makedirs(base_path, exist_ok=True)

    def dump_buffer(self, camera_id: str, packet_buffer, source_stream_info: Optional[Dict] = None):
        """
        PacketBuffer의 현재 내용을 EFS에 덤프합니다.

        Args:
            camera_id: 카메라 ID
            packet_buffer: PacketBuffer 인스턴스 (get_full_buffer() 사용)
            source_stream_info: 스트림 메타데이터 (codec, width, height 등)
        """
        camera_dir = os.path.join(self.base_path, camera_id)
        os.makedirs(camera_dir, exist_ok=True)

        try:
            # 패킷 데이터 직렬화
            # PacketBuffer.buffer는 deque[(timestamp, av.Packet)]
            # av.Packet → bytes로 변환하여 pickle 저장
            packets_data = []
            with packet_buffer.lock:
                for ts, pkt in packet_buffer.buffer:
                    packets_data.append({
                        "timestamp": ts,
                        "data": bytes(pkt),
                        "pts": pkt.pts,
                        "dts": pkt.dts,
                        "is_keyframe": pkt.is_keyframe,
                    })

            if not packets_data:
                return

            # 원자적 쓰기 (임시 파일 → rename)
            packets_path = os.path.join(camera_dir, "packets.bin")
            tmp_path = packets_path + ".tmp"
            with open(tmp_path, "wb") as f:
                pickle.dump(packets_data, f)
            os.replace(tmp_path, packets_path)

            # 스트림 메타정보 저장 (변경 시에만)
            if source_stream_info:
                meta_path = os.path.join(camera_dir, "meta.json")
                # time_base, average_rate 등 Fraction 타입은 문자열로 변환
                serializable_meta = {}
                for k, v in source_stream_info.items():
                    if k == "extradata" and v is not None:
                        import base64
                        serializable_meta[k] = base64.b64encode(v).decode("ascii")
                    elif hasattr(v, "numerator"):
                        # Fraction 타입
                        serializable_meta[k] = f"{v.numerator}/{v.denominator}"
                    else:
                        serializable_meta[k] = v

                with open(meta_path, "w") as f:
                    json.dump(serializable_meta, f)

            logger.debug(f"[{camera_id}] EFS 덤프 완료: {len(packets_data)}개 패킷")

        except Exception as e:
            logger.error(f"[{camera_id}] EFS 덤프 실패: {e}", exc_info=True)

    def cleanup_old_cameras(self, active_camera_ids: set, max_age_seconds: int = 300):
        """
        더 이상 활성화되지 않은 카메라의 EFS 데이터를 정리합니다.

        Args:
            active_camera_ids: 현재 활성 카메라 ID 집합
            max_age_seconds: 이 시간보다 오래된 비활성 카메라 데이터 삭제
        """
        try:
            for entry in os.scandir(self.base_path):
                if entry.is_dir() and entry.name not in active_camera_ids:
                    packets_path = os.path.join(entry.path, "packets.bin")
                    if os.path.exists(packets_path):
                        age = time.time() - os.path.getmtime(packets_path)
                        if age > max_age_seconds:
                            import shutil
                            shutil.rmtree(entry.path, ignore_errors=True)
                            logger.info(f"[{entry.name}] EFS 데이터 정리 완료 (age: {age:.0f}초)")
        except Exception as e:
            logger.error(f"EFS 정리 실패: {e}")


class EFSPacketReader:
    """
    Worker 모드: EFS → 패킷 읽기 → muxing

    Worker가 이상 감지 시 호출하여 EFS에서 패킷을 읽고
    MP4 클립으로 변환합니다.
    """

    def __init__(self, base_path: str):
        """
        Args:
            base_path: EFS 마운트 경로 (예: /efs/buffers)
        """
        self.base_path = base_path

    def read_and_mux(self, camera_id: str, clip_duration: int = 30) -> Optional[io.BytesIO]:
        """
        EFS에서 패킷을 읽어 MP4로 muxing합니다.

        Args:
            camera_id: 카메라 ID
            clip_duration: 클립 길이 (초)

        Returns:
            MP4 데이터가 담긴 BytesIO 객체, 실패 시 None
        """
        import av
        from ..core.muxer import mux_packets_to_mp4

        camera_dir = os.path.join(self.base_path, camera_id)
        packets_path = os.path.join(camera_dir, "packets.bin")
        meta_path = os.path.join(camera_dir, "meta.json")

        if not os.path.exists(packets_path) or not os.path.exists(meta_path):
            logger.warning(f"[{camera_id}] EFS 패킷 데이터를 찾을 수 없습니다.")
            return None

        try:
            # 메타데이터 읽기
            with open(meta_path, "r") as f:
                meta = json.load(f)

            # extradata를 bytes로 복원
            if meta.get("extradata"):
                import base64
                meta["extradata"] = base64.b64decode(meta["extradata"])

            # time_base, average_rate를 Fraction으로 복원
            from fractions import Fraction
            for key in ("time_base", "average_rate"):
                if key in meta and isinstance(meta[key], str) and "/" in meta[key]:
                    num, den = meta[key].split("/")
                    meta[key] = Fraction(int(num), int(den))

            # 패킷 데이터 읽기
            with open(packets_path, "rb") as f:
                packets_data = pickle.load(f)

            if not packets_data:
                logger.warning(f"[{camera_id}] EFS 패킷이 비어있습니다.")
                return None

            # clip_duration 범위의 패킷만 필터링
            now = time.time()
            start_ts = now - clip_duration
            filtered = [p for p in packets_data if p["timestamp"] >= start_ts]
            if not filtered:
                filtered = packets_data  # 필터링 결과가 없으면 전체 사용

            # 키프레임 백트래킹
            keyframe_idx = None
            for i in range(len(filtered) - 1, -1, -1):
                if filtered[i]["is_keyframe"]:
                    keyframe_idx = i
                    break
            # 뒤에서부터 못 찾으면 앞에서부터 찾기
            if keyframe_idx is None:
                for i, p in enumerate(filtered):
                    if p["is_keyframe"]:
                        keyframe_idx = i
                        break

            if keyframe_idx is None:
                logger.warning(f"[{camera_id}] 키프레임을 찾을 수 없습니다.")
                return None

            # av.Packet 복원
            av_packets = []
            for p in filtered[keyframe_idx:]:
                pkt = av.Packet(p["data"])
                pkt.pts = p["pts"]
                pkt.dts = p["dts"]
                pkt.is_keyframe = p["is_keyframe"]
                av_packets.append(pkt)

            # muxing
            mp4_file = mux_packets_to_mp4(av_packets, meta)
            if mp4_file and mp4_file.getbuffer().nbytes > 0:
                logger.info(f"[{camera_id}] EFS → MP4 muxing 완료: {mp4_file.getbuffer().nbytes} bytes")
                return mp4_file

            return None

        except Exception as e:
            logger.error(f"[{camera_id}] EFS 읽기/muxing 실패: {e}", exc_info=True)
            return None
