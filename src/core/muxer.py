"""
패킷들을 MP4 컨테이너로 Muxing(Remuxing)하는 모듈
브라우저 재생 가능한 MP4를 메모리에서 생성합니다
"""
import io
import logging
import tempfile
import os
from typing import List
import av

logger = logging.getLogger("aegis-agent.muxer")


def mux_packets_to_mp4(packets: List[av.Packet], source_stream: av.video.stream.VideoStream) -> io.BytesIO:
    """
    패킷 리스트를 브라우저 재생 가능한 MP4로 변환합니다.

    브라우저 호환을 위해 moov 박스를 파일 앞쪽에 배치합니다 (faststart).
    임시 파일을 사용하여 ffmpeg의 movflags 옵션을 적용합니다.
    """
    if not packets:
        logger.warning("Muxing할 패킷이 없습니다.")
        return io.BytesIO()

    logger.info(f"Muxing 시작: {len(packets)}개 패킷")

    # 임시 파일 사용 (faststart 옵션 적용을 위해 필요)
    temp_fd, temp_path = tempfile.mkstemp(suffix='.mp4')
    os.close(temp_fd)

    try:
        # faststart: moov 박스를 파일 앞에 배치하여 브라우저 스트리밍 지원
        with av.open(temp_path, mode='w', format='mp4', options={'movflags': '+faststart'}) as output_container:
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
            muxed_count = 0

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
                muxed_count += 1

        # 임시 파일에서 메모리로 읽기
        output_buffer = io.BytesIO()
        with open(temp_path, 'rb') as f:
            output_buffer.write(f.read())
        output_buffer.seek(0)

        file_size = output_buffer.getbuffer().nbytes

        if file_size == 0:
            logger.warning("Muxing 결과가 0바이트입니다.")
            return io.BytesIO()

        logger.info(f"Muxing 완료: {file_size} bytes ({muxed_count}개 패킷, faststart 적용)")
        return output_buffer

    except Exception as e:
        logger.error(f"Muxing 중 오류 발생: {e}", exc_info=True)
        return io.BytesIO()

    finally:
        # 임시 파일 정리
        if os.path.exists(temp_path):
            os.unlink(temp_path)
