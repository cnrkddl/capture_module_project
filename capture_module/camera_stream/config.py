# 박지민 - 해상도, fps, 포트, 화질, packet size 등 설정
"""camera_stream/config.py - 설정값을 읽어서 AppConfig 하나로 만들어 준다.

설정값이 오는 곳은 세 군데이고, 아래 순서로 덮어쓴다 (뒤에 있을수록 우선).

    1단계. 코드 안 기본값    schema.py의 CameraSettings, StreamSettings에 적혀 있는 값
    2단계. 설정 파일         config.json (있으면 1단계 값을 덮어쓴다)
    3단계. 환경변수          CAMERA_로 시작하는 환경변수 (있으면 2단계 값까지 덮어쓴다)

즉 "환경변수 > config.json > 코드 기본값" 순서로 이긴다.
config.json이 없어도 기본값만으로 동작한다.

현장에서 값을 바꿀 때는 config.json만 고치면 된다. (코드를 열 필요 없음)
설정값마다 뜻은 schema.py의 CameraSettings, StreamSettings 설명을 보면 된다.

환경변수 이름 규칙:  CAMERA_<구역>_<설정이름>   (모두 대문자)
    예) CAMERA_CAMERA_TARGET_FPS=30    카메라 구역(camera)의 target_fps
    예) CAMERA_STREAM_PORT=9000        송출 구역(stream)의 port
    예) CAMERA_CONFIG=D:\\site\\config.json   설정 파일 위치를 바꾸고 싶을 때

참고: 해상도는 여기서 설정하지 않는다. camera.py가 카메라에서 직접 읽은 값을 쓴다.
"""
import json
import logging
import os
from pathlib import Path
from typing import Any

from .schema import AppConfig, CameraSettings, StreamSettings

log = logging.getLogger("camera_stream.config")

# 설정 파일 이름. 프로그램을 실행한 폴더에서 찾는다 (python run_camera_module.py를 실행한 폴더).
DEFAULT_CONFIG_PATH: str = "config.json"

# 환경변수 이름의 앞부분
ENV_PREFIX: str = "CAMERA_"

# 환경변수는 항상 글자(문자열)로 들어오므로, 설정마다 어떤 타입으로 바꿀지 적어 둔다.
# float = 소수, int = 정수, str = 글자 그대로
# dict[str, type] = "설정 이름(str)"을 키로, "바꿀 타입(float/int/str)"을 값으로 가진 표
CAMERA_FIELD_TYPES: dict[str, type] = {
    "target_fps": float,
    "exposure_us": float,
    "gain_db": float,
    "gain_raw": int,
    "white_balance": str,
    "packet_size": int,
    "serial_number": str,
    "retry_sec": float,
    "grab_timeout_ms": int,
}
STREAM_FIELD_TYPES: dict[str, type] = {
    "host": str,
    "port": int,
    "jpeg_quality": int,
    "skip_frames": int,
    "resize_width": int,
    "resize_height": int,
    "output_fps": float,
}


def read_json_file(path: str | Path) -> dict[str, Any]:
    """2단계: 설정 파일(JSON)을 읽어서 딕셔너리로 돌려준다. 파일이 없으면 빈 딕셔너리.

    path: 설정 파일 위치 (글자 또는 Path)
    반환: {"camera": {...}, "stream": {...}} 모양의 딕셔너리
    """
    # 글자(str)로 온 경로를 Path 객체로 바꿔야 .exists(), .open()을 쓸 수 있다
    file_path: Path = Path(path)

    # 파일이 없으면 오류가 아니다. 기본값과 환경변수만으로 동작한다.
    if not file_path.exists():
        log.info("설정 파일 없음(%s) - 기본값 + 환경변수만 사용", file_path)
        return {}

    log.info("설정 파일 사용: %s", file_path)

    with file_path.open("r", encoding="utf-8") as file:
        try:
            return json.load(file)

        except json.JSONDecodeError as error:
            # JSON 문법이 틀린 경우 (쉼표 빠짐, 따옴표 오류 등)
            raise ValueError(f"설정 파일을 읽을 수 없습니다 ({file_path}): {error}") from error


def convert_env_value(raw_text: str, value_type: type) -> float | int | str | None:
    """환경변수 글자를 설정 타입(float, int, str)으로 바꾼다.

    빈 글자("")나 "none"은 "값 없음(None)"으로 본다. 예) CAMERA_CAMERA_GAIN_DB=none

    raw_text  : 환경변수에서 읽은 글자 (예: "30")
    value_type: 바꿀 타입 (float, int, str 중 하나)
    반환      : 바뀐 값. "값 없음"이면 None
    """
    # 대소문자 상관없이 "none", "None", "NONE"을 같게 보기 위해 소문자로 바꿔 비교한다
    lowered_text: str = raw_text.lower()

    # 빈 글자이거나 "none"이면 "값 없음"으로 처리한다
    if raw_text == "":
        return None

    if lowered_text == "none":
        return None

    # 설정 타입에 맞게 글자를 숫자로 바꾼다
    if value_type is float:
        return float(raw_text)

    if value_type is int:
        return int(raw_text)

    # str 타입이면 글자 그대로 돌려준다
    return raw_text


