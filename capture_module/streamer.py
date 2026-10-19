"""캡쳐 모듈: Basler 카메라에서 계속 최신 프레임을 받아 두고, 캡쳐 버튼(capture()) 처리.

백그라운드 스레드가 계속 프레임을 읽어 최신 프레임만 들고 있고,
캡쳐할 때는 그 최신 프레임을 CaptureProcessor(process.py) 에 넘겨 저장 → 분류 → 결과 기록한다.

  streamer.py   카메라 프레임 계속 읽기 + 최신 프레임 보관 + capture() 액션
  process.py    사진 한 장 → 저장 → 분류 → 결과 기록 (카메라 없이도 사용 가능)
"""

import asyncio
import threading
import time
from datetime import datetime

from . import config
from .camera.basler_source import BaslerSource
from .camera_stream import Frame, StreamServer, StreamSettings
from .process import CaptureProcessor
from .utils.zoom import zoom


class Streamer:
    """카메라에서 계속 최신 장면을 받아 두고, capture() 하면 그 장면을 CaptureProcessor 로 처리.

    카메라는 CameraSource 틀(isOpened / read / release)만 보고 쓴다. (기본: Basler 카메라)
    """

    def __init__(self, model_path=None, camera_options=None, capture_dir=None, results_file=None,
                 jpeg_quality=None, camera=None, zoom=None, processor=None):
        """
        model_path     : 분류 모델 .pt 경로                            (None: config.MODEL_PATH)
        camera_options : Basler 설정 dict 예) {"exposure_us": 20000}   (None: config.BASLER_ 값)
        capture_dir    : 캡쳐 사진 저장 폴더                            (None: config.CAPTURE_DIR)
        results_file   : 결과 jsonl 파일                               (None: config.RESULTS_FILE)
        jpeg_quality   : 캡쳐 저장 jpg 화질                             (None: config.JPEG_QUALITY)
        camera         : 사용할 카메라 (CameraSource 틀을 따르는 객체)   (None: camera_options 로 BaslerSource 만들어 씀)
        zoom           : 확대 배율 예) 2.0                            (None: config.ZOOM)
        processor      : 이미 만들어 둔 CaptureProcessor (모델을 다시 안 불러옴)
                         넘기면 model_path / capture_dir / results_file / jpeg_quality 는 안 씀
                                                                      (None: 위 값으로 새로 만듦)
        """

        # 줌 설정
        # zoom 값을 안넣었으면 config의 값 사용
        self.zoom = config.ZOOM if zoom is None else zoom

        # 저장 → 분류 → 기록 담당을 한 번만 만들어 둠 (모델도 여기서 미리 불러 둠 -> capture() 하면 바로 추론)
        # processor 를 받았으면 그대로 씀 (GUI 에서 카메라를 다시 연결할 때 모델을 또 불러오지 않게)
        if processor is None:
            processor = CaptureProcessor(model_path, capture_dir, results_file, jpeg_quality)
        self.processor = processor

        # 카메라 연결
        if camera is None: # 설정한 카메라가 없으면 basler 씀
            camera = BaslerSource(**(camera_options or {}))  # 딕셔너리 비어있으면 {} 로 씀 / ** : 딕셔너리 풀어서 넘겨(이름=값)
        self.cap = camera

        # 영상 소스가 안 열렸으면 멈춤
        if not self.cap.isOpened(): # 카메라가 열리지 않았으면
            raise RuntimeError("카메라를 열 수 없습니다 (연결 / 다른 프로그램이 사용 중인지 확인)")

        self._frame = None # 최신 프레임 자리
        self._lock = threading.Lock()
        self._running = False # 스위치
        self._thread = None

        self.stream_server = None # WebSocket 송출 서버 (start_stream() 을 부르면 만들어짐)
        self._stream_loop = None # 송출 서버가 도는 이벤트 루프
        self._frame_no = 0 # 송출 프레임 번호

    # 영상 받기 시작 (백그라운드 스레드)
    def start(self):
        self._running = True # 스위치 켬
        self._thread = threading.Thread(target=self._loop, daemon=True) # daemon=True: 프로그램 끝나면 스레드도 끔
        self._thread.start() # 스레드 시작
        return self

    # WebSocket 송출 서버를 별도 스레드(자체 이벤트 루프)에서 켬. 카메라는 이 Streamer 가 열어 둔 것을 그대로 씀
    def start_stream(self, settings=None):
        if self.stream_server is not None: # 이미 켜져 있으면 또 켜지 않음
            return self

        self.stream_server = StreamServer(settings or StreamSettings())
        self._stream_loop = asyncio.new_event_loop()

        def run():
            asyncio.set_event_loop(self._stream_loop)
            self._stream_loop.run_until_complete(self.stream_server.start())
            self._stream_loop.run_forever()

        threading.Thread(target=run, daemon=True).start()
        return self

    # 스레드가 반복 : 스위치가 꺼질 때까지 사진 받고 -> 최신 사진으로 교체 -> (실패하면 쉬기 )반복
    def _loop(self):
        while self._running: # 스위치가 true인 동안 계속 반복
            ok, frame = self.cap.read() # 카메라에서 한장 받아옴(true, GBR이미지)
            if not ok: # 못 받았으면
                time.sleep(0.1) # 0.1초 쉼
                continue
            frame = zoom(frame, self.zoom) # 설정한 배율만큼 확대
            if self.stream_server is not None: # 송출 서버가 켜져 있으면 같은 프레임을 넘김 (압축, 송출은 서버가 함)
                self._frame_no += 1
                height, width = frame.shape[:2]
                self.stream_server.push_frame(Frame(self._frame_no, time.time(), 0, width, height, frame))
            with self._lock: # 받았으면 바꾸는 중에 꺼내가지 않도록 잠금
                self._frame = frame

    # 최신 프레임의 복사본을 줌, 아직 없으면 None
    def get_frame(self):
        with self._lock: # 잠금
            if self._frame is None: # 없으면
                return None # none
            return self._frame.copy() # 있으면 복사해서 리턴

    # 프레임 받기가 돌고 있는지 (start() 후 True, stop() 하면 False)
    def is_running(self):
        return self._running

    # 영상 받기 멈추고 카메라 닫기
    def stop(self):
        self._running = False # 스위치 끔
        if self._thread: # 스레드 있으면
            self._thread.join(timeout=1) # 최대 1초만 기다림
        if self.stream_server is not None: # 송출 서버 정리 (실패해도 카메라는 꼭 닫아야 해서 아래로 계속 진행)
            try:
                asyncio.run_coroutine_threadsafe(self.stream_server.stop(), self._stream_loop).result(timeout=3)
                self._stream_loop.call_soon_threadsafe(self._stream_loop.stop)
            except Exception: # pylint: disable=broad-exception-caught
                pass
            self.stream_server = None
        self.cap.release() # 카메라 닫기


    # 액션(캡쳐 버튼): 지금 장면 캡쳐 -> processor 로 저장 -> 분류 -> 결과 기록 -> 결과 dict 리턴
    def capture(self):
        """지금 장면을 캡쳐해서 바로 추론하고 결과를 돌려준다. 아직 프레임이 없으면 None."""
        frame = self.get_frame() # 캡쳐 순간 장면 가져옴
        captured_at = datetime.now() # 캡쳐 시각 기록
        if frame is None: # 사진이 없으면
            return None
        return self.processor.process(frame, captured_at)

    # with 문 지원
    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
