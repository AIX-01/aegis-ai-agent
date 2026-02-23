"""
패킷들을 브라우저 재생 가능한 MP4로 Muxing하는 모듈
디스크 I/O 없이 메모리에서 처리합니다.
"""
import io
import logging
import struct
from typing import List, Tuple, Union, Dict, Any
import av
logger = logging.getLogger("aegis-agent.muxer")
def _find_atom(data: bytes, atom_type: bytes) -> Tuple[int, int]:
    """MP4 atom을 찾아 (offset, size)를 반환합니다."""
    offset = 0
    while offset < len(data) - 8:
        size = struct.unpack('>I', data[offset:offset+4])[0]
        atype = data[offset+4:offset+8]
        if size < 8:
            break
        if size == 1 and offset + 16 <= len(data):
            size = struct.unpack('>Q', data[offset+8:offset+16])[0]
        if atype == atom_type:
            return offset, size
        offset += size
    return -1, 0
def _patch_stco(data: bytearray, delta: int) -> None:
    """moov 내 stco/co64 오프셋을 재귀적으로 패치합니다."""
    containers = {b'moov', b'trak', b'mdia', b'minf', b'stbl', b'udta'}
    pos = 0
    while pos < len(data) - 8:
        size = struct.unpack('>I', data[pos:pos+4])[0]
        atype = bytes(data[pos+4:pos+8])
        if size < 8 or pos + size > len(data):
            break
        header = 8
        if size == 1 and pos + 16 <= len(data):
            size = struct.unpack('>Q', data[pos+8:pos+16])[0]
            header = 16
        if atype == b'stco' and pos + 16 <= len(data):
            cnt = struct.unpack('>I', data[pos+12:pos+16])[0]
            for i in range(cnt):
                p = pos + 16 + i * 4
                if p + 4 <= len(data):
                    v = struct.unpack('>I', data[p:p+4])[0]
                    data[p:p+4] = struct.pack('>I', v + delta)
        elif atype == b'co64' and pos + 16 <= len(data):
            cnt = struct.unpack('>I', data[pos+12:pos+16])[0]
            for i in range(cnt):
                p = pos + 16 + i * 8
                if p + 8 <= len(data):
                    v = struct.unpack('>Q', data[p:p+8])[0]
                    data[p:p+8] = struct.pack('>Q', v + delta)
        elif atype in containers:
            inner = bytearray(data[pos+header:pos+size])
            _patch_stco(inner, delta)
            data[pos+header:pos+size] = inner
        pos += size
def _remove_edts_from_trak(trak: bytes) -> bytearray:
    """trak 내부에서 edts를 제거합니다."""
    result = bytearray(trak[0:8])
    pos = 8
    while pos < len(trak) - 8:
        size = struct.unpack('>I', trak[pos:pos+4])[0]
        if size < 8 or pos + size > len(trak):
            result.extend(trak[pos:])
            break
        if trak[pos+4:pos+8] != b'edts':
            result.extend(trak[pos:pos+size])
        pos += size
    result[0:4] = struct.pack('>I', len(result))
    return result
def _remove_edts(moov: bytearray) -> bytearray:
    """moov 내부의 edts를 제거합니다."""
    result = bytearray(moov[0:8])
    pos = 8
    while pos < len(moov) - 8:
        size = struct.unpack('>I', moov[pos:pos+4])[0]
        atype = bytes(moov[pos+4:pos+8])
        if size < 8 or pos + size > len(moov):
            result.extend(moov[pos:])
            break
        if atype == b'trak':
            result.extend(_remove_edts_from_trak(moov[pos:pos+size]))
        elif atype != b'edts':
            result.extend(moov[pos:pos+size])
        pos += size
    result[0:4] = struct.pack('>I', len(result))
    return result
def _patch_resolution(data: bytearray, width: int, height: int) -> bytearray:
    """avc1과 tkhd의 해상도를 패치합니다."""
    # avc1 패치
    avc1_idx = data.find(b'avc1')
    if avc1_idx > 0:
        base = avc1_idx - 4
        data[base+32:base+34] = struct.pack('>H', width)
        data[base+34:base+36] = struct.pack('>H', height)
    # tkhd 패치 (fixed-point 16.16)
    # tkhd 구조: type(4) + ver+flags(4) + creation(4) + modification(4)
    #   + track_id(4) + reserved(4) + duration(4) + reserved(8)
    #   + layer(2) + alt_group(2) + volume(2) + reserved(2)
    #   + matrix(36) + width(4) + height(4)
    # → width: tkhd_idx+80, height: tkhd_idx+84 (version 0 기준)
    tkhd_idx = data.find(b'tkhd')
    if tkhd_idx > 0:
        data[tkhd_idx+80:tkhd_idx+84] = struct.pack('>I', width << 16)
        data[tkhd_idx+84:tkhd_idx+88] = struct.pack('>I', height << 16)
    return data
