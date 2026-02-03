"""
패킷들을 MP4 컨테이너로 Muxing(Remuxing)하는 모듈
"""
import io
import logging
from typing import List
import av

logger = logging.getLogger("aegis-agent.muxer")

def mux_packets_to_mp4(packets: List[av.Packet], source_stream: av.video.stream.VideoStream) -> io.BytesIO:
    """
    재인코딩 없이 패킷 리스트를 MP4 형식으로 Muxing하여 메모리 객체로 반환합니다.

    Args:
        packets: Muxing할 PyAV 패킷 리스트 (키프레임부터 시작되어야 함)
        source_stream: 원본 비디오 스트림 (코덱 설정 및 타임베이스 참조용)

    Returns:
        MP4 데이터가 담긴 io.BytesIO 객체
    """
    if not packets:
        logger.warning("Muxing할 패킷이 없습니다.")
        return io.BytesIO()

    # 메모리 내 출력 버퍼 생성
    output_buffer = io.BytesIO()
    
    # 출력 컨테이너 열기 (mp4 포맷)
    output_container = av.open(output_buffer, mode='w', format='mp4')

    # 출력 스트림 생성 (원본 스트림의 설정 복사)
    # template 인자를 사용하여 원본 스트림의 코덱 설정을 그대로 복제합니다.
    output_stream = output_container.add_stream(template=source_stream)
    
    # MP4 컨테이너는 대개 'faststart'와 같은 플래그를 사용하여 스트리밍 최적화를 할 수 있지만, 
    # 여기서는 단순 메모리 저장이므로 기본 설정을 유지합니다.

    first_pts = None
    first_dts = None

    try:
        for packet in packets:
            # 패킷 복제 (원본 패킷 보호)
            new_packet = av.Packet(packet)
            
            # 출력 스트림에 맞게 패킷 연결
            new_packet.stream = output_stream
            
            # 타임스탬프 리스케일링 (중요)
            # 스트림의 시작을 0으로 맞추기 위해 첫 패킷의 PTS/DTS를 오프셋으로 사용합니다.
            if first_pts is None:
                first_pts = new_packet.pts if new_packet.pts is not None else 0
                first_dts = new_packet.dts if new_packet.dts is not None else 0
            
            if new_packet.pts is not None:
                new_packet.pts -= first_pts
            if new_packet.dts is not None:
                new_packet.dts -= first_dts
            
            # 원본 타임베이스에서 출력 스트림의 타임베이스로 변환
            new_packet.rescale_ts(source_stream.time_base, output_stream.time_base)
            
            # 컨테이너에 패킷 쓰기
            output_container.mux(new_packet)

        # 컨테이너 닫기 (메모리에 데이터 플러시)
        output_container.close()
        
    except Exception as e:
        logger.error(f"Muxing 중 오류 발생: {e}", exc_info=True)
        return io.BytesIO()

    # 버퍼 포인터를 처음으로 되돌려 읽기 준비
    output_buffer.seek(0)
    return output_buffer
