# 장희정 - 로깅 설정: 출력 형식, 레벨, 파일 저장
"""camera_stream/logger.py - 모듈 전체가 공용으로 쓰는 로깅 설정.

- 각 파일은 logging.getLogger("camera_stream.xxx")로 로거만 가져다 쓰고,
  출력 형식과 레벨은 여기서 한 번만 정한다.
- log_file을 주면 화면과 파일에 함께 남긴다(측정 결과를 나중에 확인할 때 사용).
"""
import logging
from pathlib import Path

LOG_FORMAT = "[%(asctime)s] %(levelname)-7s %(name)s | %(message)s"
DATE_FORMAT = "%H:%M:%S"


def setup_logging(level: int = logging.INFO, log_file: str | Path | None = None):
    """로깅을 초기화한다. 프로그램 시작 시 한 번만 호출한다."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        handlers=handlers,
        force=True,  # 이미 설정돼 있어도 이 설정으로 덮어쓴다
    )

    # websockets가 연결마다 남기는 INFO 로그는 우리 상태 로그를 덮어버려서 경고 이상만 남긴다
    logging.getLogger("websockets").setLevel(logging.WARNING)