def read_env_overrides(
    section_name: str, field_types: dict[str, type]
) -> dict[str, float | int | str | None]:
    """3단계: 환경변수에서 이 구역의 설정값을 읽어서 딕셔너리로 돌려준다.

    section_name: "camera" 또는 "stream"
    field_types : 그 구역의 설정 이름과 타입 표 (예: {"port": int})
    반환        : 환경변수로 덮어쓸 값만 담은 딕셔너리 (예: {"port": 9000})
    """
    overrides: dict[str, float | int | str | None] = {}

    for field_name, value_type in field_types.items():
        # 환경변수 이름을 "앞부분 + 구역 + 설정이름" 순서로 조립한다 (모두 대문자)
        # 예) camera 구역의 target_fps -> CAMERA_ + CAMERA + _ + TARGET_FPS
        section_upper: str = section_name.upper()
        field_upper: str = field_name.upper()
        env_name: str = f"{ENV_PREFIX}{section_upper}_{field_upper}"

        # 그 이름의 환경변수가 있는지 찾는다. 없으면 None이 돌아온다
        raw_text: str | None = os.environ.get(env_name)

        # 환경변수가 설정돼 있을 때만 타입을 바꿔서 담는다
        if raw_text is not None:
            converted_value = convert_env_value(raw_text, value_type)
            overrides[field_name] = converted_value

    return overrides


def pick_known_fields(
    values: dict[str, Any], field_types: dict[str, type]
) -> dict[str, Any]:
    """딕셔너리에서 우리가 아는 설정 이름만 남긴다. 모르는 이름은 경고만 하고 버린다.

    values     : 설정 이름과 값이 섞여 있는 딕셔너리 (예: {"port": 9000, "typo": 1})
    field_types: 아는 설정 이름 표 (이 안에 이름이 있으면 "아는 이름")
    반환       : 아는 이름만 남긴 딕셔너리 (예: {"port": 9000})
    """
    known_values: dict[str, Any] = {}
    unknown_names: list[str] = []

    # 설정 이름을 하나씩 보면서, 아는 이름이면 담고 모르는 이름이면 따로 모아 둔다
    for name, value in values.items():
        if name in field_types:
            known_values[name] = value
        else:
            unknown_names.append(name)

    # 모르는 이름이 하나라도 있으면 경고를 남긴다 (이름순으로 정렬해서 보기 쉽게)
    if unknown_names:
        log.warning("알 수 없는 설정 항목 무시: %s", sorted(unknown_names))

    return known_values


def load_config(path: str | Path | None = None) -> AppConfig:
    """설정을 읽어 AppConfig를 만든다.

    path: 설정 파일 위치. 없으면(None) 환경변수 CAMERA_CONFIG, 그것도 없으면 config.json.
    반환: 카메라 설정과 송출 설정이 담긴 AppConfig (검사까지 마친 상태)
    """
    # 설정 파일 위치 정하기: 인자 > 환경변수 CAMERA_CONFIG > 기본 이름(config.json)
    config_path: str | Path

    if path:
        # 1순위: 함수를 부를 때 직접 알려준 위치
        config_path = path
    else:
        # 2순위: 환경변수 CAMERA_CONFIG, 이것도 없으면 3순위: 기본 이름(config.json)
        env_config_name: str = f"{ENV_PREFIX}CONFIG"
        config_path = os.environ.get(env_config_name, DEFAULT_CONFIG_PATH)

    # 2단계: 설정 파일 읽기 ("camera" 구역, "stream" 구역으로 나뉘어 있다)
    file_data: dict[str, Any] = read_json_file(config_path)

    # 구역이 파일에 없으면 빈 딕셔너리를 쓴다. dict()로 복사하는 이유는
    # 아래에서 값을 덮어써도 file_data 원본이 바뀌지 않게 하기 위해서다
    camera_section: dict[str, Any] = file_data.get("camera", {})
    stream_section: dict[str, Any] = file_data.get("stream", {})
    camera_values: dict[str, Any] = dict(camera_section)
    stream_values: dict[str, Any] = dict(stream_section)

    # 3단계: 환경변수로 덮어쓰기 (같은 이름이면 환경변수가 이긴다)
    camera_values.update(read_env_overrides("camera", CAMERA_FIELD_TYPES))
    stream_values.update(read_env_overrides("stream", STREAM_FIELD_TYPES))

    # 모르는 설정 이름은 걸러내기
    camera_values = pick_known_fields(camera_values, CAMERA_FIELD_TYPES)
    stream_values = pick_known_fields(stream_values, STREAM_FIELD_TYPES)

    # 1단계(기본값)는 여기서 자동으로 적용된다:
    # 위에서 값을 못 받은 설정은 schema.py의 기본값이 그대로 쓰인다.
    config: AppConfig = AppConfig(
        camera=CameraSettings(**camera_values),
        stream=StreamSettings(**stream_values),
    )

    # 값이 말이 되는지 검사 (예: 포트 범위, 0보다 커야 하는 값)
    config.validate()
    return config
