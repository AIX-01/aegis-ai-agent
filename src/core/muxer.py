"""
패킷들을 MP4 컨테이너로 Muxing(Remuxing)하는 모듈
브라우저 재생 가능한 MP4를 메모리에서 생성합니다 (디스크 I/O 없음)
"""
import io
import logging
import struct
from typing import List, Tuple
import av

logger = logging.getLogger("aegis-agent.muxer")


def _find_atom(data: bytes, atom_type: bytes, start: int = 0) -> Tuple[int, int]:
    """
    MP4 atom(box)을 찾아 (offset, size)를 반환합니다.
    찾지 못하면 (-1, 0)을 반환합니다.
    """
    offset = start
    while offset < len(data) - 8:
        size = struct.unpack('>I', data[offset:offset+4])[0]
        atype = data[offset+4:offset+8]

        if size < 8:
            break
        if size == 1:  # 64비트 확장 크기
            if offset + 16 > len(data):
                break
            size = struct.unpack('>Q', data[offset+8:offset+16])[0]

        if atype == atom_type:
            return offset, size

        offset += size

    return -1, 0


def _patch_stco(data: bytearray, offset_delta: int) -> None:
    """
    데이터 내의 모든 stco/co64 atom들의 청크 오프셋을 재귀적으로 수정합니다.
    moov 내부의 중첩된 컨테이너(trak, mdia, minf, stbl)를 탐색합니다.
    """
    containers = {b'moov', b'trak', b'mdia', b'minf', b'stbl', b'udta'}

    pos = 0
    while pos < len(data) - 8:
        size = struct.unpack('>I', data[pos:pos+4])[0]
        atype = bytes(data[pos+4:pos+8])

        if size < 8 or pos + size > len(data):
            break

        header_size = 8
        if size == 1 and pos + 16 <= len(data):
            size = struct.unpack('>Q', data[pos+8:pos+16])[0]
            header_size = 16

        if atype == b'stco':
            if pos + 16 <= len(data):
                entry_count = struct.unpack('>I', data[pos+12:pos+16])[0]
                for i in range(entry_count):
                    entry_pos = pos + 16 + i * 4
                    if entry_pos + 4 <= len(data):
                        old_val = struct.unpack('>I', data[entry_pos:entry_pos+4])[0]
                        new_val = old_val + offset_delta
                        data[entry_pos:entry_pos+4] = struct.pack('>I', new_val)

        elif atype == b'co64':
            if pos + 16 <= len(data):
                entry_count = struct.unpack('>I', data[pos+12:pos+16])[0]
                for i in range(entry_count):
                    entry_pos = pos + 16 + i * 8
                    if entry_pos + 8 <= len(data):
                        old_val = struct.unpack('>Q', data[entry_pos:entry_pos+8])[0]
                        new_val = old_val + offset_delta
                        data[entry_pos:entry_pos+8] = struct.pack('>Q', new_val)

        elif atype in containers:
            inner_start = pos + header_size
            inner_end = pos + size
            if inner_end <= len(data):
                inner_array = bytearray(data[inner_start:inner_end])
                _patch_stco(inner_array, offset_delta)
                data[inner_start:inner_end] = inner_array

        pos += size


def _remove_edts(moov_data: bytearray) -> bytearray:
    """
    moov 내부의 모든 edts atom을 제거합니다.
    edts(edit list)는 미디어 시작 오프셋을 지정하는데,
    브라우저마다 해석이 달라 재생 위치 문제를 유발합니다.
    """
    result = bytearray()
    # moov 헤더 복사 (size + 'moov')
    result.extend(moov_data[0:8])

    pos = 8  # moov 헤더 이후부터 시작

    while pos < len(moov_data) - 8:
        size = struct.unpack('>I', moov_data[pos:pos+4])[0]
        atype = bytes(moov_data[pos+4:pos+8])

        if size < 8 or pos + size > len(moov_data):
            result.extend(moov_data[pos:])
            break

        if atype == b'trak':
            # trak 내부에서 edts 제거
            trak_data = _remove_edts_from_trak(moov_data[pos:pos+size])
            result.extend(trak_data)
        elif atype != b'edts':
            # edts가 아니면 그대로 복사
            result.extend(moov_data[pos:pos+size])
        # edts는 스킵 (복사하지 않음)

        pos += size

    # moov 크기 업데이트
    if len(result) >= 4:
        new_size = len(result)
        result[0:4] = struct.pack('>I', new_size)

    return result


