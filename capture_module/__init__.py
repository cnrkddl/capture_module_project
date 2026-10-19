"""캡쳐 모듈: Basler 카메라 캡쳐 + 재질 분류.

[사용 예]
    from capture_module import Streamer

    with Streamer() as cam:           # 카메라 연결 + 기본 모델 불러오기
        result = cam.capture()        # {"image": ..., "captured_at": ..., "class": ..., "confidence": ...}

    from capture_module import CaptureProcessor
    result = CaptureProcessor().process(frame)   # 카메라 없이 사진 한 장 분류

웹 화면: 설치 후 터미널에서 capture-server
GUI 창:  설치 후 터미널에서 capture-gui
"""

from importlib.metadata import version

from .camera.camera_source import CameraSource
from .process import CaptureProcessor
from .streamer import Streamer

__version__ = version("capture_module")  # 버전은 pyproject.toml 한 곳에서만 관리

__all__ = ["Streamer", "CaptureProcessor", "CameraSource"]
