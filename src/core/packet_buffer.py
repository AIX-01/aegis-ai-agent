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
    최근 N초간의 비디오 패킷을 메모리에 저장하는 원형 버퍼.
    VLM 분석 후 영상 클립 생성 요청이 들어오면,
    지정된 시간 범위의 패킷을 '키프레임(I-Frame)'부터 시작하도록 보정하여 반환합니다.
    """

    def __init__(self, buffer_duration: int = 30):
        """
        Args:
            buffer_duration: 패킷을 유지할 시간(초). 기본값 30초.
        """
        self.buffer_duration = buffer_duration
        # 버퍼 구조: (수신_타임스탬프, av.Packet)의 튜플을 저장하는 deque
        self.buffer: deque[Tuple[float, av.Packet]] = deque()
        self.lock = threading.Lock()

    def add_packet(self, packet: av.Packet):
        """
        새로운 패킷을 버퍼에 추가하고, 만료된 패킷을 제거합니다.
        
        Args:
            packet: PyAV 패킷 객체
        """
        # 패킷 수신 시점의 시스템 시간 기록 (검색용)
        now = time.time()
        
        with self.lock:
            self.buffer.append((now, packet))
            
            # 버퍼 유지 시간(buffer_duration)을 초과한 오래된 패킷 제거
            # 버퍼의 맨 앞(가장 오래된 것)을 확인하여 제거
            while self.buffer and (now - self.buffer[0][0] > self.buffer_duration):
                self.buffer.popleft()

    def get_packets(self, start_ts: float, end_ts: float) -> List[av.Packet]:
        """
        특정 시간 범위의 패킷 리스트를 반환합니다.
        
        [Keyframe Back-Tracking 알고리즘]
        요청된 start_ts 시점의 패킷이 키프레임이 아니라면, 
        영상 깨짐을 방지하기 위해 그보다 앞선(과거의) 가장 가까운 키프레임까지
        시작 시점을 당겨서(Back-tracking) 반환합니다.

        Args:
            start_ts: 클립 시작 타임스탬프 (시스템 시간)
            end_ts: 클립 종료 타임스탬프 (시스템 시간)

        Returns:
            av.Packet 리스트 (키프레임부터 시작됨)
        """
        with self.lock:
            if not self.buffer:
                return []
            
            # deque를 리스트로 변환하여 인덱싱 접근 (30초 분량이라 오버헤드 적음)
            buffer_list = list(self.buffer)
            
            # 1. 요청된 start_ts가 버퍼 범위 내에 있는지 확인
            # 버퍼의 가장 마지막(최신) 시간보다 요청 시작 시간이 미래라면 데이터 없음
            if buffer_list[-1][0] < start_ts:
                return []

            # 2. start_ts 이후의 첫 번째 패킷 인덱스 찾기 (Target Start Index)
            target_start_idx = -1
            for i, (ts, pkt) in enumerate(buffer_list):
                if ts >= start_ts:
                    target_start_idx = i
                    break
            
            # 요청 시간이 너무 과거라서 버퍼에 없는 경우 -> 버퍼의 처음부터 시작
            if target_start_idx == -1:
                target_start_idx = 0

            # 3. Keyframe Back-Tracking (뒤로 가며 키프레임 찾기)
            # target_start_idx 부터 0까지 역순으로 탐색
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
            
            # 만약 앞쪽에서 키프레임을 못 찾았다면?
            # 버퍼의 맨 처음이 키프레임이 아닐 수도 있지만, 가용 데이터 중 가장 앞선 것을 사용
            if not found_keyframe:
                # 경고: 키프레임 없이 시작하면 영상 초반이 깨질 수 있음
                # 하지만 데이터가 이것뿐이므로 그냥 0번이나 target_idx 사용
                # 여기서는 최대한 안전하게 버퍼의 처음(0)부터 보냄 (운 좋으면 I-frame일 수 있음)
                final_start_idx = 0

            # 4. 결과 패킷 수집
            result_packets = []
            for i in range(final_start_idx, len(buffer_list)):
                ts, pkt = buffer_list[i]
                
                # 종료 시간 체크
                if ts > end_ts:
                    break
                    
                result_packets.append(pkt)

            return result_packets
