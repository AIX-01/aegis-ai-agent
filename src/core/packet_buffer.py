"""
비디오 패킷 버퍼링 및 키프레임 백트래킹 모듈
"""
import threading
import time
from collections import deque
from typing import List, Tuple, Optional
import av

class PacketBuffer:
    """
    최근 N초간의 비디오 패킷을 메모리에 저장하는 원형 버퍼입니다.
    
    [핵심 알고리즘: Keyframe Back-tracking]
    일반적인 비디오 스트림은 I-Frame(전체 이미지)과 P/B-Frame(차이점 데이터)으로 구성됩니다.
    VLM 분석 시점에서 단순히 30초 전 패킷부터 잘라내면, 시작점이 P-Frame일 경우
    다음 I-Frame이 나오기 전까지 화면이 깨지거나 녹색으로 보이는 현상이 발생합니다.
    
    이 버퍼는 추출 요청 시 시작 시점보다 과거에 있는 '가장 가까운 키프레임(I-Frame)'을
    역추적(Back-tracking)하여 추출 시작점을 보정함으로써, 깨지지 않는 깨끗한 영상을 보장합니다.
    """

    def __init__(self, buffer_duration: int = 30):
        """
        Args:
            buffer_duration: 패킷을 메모리에 유지할 최대 시간(초). 기본값 30초.
        """
        self.buffer_duration = buffer_duration
        # 수신 시간과 패킷 객체를 함께 저장하여 시간 기반 검색 지원
        self.buffer: deque[Tuple[float, av.Packet]] = deque()
        self.lock = threading.Lock()

    def add_packet(self, packet: av.Packet):
        """
        새로운 패킷을 버퍼에 추가합니다.
        가용 메모리 유지를 위해 설정된 시간(30초)이 지난 오래된 패킷은 자동으로 제거합니다.
        """
        now = time.time()
        
        with self.lock:
            self.buffer.append((now, packet))
            
            # 버퍼의 맨 앞(가장 오래된 데이터)부터 확인하여 유효 기간이 지난 패킷을 popleft()로 제거
            while self.buffer and (now - self.buffer[0][0] > self.buffer_duration):
                self.buffer.popleft()

    def get_packets(self, start_ts: float, end_ts: float) -> List[av.Packet]:
        """
        지정된 시간 범위의 패킷을 추출하되, 시작점을 키프레임으로 보정하여 반환합니다.
        
        작동 원리:
        1. 요청된 시작 시점(start_ts)에 해당하는 패킷 인덱스를 찾습니다.
        2. 해당 인덱스부터 '과거 방향'으로 탐색하며 가장 먼저 만나는 키프레임을 찾습니다.
        3. 실제 데이터는 보정된 키프레임 인덱스부터 종료 시점까지 수집합니다.
        """
        with self.lock:
            if not self.buffer:
                return []
            
            buffer_list = list(self.buffer)
            
            # [Step 1] 요청된 시작 시점이 현재 버퍼가 보유한 가장 최신 데이터보다 뒤인지 확인
            if buffer_list[-1][0] < start_ts:
                return []

            # [Step 2] 타겟 인덱스 찾기 (요청 시점과 가장 가까운 패킷)
            target_start_idx = -1
            for i, (ts, pkt) in enumerate(buffer_list):
                if ts >= start_ts:
                    target_start_idx = i
                    break
            
            if target_start_idx == -1:
                target_start_idx = 0

            # [Step 3] Keyframe Back-Tracking (뒤로 가며 I-Frame 탐색)
            # 시작점이 깨지지 않도록 하기 위한 핵심 보정 단계입니다.
            final_start_idx = target_start_idx
            curr_idx = target_start_idx
            found_keyframe = False
            
            while curr_idx >= 0:
                pkt = buffer_list[curr_idx][1]
                if pkt.is_keyframe:
                    final_start_idx = curr_idx
                    found_keyframe = True
                    break
                curr_idx -= 1
            
            # 만약 버퍼 범위 내에서 키프레임을 찾지 못했다면 가용한 가장 오래된 데이터부터 시작
            if not found_keyframe:
                final_start_idx = 0

            # [Step 4] 보정된 시작점부터 종료 시간까지의 모든 패킷 수집
            result_packets = []
            for i in range(final_start_idx, len(buffer_list)):
                ts, pkt = buffer_list[i]
                if ts > end_ts:
                    break
                result_packets.append(pkt)

            return result_packets

    def get_full_buffer(self, clip_duration: int = 30) -> List[av.Packet]:
        """
        버퍼에 저장된 최근 N초 분량의 전체 패킷을 추출합니다.

        Args:
            clip_duration: 추출할 클립 길이(초). 기본값 30초.

        Returns:
            키프레임으로 시작하는 패킷 리스트
        """
        with self.lock:
            if not self.buffer:
                return []

            buffer_list = list(self.buffer)
            now = time.time()

            # 클립 시작 시점 계산 (현재 - clip_duration)
            target_start_ts = now - clip_duration

            # 시작 인덱스 찾기
            target_start_idx = 0
            for i, (ts, pkt) in enumerate(buffer_list):
                if ts >= target_start_ts:
                    target_start_idx = i
                    break

            # 키프레임 백트래킹 (키프레임을 찾을 때까지 과거로)
            final_start_idx = target_start_idx
            found_keyframe = False
            for i in range(target_start_idx, -1, -1):
                if buffer_list[i][1].is_keyframe:
                    final_start_idx = i
                    found_keyframe = True
                    break

            # 키프레임을 못 찾으면 버퍼 전체에서 첫 키프레임 찾기
            if not found_keyframe:
                for i, (ts, pkt) in enumerate(buffer_list):
                    if pkt.is_keyframe:
                        final_start_idx = i
                        found_keyframe = True
                        break

            # 그래도 못 찾으면 빈 리스트 반환
            if not found_keyframe:
                return []

            # 시작점부터 끝까지 모든 패킷 반환
            return [pkt for ts, pkt in buffer_list[final_start_idx:]]