def _remove_edts_from_trak(trak_data: bytes) -> bytearray:
    """
    trak atom 내부에서 edts를 제거합니다.
    """
    result = bytearray()
    result.extend(trak_data[0:8])  # trak 헤더 (size + 'trak')

    pos = 8
    while pos < len(trak_data) - 8:
        size = struct.unpack('>I', trak_data[pos:pos+4])[0]
        atype = trak_data[pos+4:pos+8]

        if size < 8 or pos + size > len(trak_data):
            result.extend(trak_data[pos:])
            break

        if atype != b'edts':
            result.extend(trak_data[pos:pos+size])
        # edts는 스킵

        pos += size

    # trak 크기 업데이트
    if len(result) >= 4:
        result[0:4] = struct.pack('>I', len(result))

    return result



def _faststart(data: bytes) -> bytes:
    """
    moov atom을 mdat 앞으로 이동시킵니다 (faststart).
    브라우저 스트리밍 재생에 필수입니다.
    입력 데이터는 ftyp로 시작해야 합니다.
    """
    # atom 위치 찾기
    ftyp_offset, ftyp_size = _find_atom(data, b'ftyp')
    if ftyp_offset != 0:
        logger.warning(f"ftyp가 파일 시작이 아님: {ftyp_offset}")
        return data

    moov_offset, moov_size = _find_atom(data, b'moov')
    if moov_offset == -1:
        logger.warning("moov atom을 찾을 수 없습니다.")
        return data

    mdat_offset, mdat_size = _find_atom(data, b'mdat')
    if mdat_offset == -1:
        logger.warning("mdat atom을 찾을 수 없습니다.")
        return data

    # moov가 이미 mdat 앞에 있어도 edts 제거는 필요
    if moov_offset < mdat_offset:
        logger.debug("moov가 이미 mdat 앞에 있습니다. edts만 제거합니다.")
        # moov에서 edts 제거
        moov_data = bytearray(data[moov_offset:moov_offset + moov_size])
        cleaned_moov = _remove_edts(moov_data)

        if len(cleaned_moov) != moov_size:
            # edts가 제거되어 크기가 변경됨 - stco 오프셋 조정 필요
            size_diff = moov_size - len(cleaned_moov)
            _patch_stco(cleaned_moov, -size_diff)

            # 파일 재조립
            result = io.BytesIO()
            result.write(data[:moov_offset])
            result.write(bytes(cleaned_moov))
            result.write(data[moov_offset + moov_size:])
            return result.getvalue()
        return data

    logger.debug(f"faststart 적용: ftyp@{ftyp_offset}, mdat@{mdat_offset}, moov@{moov_offset}")

    # moov 추출 및 복사
    moov_data = bytearray(data[moov_offset:moov_offset + moov_size])

    # edts atom 제거 (edit list가 브라우저 호환성 문제 유발)
    moov_data = _remove_edts(moov_data)
    moov_size = len(moov_data)

    # 새 구조: ftyp + moov + (ftyp~moov 사이 데이터) + (moov 이후 데이터)
    ftyp_end = ftyp_offset + ftyp_size

    # 새 mdat 위치 = ftyp_size + moov_size + (ftyp_end ~ mdat_offset 사이 박스들 크기)
    # 간단히: mdat의 상대적 이동량 = moov_size (moov가 ftyp 뒤로 삽입되므로)
    # 하지만 원래 mdat 앞에 free 등이 있을 수 있으므로 정확히 계산

    # 원래: ftyp + free? + mdat + ... + moov
    # 새로: ftyp + moov + free? + mdat + ...
    # mdat의 새 오프셋 = ftyp_size + moov_size + (원래 ftyp_end ~ mdat_offset 사이 크기)
    between_size = mdat_offset - ftyp_end  # ftyp와 mdat 사이 (free 등)
    new_mdat_offset = ftyp_size + moov_size + between_size
    offset_delta = new_mdat_offset - mdat_offset

    # stco/co64 오프셋 패치
    _patch_stco(moov_data, offset_delta)

    # 새 파일 조립
    result = io.BytesIO()

    # 1. ftyp 복사
    result.write(data[ftyp_offset:ftyp_end])

    # 2. 패치된 moov 복사
    result.write(bytes(moov_data))

    # 3. ftyp 이후 ~ moov 이전의 모든 데이터 (free, mdat 등)
    result.write(data[ftyp_end:moov_offset])

    # 4. moov 이후의 데이터 (있다면)
    if moov_offset + moov_size < len(data):
        result.write(data[moov_offset + moov_size:])

    return result.getvalue()


