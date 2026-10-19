# 박지민 - 공용 데이터 스키마: Frame, CameraSettings, StreamSettings, AppConfig
"""camera_stream/schema.py - 모듈 간에 주고받는 데이터의 형태(dataclass)를 정의한다.

camera.py와 streamer.py가 서로의 구현을 몰라도 되도록, 주고받는 데이터 계약을 한 곳에 모았다.
- Frame: camera.py가 만들어 streamer.py로 넘기는 프레임 한 장 + 메타데이터
- CameraSettings / StreamSettings / AppConfig: config.py가 읽어서 채우는 설정값 스키마
- HEADER_FORMAT / pack_header / unpack_header: 송출 메시지 앞에 붙는 헤더 규격
"""
import struct
import zlib
from dataclasses import dataclass, field

import numpy as np

# 송출 메시지 = 헤더 36바이트 + JPEG. 보내는 쪽(streamer.py)과 받는 쪽(수신 클라이언트)이
# 같은 규격을 따라야 하므로 여기 한 곳에만 정의한다. 파이썬 수신 쪽은 이걸 import하면
# 필드를 바꿀 때 함께 따라온다.
# 자바스크립트처럼 import가 안 되는 수신 쪽은 헤더 오프셋도 같이 고쳐야 한다.
# camera_timestamp(카메라 내부 tick)는 장비마다 기준이 달라 호스트 시각과 못 섞으므로 헤더엔 안 넣는다.
# CRC ①: JPEG 중간 바이트만 바뀐 손상은 디코딩 검사로 못 잡아서(44장 중 0장 감지)
# 헤더 끝에 CRC32 4바이트를 추가해 32→36바이트로 늘린다.
# 프레임 번호(Q,8) + 촬영 시각(d,8) + 송출 시각(d,8) + width(I,4) + height(I,4) + crc32(I,4)
HEADER_FORMAT = "<QddIII"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 36
_HEADER = struct.Struct(HEADER_FORMAT)


CRC_OFFSET = HEADER_SIZE - 4  # ! CRC 칸이 시작하는 위치(32)고 그 앞 32바이트가 CRC 계산에 들어감


def frame_crc32(head: bytes, jpeg: bytes) -> int:
    """헤더 앞 32바이트(CRC 칸 제외)와 JPEG를 이어서 계산한 CRC32. 서버와 받는 쪽이 같은 함수를 쓴다."""
    # !CRC를 JPEG에만 걸면 헤더(프레임 번호 등)가 바뀌어도 못 잡아서 헤더 앞 32바이트까지 넣는다.
    return zlib.crc32(jpeg, zlib.crc32(head)) & 0xFFFFFFFF


def pack_header(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    frame_no: int,
    timestamp: float,
    sent_at: float,
    width: int,
    height: int,
    crc32: int,
) -> bytes:
    """헤더 36바이트를 만든다. JPEG 앞에 붙여서 보낸다."""
    return _HEADER.pack(frame_no, timestamp, sent_at, width, height, crc32)


def unpack_header(message: bytes) -> tuple[int, float, float, int, int, int]:
    """받은 메시지 앞부분에서 (프레임 번호, 촬영 시각, 송출 시각, width, height, crc32)를 읽는다."""
    return _HEADER.unpack_from(message)


@dataclass
class Frame:
    """캡처된 프레임 한 장과 그에 대한 메타데이터."""

    frame_no: int
    timestamp: float  # 호스트(PC) 기준 촬영 시각. RetrieveResult 직후에 찍어 변환 지연이 섞이지 않게 한다
    camera_timestamp: int  # 카메라 내부 타임스탬프 tick(장비마다 기준 다름). 호스트 시각과 직접 비교 불가, 참고용
    width: int
    height: int
    image: np.ndarray  # BGR, uint8, shape (height, width, 3) - 해상도는 카메라가 보고하는 값


