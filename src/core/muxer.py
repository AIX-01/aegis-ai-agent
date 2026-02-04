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
    재인코딩 없이 패킷 리스트를 MP4 컨테이너로 Muxing(Remuxing)합니다.

    [장점: 초고속 및 저부하]
    - 비디오 데이터를 다시 압축하지 않고 '포장지(Container)'만 MP4로 바꿉니다.
    - CPU 사용량이 거의 없으며 원본 화질의 손실이 0%입니다.

    [핵심 로직: PTS/DTS Rescaling]
    - 스트림 중간에서 잘라낸 패킷들은 시작 타임스탬프가 0이 아닙니다.
    - 이를 그대로 저장하면 플레이어에서 영상이 멈춰있거나 비정상적으로 재생될 수 있습니다.
    - 첫 패킷의 시간을 0으로 맞추고(Offset 제거), 출력 스트림의 Timebase에 맞춰 
      모든 패킷의 시간 정보를 재계산(Rescale)하여 정상적인 재생을 보장합니다.
    """
    if not packets:
        logger.warning("Muxing할 패킷이 없습니다.")
        return io.BytesIO()

    # 메모리 내 출력 버퍼 생성 (디스크 I/O 없이 메모리에서만 작업하여 성능 극대화)
    output_buffer = io.BytesIO()
    
    # 출력 컨테이너 열기 (mp4 포맷)
    output_container = av.open(output_buffer, mode='w', format='mp4')

    # 출력 스트림 생성: 원본 스트림의 코덱 설정(H.264 등)을 그대로 복제합니다.
    output_stream = output_container.add_stream(template=source_stream)
    
    first_pts = None
    first_dts = None

    try:
        for packet in packets:
            # 패킷 복제 (원본 스트림의 패킷 상태를 유지하기 위해 복사본 생성)
            new_packet = av.Packet(packet)
            new_packet.stream = output_stream
            
            # [시작 시간 보정]
            # 잘라낸 시점의 첫 패킷 시간을 0으로 설정하여 클립의 시작점을 맞춥니다.
            if first_pts is None:
                first_pts = new_packet.pts if new_packet.pts is not None else 0
                first_dts = new_packet.dts if new_packet.dts is not None else 0
            
            if new_packet.pts is not None:
                new_packet.pts -= first_pts
            if new_packet.dts is not None:
                new_packet.dts -= first_dts
            
            # [타임베이스 변환]
            # 원본 스트림(예: RTSP)과 출력 MP4의 시간 단위(Timebase)가 다를 수 있으므로
            # 비디오 규격에 맞게 시간 정보를 변환합니다.
            new_packet.rescale_ts(source_stream.time_base, output_stream.time_base)
            
            output_container.mux(new_packet)

        # 컨테이너를 닫으며 MP4 헤더 등 메타데이터를 메모리에 최종 기록합니다.
        output_container.close()
        
    except Exception as e:
        logger.error(f"Muxing 중 오류 발생: {e}", exc_info=True)
        return io.BytesIO()

    # 버퍼 포인터를 처음으로 되돌려, 이후 S3 업로드 시 처음부터 읽을 수 있도록 준비합니다.
    output_buffer.seek(0)
    return output_buffer