def mux_packets_to_mp4(packets: List[av.Packet], source_stream: av.video.stream.VideoStream) -> io.BytesIO:
    """
    패킷 리스트를 브라우저 재생 가능한 MP4로 변환합니다.

    디스크 I/O 없이 메모리에서 처리:
    1. PyAV로 일반 MP4 muxing
    2. moov atom을 파일 앞으로 이동 (faststart)
    """
    if not packets:
        logger.warning("Muxing할 패킷이 없습니다.")
        return io.BytesIO()

    logger.info(f"Muxing 시작: {len(packets)}개 패킷")
    output_buffer = io.BytesIO()

    try:
        # 1단계: 일반 MP4로 muxing
        with av.open(output_buffer, mode='w', format='mp4') as output_container:
            codec_name = source_stream.codec_context.name
            output_stream = output_container.add_stream(codec_name, rate=source_stream.average_rate)

            output_stream.width = source_stream.width
            output_stream.height = source_stream.height
            output_stream.pix_fmt = source_stream.pix_fmt
            output_stream.time_base = source_stream.time_base

            # H.264 SPS/PPS 정보 복사 (브라우저 재생에 필수)
            if source_stream.codec_context.extradata:
                output_stream.codec_context.extradata = source_stream.codec_context.extradata

            first_pts = None
            first_dts = None
            last_dts = -1  # DTS 단조 증가 보장용
            muxed_count = 0

            for packet in packets:
                if packet.size == 0:
                    continue

                # 패킷 복사
                packet_bytes = bytes(packet)
                new_packet = av.Packet(packet_bytes)
                new_packet.stream = output_stream
                new_packet.is_keyframe = packet.is_keyframe
                new_packet.time_base = output_stream.time_base  # time_base 명시적 설정

                # PTS/DTS 정규화 (0부터 시작)
                if first_pts is None:
                    first_pts = packet.pts if packet.pts is not None else 0
                    first_dts = packet.dts if packet.dts is not None else 0

                if packet.pts is not None:
                    new_packet.pts = packet.pts - first_pts
                else:
                    new_packet.pts = muxed_count * 3000  # 기본값 (30fps 기준)

                if packet.dts is not None:
                    new_dts = packet.dts - first_dts
                else:
                    new_dts = muxed_count * 3000

                # DTS는 반드시 단조 증가해야 함
                if new_dts <= last_dts:
                    new_dts = last_dts + 1
                new_packet.dts = new_dts
                last_dts = new_dts

                output_container.mux(new_packet)
                muxed_count += 1

        # 2단계: ftyp 앞 쓰레기 제거 및 faststart 적용
        raw_data = output_buffer.getvalue()

        if len(raw_data) == 0:
            logger.warning("PyAV muxing 결과가 0바이트입니다.")
            return io.BytesIO()

        # ftyp 앞의 쓰레기 데이터 제거 (PyAV BytesIO 버그 대응)
        ftyp_pos = raw_data.find(b'ftyp')
        if ftyp_pos > 4:
            raw_data = raw_data[ftyp_pos - 4:]
            logger.debug(f"ftyp 앞 {ftyp_pos - 4}바이트 쓰레기 제거")
        elif ftyp_pos == -1:
            logger.error("ftyp를 찾을 수 없습니다.")
            return io.BytesIO()

        # faststart 적용 (moov를 앞으로)
        faststart_data = _faststart(raw_data)

        result_buffer = io.BytesIO(faststart_data)
        logger.info(f"Muxing 완료: {len(faststart_data)} bytes ({muxed_count}개 패킷)")
        return result_buffer

    except Exception as e:
        logger.error(f"Muxing 중 오류 발생: {e}", exc_info=True)
        return io.BytesIO()
