"""
비디오 패킷 버퍼링 모듈
최근 N초간의 패킷을 저장하고 키프레임으로 시작하는 클립을 추출합니다.
"""
import threading
import time
from collections import deque
from typing import List, Tuple
import av


class PacketBuffer:
    """
    최근 N초간의 비디오 패킷을 저장하는 원형 버퍼입니다.

    키프레임 백트래킹: 클립 추출 시 시작점을 가장 가까운 키프레임(I-Frame)으로
    보정하여 화면 깨짐 없는 깨끗한 영상을 보장합니다.
    """

    def __init__(self, buffer_duration: int = 30):
        self.buffer_duration = buffer_duration
        self.buffer: deque[Tuple[float, av.Packet]] = deque()
        self.lock = threading.Lock()

    def add_packet(self, packet: av.Packet) -> None:
        """패킷을 버퍼에 추가하고 오래된 패킷을 제거합니다."""
        now = time.time()
        with self.lock:
            self.buffer.append((now, packet))
            # 버퍼 크기 유지
            while self.buffer and (now - self.buffer[0][0] > self.buffer_duration):
                self.buffer.popleft()

    def get_full_buffer(self, clip_duration: int = 30) -> List[av.Packet]:
        """
        최근 N초 분량의 패킷을 키프레임으로 시작하도록 추출합니다.

        Returns:
            키프레임으로 시작하는 패킷 리스트. 키프레임이 없으면 빈 리스트.
        """
        with self.lock:
            if not self.buffer:
                return []

            packets = list(self.buffer)
            now = time.time()
            start_ts = now - clip_duration

            # 시작 인덱스 찾기
            start_idx = 0
            for i, (ts, _) in enumerate(packets):
                if ts >= start_ts:
                    start_idx = i
                    break

            # 키프레임 백트래킹
            keyframe_idx = None
            for i in range(start_idx, -1, -1):
                if packets[i][1].is_keyframe:
                    keyframe_idx = i
                    break

            # 못 찾으면 전체에서 첫 키프레임 찾기
            if keyframe_idx is None:
                for i, (_, pkt) in enumerate(packets):
                    if pkt.is_keyframe:
                        keyframe_idx = i
                        break

            if keyframe_idx is None:
                return []

            return [pkt for _, pkt in packets[keyframe_idx:]]
