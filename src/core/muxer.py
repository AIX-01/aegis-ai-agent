"""
패킷들을 MP4 컨테이너로 Muxing(Remuxing)하는 모듈
메모리 상에서 Fast Start MP4를 생성합니다 (디스크 I/O 없음)
"""
import io
import logging
from typing import List
import av

logger = logging.getLogger("aegis-agent.muxer")


def mux_packets_to_mp4(packets: List[av.Packet], source_stream: av.video.stream.VideoStream) -> io.BytesIO:
    """
    패킷 리스트를 메모리 상에서 Fast Start MP4로 변환합니다.

    1단계: fMP4로 메모리에 muxing
    2단계: fMP4를 faststart MP4로 remuxing (메모리 → 메모리)

    디스크 I/O가 전혀 발생하지 않습니다.
    """
    if not packets:
        logger.warning("Muxing할 패킷이 없습니다.")
        return io.BytesIO()

    logger.info(f"Muxing 시작: {len(packets)}개 패킷")

    try:
        # 1단계: 패킷을 fMP4로 muxing (메모리)
        fmp4_buffer = _mux_to_fmp4(packets, source_stream)
        if fmp4_buffer.getbuffer().nbytes == 0:
            return io.BytesIO()

        # 2단계: fMP4를 faststart MP4로 remuxing (메모리 → 메모리)
        faststart_buffer = _convert_to_faststart(fmp4_buffer)

        file_size = faststart_buffer.getbuffer().nbytes
        logger.info(f"Muxing 완료: {file_size} bytes (faststart)")
        return faststart_buffer

    except Exception as e:
        logger.error(f"Muxing 중 오류 발생: {e}", exc_info=True)
        return io.BytesIO()


def _mux_to_fmp4(packets: List[av.Packet], source_stream: av.video.stream.VideoStream) -> io.BytesIO:
    """패킷들을 fMP4로 muxing (1단계)"""
    output_buffer = io.BytesIO()

    with av.open(output_buffer, mode='w', format='mp4',
                 options={'movflags': 'frag_keyframe+empty_moov'}) as output_container:

        codec_name = source_stream.codec_context.name
        output_stream = output_container.add_stream(codec_name, rate=source_stream.average_rate)

        output_stream.width = source_stream.width
        output_stream.height = source_stream.height
        output_stream.pix_fmt = source_stream.pix_fmt
        output_stream.time_base = source_stream.time_base
        if source_stream.codec_context.extradata:
            output_stream.codec_context.extradata = source_stream.codec_context.extradata

        first_pts = None
        first_dts = None

        for packet in packets:
            if packet.size == 0:
                continue

            packet_bytes = bytes(packet)
            new_packet = av.Packet(packet_bytes)
            new_packet.stream = output_stream
            new_packet.is_keyframe = packet.is_keyframe

            if first_pts is None:
                first_pts = packet.pts if packet.pts is not None else 0
                first_dts = packet.dts if packet.dts is not None else 0

            if packet.pts is not None:
                new_packet.pts = packet.pts - first_pts
            if packet.dts is not None:
                new_packet.dts = packet.dts - first_dts

            output_container.mux(new_packet)

    output_buffer.seek(0)
    return output_buffer


def _convert_to_faststart(input_buffer: io.BytesIO) -> io.BytesIO:
    """
    fMP4를 faststart MP4로 변환 (2단계)
    BytesIO는 seek 가능하므로 faststart 적용 가능
    """
    output_buffer = io.BytesIO()

    with av.open(input_buffer, mode='r') as input_container:
        with av.open(output_buffer, mode='w', format='mp4',
                     options={'movflags': 'faststart'}) as output_container:

            input_stream = input_container.streams.video[0]
            output_stream = output_container.add_stream(template=input_stream)

            for packet in input_container.demux(input_stream):
                if packet.dts is None:
                    continue
                packet.stream = output_stream
                output_container.mux(packet)

    output_buffer.seek(0)
    return output_buffer
