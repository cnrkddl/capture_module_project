# 박지민 - CameraSource: 카메라 연결, 프레임 수집, 변환, 재연결
"""camera_stream/camera.py - Basler 카메라 연결 및 프레임 수집.

- pypylon으로 카메라에 연결하고 gain/exposure 등 파라미터를 지정한다.
- 픽셀 포맷을 8비트 Bayer(BayerRG8)로 설정해 GigE 대역폭을 아껴 60fps를 확보하고,
  받은 프레임은 ImageFormatConverter로 Bayer -> BGR 변환한다.
- 해상도는 하드코딩하지 않고 카메라가 알려주는 값(변환된 배열의 shape)을 그대로 쓴다.
- 연결이 끊기거나 타임아웃이 나면 일정 간격으로 재연결을 시도하고,
  재연결에 성공하면 gain/exposure 등 설정값을 다시 적용한다.
- 프레임 번호와 촬영 시각(timestamp)을 기록해 Frame으로 만든다.
- 새 프레임이 준비되면 on_frame(frame)을 불러 넘겨준다. 누가 받는지는 모른다(연결은 __init__.py가 한다).
"""
import logging
import threading
import time
from typing import Callable

from pypylon import pylon

from .schema import CameraSettings, Frame

log = logging.getLogger("camera_stream.camera")