@dataclass
# 설정 항목 하나가 속성 하나라서 개수가 많은 것이 정상이다 (dataclass)
class CameraSettings:  # pylint: disable=too-many-instance-attributes
    """camera.py(CameraSource)가 사용하는 카메라 관련 설정."""

    target_fps: float = 60.0
    exposure_us: float | None = None  # ExposureTimeAbs/ExposureTime, 둘 다 단위는 마이크로초
    gain_db: float | None = None  # Gain (dB). 지원하는 모델이면 이쪽을 우선 사용
    # GainRaw (카메라 고유 정수 단위, dB 아님). 구형 GigE 모델은 Gain 노드가 없어 이 값만 먹는다
    gain_raw: int | None = None
    white_balance: str | None = None  # BalanceWhiteAuto: "Off" | "Once" | "Continuous"
    # GigE Vision GevSCPSPacketSize(바이트). grabbing 중엔 잠겨서 바꿀 수 없어 연결 시점에만 적용됨
    packet_size: int | None = None
    serial_number: str | None = None  # 지정하면 이 시리얼 번호의 카메라에 연결. None이면 맨 처음 잡히는 카메라 사용
    retry_sec: float = 2.0  # 재연결 재시도 간격
    grab_timeout_ms: int = 2000  # RetrieveResult 타임아웃 (끊김/타임아웃 감지 기준)

    def validate(self):
        """카메라 설정값이 허용 범위 안인지 검사한다. 벗어나면 ValueError."""
        if self.target_fps <= 0:
            raise ValueError(f"target_fps는 0보다 커야 합니다: {self.target_fps}")

        if self.exposure_us is not None and self.exposure_us <= 0:
            raise ValueError(f"exposure_us는 0보다 커야 합니다: {self.exposure_us}")

        if self.gain_db is not None and self.gain_db < 0:
            raise ValueError(f"gain_db는 0 이상이어야 합니다: {self.gain_db}")

        if self.gain_raw is not None and self.gain_raw < 0:
            raise ValueError(f"gain_raw는 0 이상이어야 합니다: {self.gain_raw}")

        if self.white_balance is not None and self.white_balance not in (
            "Off",
            "Once",
            "Continuous",
        ):
            raise ValueError(f"white_balance 값이 올바르지 않습니다: {self.white_balance}")

        if self.packet_size is not None and not 500 <= self.packet_size <= 16000:
            raise ValueError(f"packet_size 범위가 올바르지 않습니다(500~16000): {self.packet_size}")

        if self.serial_number is not None and not self.serial_number.strip():
            raise ValueError("serial_number는 빈 문자열일 수 없습니다")

        if self.retry_sec <= 0:
            raise ValueError(f"retry_sec는 0보다 커야 합니다: {self.retry_sec}")

        if self.grab_timeout_ms <= 0:
            raise ValueError(f"grab_timeout_ms는 0보다 커야 합니다: {self.grab_timeout_ms}")


@dataclass
# 설정 항목 하나가 속성 하나라서 개수가 많은 것이 정상이다 (dataclass)
class StreamSettings:  # pylint: disable=too-many-instance-attributes
    """streamer.py(StreamServer)가 사용하는 서버/화질/송출 관련 설정."""

    host: str = "0.0.0.0"
    port: int = 8765
    jpeg_quality: int = 80
    skip_frames: int = 2  # 송신 버퍼에 이 장수 이상 쌓인 클라이언트는 건너뜀 ("장수"이므로 int)
    resize_width: int | None = None  # 지정하면 송출 전 리사이즈. None이면 카메라 원본 해상도 그대로 송출
    resize_height: int | None = None
    output_fps: float | None = None  # 송출 fps 제한. None이면 새 프레임이 나오는 대로 즉시 송출

    def validate(self):
        """송출 설정값이 허용 범위 안인지 검사한다. 벗어나면 ValueError."""
        if not 1 <= self.port <= 65535:
            raise ValueError(f"port 범위가 올바르지 않습니다(1~65535): {self.port}")

        if not 1 <= self.jpeg_quality <= 100:
            raise ValueError(f"jpeg_quality 범위가 올바르지 않습니다(1~100): {self.jpeg_quality}")

        if self.skip_frames <= 0:
            raise ValueError(f"skip_frames는 0보다 커야 합니다: {self.skip_frames}")

        if self.resize_width is not None and self.resize_width <= 0:
            raise ValueError(f"resize_width는 0보다 커야 합니다: {self.resize_width}")

        if self.resize_height is not None and self.resize_height <= 0:
            raise ValueError(f"resize_height는 0보다 커야 합니다: {self.resize_height}")

        if self.output_fps is not None and self.output_fps <= 0:
            raise ValueError(f"output_fps는 0보다 커야 합니다: {self.output_fps}")


@dataclass
class AppConfig:
    """카메라 설정과 송출 설정을 하나로 묶은 전체 설정."""

    camera: CameraSettings = field(default_factory=CameraSettings)
    stream: StreamSettings = field(default_factory=StreamSettings)

    def validate(self):
        """카메라 설정과 송출 설정을 모두 검사한다."""
        self.camera.validate()
        self.stream.validate()
