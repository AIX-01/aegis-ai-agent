"""
패킷들을 MP4 컨테이너로 Muxing(Remuxing)하는 모듈
"""
import io
import logging
from typing import List
import av

logger = logging.getLogger("aegis-agent.muxer")


def _faststart_in_memory(data: bytes) -> bytes:
    """
    메모리 내에서 moov atom을 파일 앞으로 이동하여 스트리밍 재생을 지원합니다.

    일반 MP4는 moov atom이 파일 끝에 위치하여 전체 다운로드 후에만 재생 가능합니다.
    이 함수는 moov를 ftyp 다음으로 이동하여 progressive download를 가능하게 합니다.
    """
    if len(data) < 8:
        return data

    # 모든 top-level atom 파싱
    atoms = []
    pos = 0
    while pos < len(data):
        if pos + 8 > len(data):
            break

        size = int.from_bytes(data[pos:pos+4], 'big')
        atom_type = data[pos+4:pos+8]

        if size == 0:  # atom이 파일 끝까지
            size = len(data) - pos
        elif size == 1:  # 64비트 확장 크기
            if pos + 16 > len(data):
                break
            size = int.from_bytes(data[pos+8:pos+16], 'big')

        if size < 8 or pos + size > len(data):
            break

        atoms.append((atom_type, data[pos:pos+size]))
        pos += size

    # moov 위치 확인
    moov_idx = None
    ftyp_idx = None
    for i, (atom_type, _) in enumerate(atoms):
        if atom_type == b'moov':
            moov_idx = i
        elif atom_type == b'ftyp':
            ftyp_idx = i

    # moov가 없거나 이미 앞에 있으면 그대로 반환
    if moov_idx is None:
        logger.warning("moov atom을 찾을 수 없습니다.")
        return data

    if ftyp_idx is not None and moov_idx == ftyp_idx + 1:
        logger.debug("moov가 이미 ftyp 다음에 위치합니다.")
        return data

    # 재조합: ftyp + moov + 나머지
    result = io.BytesIO()

    # ftyp 먼저
    for atom_type, atom_data in atoms:
        if atom_type == b'ftyp':
            result.write(atom_data)
            break

    # moov 다음
    for atom_type, atom_data in atoms:
        if atom_type == b'moov':
            result.write(atom_data)
            break

    # 나머지 (ftyp, moov 제외)
    for atom_type, atom_data in atoms:
        if atom_type not in (b'ftyp', b'moov'):
            result.write(atom_data)

    logger.debug(f"moov 재배치 완료: {len(data)} → {result.tell()} bytes")
    return result.getvalue()


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

    logger.info(f"Muxing 시작: {len(packets)}개 패킷")

    # 메모리 내 출력 버퍼 생성
    output_buffer = io.BytesIO()
    output_container = None

    try:
        # 일반 MP4로 생성 (moov가 파일 끝에 위치, 후처리로 앞으로 이동)
        output_container = av.open(
            output_buffer,
            mode='w',
            format='mp4'
        )

        # 출력 스트림 생성: 원본 스트림의 코덱 설정을 복제
        codec_name = source_stream.codec_context.name
        output_stream = output_container.add_stream(codec_name, rate=source_stream.average_rate)

        # 원본 스트림의 코덱 파라미터 복사
        output_stream.width = source_stream.width
        output_stream.height = source_stream.height
        output_stream.pix_fmt = source_stream.pix_fmt
        output_stream.time_base = source_stream.time_base  # time_base 명시적 설정
        if source_stream.codec_context.extradata:
            output_stream.codec_context.extradata = source_stream.codec_context.extradata

        first_pts = None
        first_dts = None
        muxed_count = 0

        for packet in packets:
            # 패킷 데이터가 유효한지 확인
            if packet.size == 0:
                continue

            # 패킷 복제: bytes로 변환 후 새 패킷 생성 (데이터 보존 보장)
            packet_bytes = bytes(packet)
            new_packet = av.Packet(packet_bytes)
            new_packet.stream = output_stream
            new_packet.is_keyframe = packet.is_keyframe

            # 시작 시간 보정 (타임베이스가 동일하므로 변환 불필요)
            if first_pts is None:
                first_pts = packet.pts if packet.pts is not None else 0
                first_dts = packet.dts if packet.dts is not None else 0

            # PTS/DTS 보정 (시작점을 0으로 맞춤)
            if packet.pts is not None:
                new_packet.pts = packet.pts - first_pts
            if packet.dts is not None:
                new_packet.dts = packet.dts - first_dts

            output_container.mux(new_packet)
            muxed_count += 1

        logger.debug(f"Muxed 패킷 수: {muxed_count}/{len(packets)}")

    except Exception as e:
        logger.error(f"Muxing 중 오류 발생: {e}", exc_info=True)
        if output_container:
            try:
                output_container.close()
            except:
                pass
        return io.BytesIO()

    finally:
        # 컨테이너 종료 (MP4 메타데이터 기록)
        if output_container:
            try:
                output_container.close()
            except Exception as e:
                logger.warning(f"컨테이너 close 중 경고: {e}")

    # 버퍼 포인터를 처음으로 되돌림
    output_buffer.seek(0)

    # 파일 크기 검증
    file_size = output_buffer.getbuffer().nbytes
    if file_size == 0:
        logger.warning("Muxing 결과가 0바이트입니다.")
        return io.BytesIO()

    # moov atom을 앞으로 이동 (스트리밍 재생 지원)
    original_data = output_buffer.getvalue()
    faststart_data = _faststart_in_memory(original_data)

    result = io.BytesIO(faststart_data)
    logger.info(f"Muxing 완료: {len(faststart_data)} bytes (faststart)")
    return result