# 스레드, 연결 상태, 변환기 등 카메라 수집에 필요한 상태가 많아서 속성 개수 제한을 넘는다
class CameraSource:  # pylint: disable=too-many-instance-attributes
    """카메라에서 프레임을 계속 받아 on_frame으로 넘긴다. 끊기면 자동 재연결."""

    # 카메라 모델(GigE/USB3)에 따라 노드 이름이 다를 수 있어 후보를 순서대로 시도한다.
    _EXPOSURE_NODES = ("ExposureTimeAbs", "ExposureTime")  # 둘 다 단위는 마이크로초라 값 그대로 써도 안전
    _WHITE_BALANCE_NODES = ("BalanceWhiteAuto",)
    _PACKET_SIZE_NODES = ("GevSCPSPacketSize",)
    _FRAME_RATE_NODES = ("AcquisitionFrameRateAbs", "AcquisitionFrameRate")

    # 카메라 객체가 처음 만들어질 때 한번 실행되는 함수
    def __init__(self, settings: CameraSettings | None = None):
        self.settings = settings or CameraSettings() #fb 
        # 새 프레임을 넘겨줄 곳. 연결은 __init__.py가 한다 (camera는 받는 쪽이 누군지 모름)
        # 수집 스레드에서 불리므로, 여기 연결하는 함수는 오래 걸리거나 예외를 던지면 안 된다
        self.on_frame: Callable[[Frame], None] | None = None #fb함수가 아닌데 왜 콜라블 
        self.frame_count = 0
        self.connected = False
        self._camera: pylon.InstantCamera | None = None
        self._converter = pylon.ImageFormatConverter()
        self._converter.OutputPixelFormat = pylon.PixelType_BGR8packed  # 컬러(Bayer) -> BGR
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        """수집 스레드를 시작한다."""
        self._thread = threading.Thread(target=self._run, daemon=True, name="CameraSource") #데몬이면 서브 스레드, 이곳에서 생성됨 
        self._thread.start() #스레드를 출발시킨다 

    def stop(self):
        """수집 스레드에 종료 신호를 보내고, 끝날 때까지 기다린다."""
        self._stop.set()

        if self._thread is not None:
            # + 재연결 대기 한 번(retry_sec) + 여유분
            timeout = self.settings.grab_timeout_ms / 1000 + self.settings.retry_sec + 1.0
            self._thread.join(timeout=timeout)

            if self._thread.is_alive():
                log.warning("카메라 스레드가 %.1f초 안에 종료되지 않았습니다 (백그라운드에서 계속 실행 중)", timeout)

    # 내부 루프 -----------------------------------------------------------------

    def _run(self): #자동으로 재생성 

        while not self._stop.is_set(): 
            try:
                self._open() #카메라 연결 
                self._grab_loop() #프레임을 계속 받음(무한 반복)

            # 연결 실패, 타임아웃, 케이블 뽑힘 등 원인을 미리 알 수 없어 넓게 잡고 재연결한다
            except Exception as error:  # pylint: disable=broad-exception-caught
                log.error("카메라 오류: %s", error) #except에서 하는 거 . 로그를 남긴다 

            finally:
                self._close() #카메라 정리 

            if not self._stop.is_set(): #종료 신호가 없으면 
                log.info("카메라 재연결 시도 (%.0f초 후)", self.settings.retry_sec)
                # time.sleep이면 stop()이 와도 최대 retry_sec만큼 그냥 기다린다.
                # Event.wait는 stop() 신호가 오는 즉시 깨어난다.
                self._stop.wait(self.settings.retry_sec)  #대기 

    def _find_device(self) -> pylon.IPylonDevice:
        """serial_number가 지정돼 있으면 그 장치를 아니면 처음 잡히는 장치를 쓴다."""
        factory = pylon.TlFactory.GetInstance()

        if not self.settings.serial_number:
            return factory.CreateFirstDevice() #처음 잡히는 카메라 

        for info in factory.EnumerateDevices():
            if info.GetSerialNumber() == self.settings.serial_number:
                return factory.CreateDevice(info) #번호가 맞는 카메라 

        raise RuntimeError(f"시리얼 번호 {self.settings.serial_number}인 카메라를 찾을 수 없습니다")

    def _open(self): #카메라 연결
        device = self._find_device() #카메라 찾기
        self._camera = pylon.InstantCamera(device)
        self._camera.Open() #열기

        self._apply_settings()  # 카메라 설정 (촬영 시작 전에 불러야 함)
        self._camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly) #촬영 시작, 라이브러리의 기능

        self.connected = True
        log.info("카메라 연결됨: %s", self._camera.GetDeviceInfo().GetModelName())

    def _apply_settings(self):
        """연결할 때(최초/재연결) 카메라에 설정값을 넣는다. StartGrabbing() 전에 불러야 한다."""
        self._set_first_available(("PixelFormat",), "BayerRG8")  # 컬러 중 용량이 가장 작아 60fps에 유리
        self._set_first_available(("AcquisitionFrameRateEnable",), True)
        self._set_first_available(self._FRAME_RATE_NODES, self.settings.target_fps)
        self._set_first_available(self._PACKET_SIZE_NODES, self.settings.packet_size)
        self._set_first_available(self._EXPOSURE_NODES, self.settings.exposure_us)

        # 게인: 신형 Gain 먼저, 안 되면 구형 GainRaw
        if not self._set_first_available(("Gain",), self.settings.gain_db):
            self._set_first_available(("GainRaw",), self.settings.gain_raw)

        self._set_first_available(self._WHITE_BALANCE_NODES, self.settings.white_balance)

        log.info(
            "카메라 픽셀 포맷: %s, 목표 %.0ffps",
            self._camera.PixelFormat.Value,
            self.settings.target_fps,
        )

    def _set_first_available(
        self, node_names: tuple[str, ...], value: float | int | str | bool | None
    ) -> bool:
        """node_names 후보 중 카메라가 지원하는 첫 노드에 value를 적용한다 (모든 후보가 같은 단위일 때만 사용).
        적용했으면 True, value가 None이거나 모든 후보가 실패하면 False를 돌려준다.
        """
        if value is None:
            return False

        for node_name in node_names:
            try:
                getattr(self._camera, node_name).Value = value

            # 노드가 없거나 값이 안 맞을 때 pypylon이 던지는 예외 종류가 여러 가지라 넓게 잡는다
            except Exception as error:  # pylint: disable=broad-exception-caught
                log.debug("카메라 %s 설정 실패, 다음 후보 시도: %s", node_name, error)
                continue

            log.info("카메라 %s = %s", node_name, value)
            return True

        log.warning("카메라가 %s 노드를 지원하지 않습니다 (값 %s 적용 실패)", "/".join(node_names), value)
        return False

    def _grab_loop(self): # 카메라에서 한장씩 뽑음 계속 반복. RetrieveResult로 꺼내고 성공하면 _on_frame으로 넘김
        while self._camera.IsGrabbing() and not self._stop.is_set(): #그만 신호 없으면 계속
            result = self._camera.RetrieveResult( #한장 꺼냄 
                self.settings.grab_timeout_ms, pylon.TimeoutHandling_ThrowException
            )

            received_at = time.time()  # 받은 시간 기록

            try:
                if result.GrabSucceeded():
                    self._on_frame(result, received_at) #사진을 넘긴다 onframe으로.

                else:
                    log.warning("프레임 수신 실패: %s", result.ErrorDescription)

            finally:
                result.Release() 

    # 위에서 받은 사진 처리 .. 변환하고 Frame을 만드는 곳
    def _on_frame(self, result: pylon.GrabResult, received_at: float):
        image = self._converter.Convert(result).GetArray()  # 해상도는 여기서 나온 shape을 그대로 사용
        self.frame_count += 1  #받은 장수 +1

        frame = Frame(  #객체 만든다. 
            frame_no=self.frame_count,
            timestamp=received_at,
            camera_timestamp=result.TimeStamp,
            width=image.shape[1],
            height=image.shape[0],
            image=image,
        )

        if self.on_frame is not None:  # 연결된 곳이 있나 확인 
            self.on_frame(frame) #온프레임에 담긴 함수를 실행, pushframe으로 

    def _close(self):#끊기면..... 
        was_connected = self.connected
        self.connected = False

        if self._camera is not None:
            try:
                if self._camera.IsGrabbing():
                    self._camera.StopGrabbing()

                if self._camera.IsOpen():
                    self._camera.Close()

            # 케이블이 이미 뽑힌 상태 등 종료 중 어떤 오류가 나도 정리는 끝까지 해야 해서 넓게 잡는다
            except Exception as error:  # pylint: disable=broad-exception-caught
                log.error("카메라 종료 중 오류: %s", error)

            self._camera = None

        if was_connected:
            log.warning("카메라 연결 끊김")