def _faststart(data: bytes, width: int = 0, height: int = 0) -> bytes:
    """moov를 mdat 앞으로 이동하고 브라우저 호환성 처리를 적용합니다."""
    ftyp_off, ftyp_size = _find_atom(data, b'ftyp')
    moov_off, moov_size = _find_atom(data, b'moov')
    mdat_off, _ = _find_atom(data, b'mdat')
    if ftyp_off != 0 or moov_off == -1 or mdat_off == -1:
        return data
    # moov가 이미 앞에 있으면 edts 제거만
    if moov_off < mdat_off:
        moov_data = bytearray(data[moov_off:moov_off+moov_size])
        cleaned = _remove_edts(moov_data)
        if len(cleaned) != moov_size:
            _patch_stco(cleaned, -(moov_size - len(cleaned)))
            result = bytearray(data[:moov_off]) + cleaned + bytearray(data[moov_off+moov_size:])
        else:
            result = bytearray(data)
        if width > 0 and height > 0:
            result = _patch_resolution(result, width, height)
        return bytes(result)
    # moov를 앞으로 이동
    moov_data = bytearray(data[moov_off:moov_off+moov_size])
    moov_data = _remove_edts(moov_data)
    new_moov_size = len(moov_data)
    ftyp_end = ftyp_off + ftyp_size
    between = mdat_off - ftyp_end
    new_mdat_off = ftyp_size + new_moov_size + between
    _patch_stco(moov_data, new_mdat_off - mdat_off)
    result = bytearray()
    result.extend(data[ftyp_off:ftyp_end])
    result.extend(moov_data)
    result.extend(data[ftyp_end:moov_off])
    if moov_off + moov_size < len(data):
        result.extend(data[moov_off+moov_size:])
    if width > 0 and height > 0:
        result = _patch_resolution(result, width, height)
    return bytes(result)
def mux_packets_to_mp4(
    packets: List[av.Packet],
    source_stream: Union[Dict[str, Any], Any]
) -> io.BytesIO:
    """
    패킷 리스트를 브라우저 재생 가능한 MP4로 변환합니다.
    Args:
        packets: av.Packet 리스트
        source_stream: 스트림 메타데이터 딕셔너리 또는 VideoStream 객체
    Returns:
        MP4 데이터가 담긴 BytesIO 객체
    """
    if not packets:
        logger.warning("Muxing할 패킷이 없습니다.")
        return io.BytesIO()
    # 메타데이터 추출
    if isinstance(source_stream, dict):
        codec_name = source_stream['codec_name']
        width = source_stream['width']
        height = source_stream['height']
        pix_fmt = source_stream['pix_fmt']
        time_base = source_stream['time_base']
        avg_rate = source_stream['average_rate']
        extradata = source_stream.get('extradata')
    else:
        codec_name = source_stream.codec_context.name
        width = source_stream.width
        height = source_stream.height
        pix_fmt = source_stream.pix_fmt
        time_base = source_stream.time_base
        avg_rate = source_stream.average_rate
        extradata = source_stream.codec_context.extradata
    logger.info(f"Muxing 시작: {len(packets)}개 패킷, {width}x{height}")
    buf = io.BytesIO()
    try:
        with av.open(buf, mode='w', format='mp4') as container:
            stream = container.add_stream(codec_name, rate=avg_rate)
            stream.width = width
            stream.height = height
            stream.pix_fmt = pix_fmt
            stream.time_base = time_base
            stream.codec_context.width = width
            stream.codec_context.height = height
            if extradata:
                stream.codec_context.extradata = extradata
            first_dts = None
            last_dts = -1
            count = 0
            for pkt in packets:
                if pkt.size == 0:
                    continue
                new_pkt = av.Packet(bytes(pkt))
                new_pkt.stream = stream
                new_pkt.is_keyframe = pkt.is_keyframe
                new_pkt.time_base = stream.time_base
                # DTS 정규화 (0부터 시작, 단조 증가 보장)
                if first_dts is None:
                    first_dts = pkt.dts if pkt.dts is not None else 0
                dts = (pkt.dts - first_dts) if pkt.dts is not None else count * 3000
                if dts <= last_dts:
                    dts = last_dts + 1
                new_pkt.dts = dts
                new_pkt.pts = (pkt.pts - first_dts) if pkt.pts is not None else dts
                last_dts = dts
                container.mux(new_pkt)
                count += 1
        raw = buf.getvalue()
        if not raw:
            logger.warning("Muxing 결과가 비어있습니다.")
            return io.BytesIO()
        # ftyp 앞 쓰레기 제거
        ftyp_pos = raw.find(b'ftyp')
        if ftyp_pos > 4:
            raw = raw[ftyp_pos-4:]
        elif ftyp_pos == -1:
            logger.error("ftyp를 찾을 수 없습니다.")
            return io.BytesIO()
        # faststart 및 해상도 패치 적용
        result = _faststart(raw, width, height)
        logger.info(f"Muxing 완료: {len(result)} bytes ({count}개 패킷)")
        return io.BytesIO(result)
    except Exception as e:
        logger.error(f"Muxing 오류: {e}", exc_info=True)
        return io.BytesIO()
