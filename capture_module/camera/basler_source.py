"""Basler 산업용 카메라 소스 (pypylon).

streamer.py 의 Streamer 가 이 클래스로 카메라를 열고 read() 로 프레임을 받는다.
cv2.VideoCapture(일반 웹캠을 읽는 OpenCV 도구) 와 같은 방식(read / isOpened / release)으로 읽게 해 준다.

  - 픽셀 포맷은 후보 중 카메라가 지원하는 것을 골라 받고 BGR 로 바꾼다 (YUV 우선: 카메라 안에서 색 보정)
  - exposure / gain 등은 BaslerSource(exposure_us=...) 로 넘긴 값, 안 넘기면 config.py 의 BASLER_ 값을 연결할 때마다 적용
  - 케이블이 빠지거나 타임아웃이 나면 read() 가 False 를 돌려주고, 다음 read() 때 다시 연결을 시도
  - 카메라 없이 테스트하려면 config.BASLER_EMULATE = True (pylon 가상 카메라 사용)
"""

import os
import time

from .. import config   # .. : 한 단계 위 (capture_module 패키지)
from .camera_source import CameraSource


if config.BASLER_EMULATE: # 가상 카메라 모드가 켜져있으면
    os.environ["PYLON_CAMEMU"] = "1"

from pypylon import pylon


# PC에 연결된 Basler 카메라 목록 [(시리얼 번호, 모델 이름), ...] (없으면 빈 리스트)
def list_cameras():
    factory = pylon.TlFactory.GetInstance()
    return [(info.GetSerialNumber(), info.GetModelName()) for info in factory.EnumerateDevices()]


class BaslerSource(CameraSource):
    """Basler 카메라를 cv2.VideoCapture 와 같은 방식으로 읽게 해 주는 클래스. (CameraSource 틀을 따름)

    카메라 acA1300-60gc (ace GigE) 기준 설정 이름 사용
    """

    def __init__(self, **options):
        """options 로 카메라 설정을 넘길 수 있음. 안 넘긴 항목은 config.py 의 BASLER_ 값 사용.

        예) BaslerSource(exposure_us=20000, fps=30, white_balance="Once")
        """
        self.opt = {
            "serial_number": config.BASLER_SERIAL,  # 어떤 카메라 쓸지(None은 처음 잡히는 카메라)
            "exposure_us": config.BASLER_EXPOSURE_US, # 노출 시간 
            "gain_db": config.BASLER_GAIN_DB, # 밝기 증폭
            "fps": config.BASLER_FPS, # 초당 촬영 장수
            "packet_size": config.BASLER_PACKET_SIZE, # 패킷 사이즈
            "packet_delay": config.BASLER_PACKET_DELAY, # 패킷 사이 간격
            "num_buffers": config.BASLER_NUM_BUFFERS, # 버퍼 갯수
            "white_balance": config.BASLER_WHITE_BALANCE, # 자동 화이트밸런스
            "pixel_formats": config.BASLER_PIXEL_FORMATS, # 픽셀 포맷
            "light_source": config.BASLER_LIGHT_SOURCE, # 조명 색 보정
            "timeout_ms": config.BASLER_TIMEOUT_MS, # 프레임 최대 대기 시간
            "retry_seconds": config.BASLER_RETRY_SECONDS, # 재연결 간격
            "report_seconds": config.BASLER_REPORT_SECONDS, # 통계 출력 간격
        }
        # 넘겨 받은 이름 중에 모르는 이름 고르기
        unknown = set(options) - set(self.opt)

        # 하나라도 있으면
        if unknown:
            raise ValueError(f"모르는 카메라 옵션: {sorted(unknown)} (가능: {sorted(self.opt)})")
        self.opt.update(options) # 모르는거 없으면 넘겨받은 값으로 사용

        self.camera = None
        self.converter = pylon.ImageFormatConverter() # yuv -> bgr로 변환
        self.converter.OutputPixelFormat = pylon.PixelType_BGR8packed  # 받은 포맷(Bayer / YUV 등) -> BGR
        self.last_try = 0.0  # 마지막 연결 시도 시각 (재연결 간격 계산용)

        # 프레임 수신 통계 (실패할 때마다 찍지 않고 report_seconds 마다 요약해서 출력)
        self._ok_count = 0 # 성공 장수
        self._fail_count = 0 # 실패 장수
        self._last_error = "" # 실패 이유
        self._last_report = time.time() # 통계 출력 시각
        self._open() # 카메라 연결 시작

    # 카메라 찾고 연결하고 설정하고 촬영 시작
    def _open(self):
        self.last_try = time.time() # 지금 연결 시도 시간 기록
        try:
            factory = pylon.TlFactory.GetInstance() # 카메라 연결 관리자인 TlFactory 받아옴
            serial = self.opt["serial_number"] # 카메라 시리얼 번호 꺼냄
            if serial: # 시리얼 번호가 있으면
                device = None
                for info in factory.EnumerateDevices(): # pc에 연결된 모든 카메라의 정보 목록을 받아서 하나씩 봄
                    if info.GetSerialNumber() == serial: # 카메라 정보가 시리얼 번호랑 같으면
                        device = factory.CreateDevice(info) # 카메라 장치 객체 만들기
                        break
                if device is None: # 카메라 목록을 봤는데 못찾았으면
                    raise RuntimeError(f"시리얼 번호 {serial} 카메라를 찾을 수 없습니다") 
            else: # 시리얼 번호를 지정하지 않으면
                device = factory.CreateFirstDevice() # 검색된 카메라 중 첫번째 씀

            # 장치 객체를 instantcamera로 감싸서 저장
            self.camera = pylon.InstantCamera(device) # instantcamera는 기능을 얹은 객체(촬영 시작,중지, 프레임받기 뭐 이런것들)

            # 카메라와 통신을 시작함
            self.camera.Open()
            self._apply_settings() # config 설정을 카메라에 적용

            # 촬영 시작
            self.camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly) # LatestImageOnly : 밀린 프레임은 버리고 항상 최신 프레임만 받음
            print(f"[Basler] 연결됨: {self.camera.GetDeviceInfo().GetModelName()}")
        
        except Exception as error:
            print(f"[Basler] 연결 실패: {error}")
            self.release() # 카메라 사용을 끝내고 원래대로 돌려놓는 함수, 다른 프로그램이 카메라를 쓸 수 있도로 놓아줌

    # config 설정값을 카메라에 실제로 적용
    def _apply_settings(self):
        opt = self.opt # 설정값 딕셔너리
        self._apply_pixel_format() # 픽셀 포맷
        # 화이트밸런스 자동이 켜져 있으면 색 보정 프리셋이 잠겨서, 잠깐 끄고 바꾼 뒤 아래에서 다시 켬
        if opt["light_source"] is not None:
            self._set("BalanceWhiteAuto", "Off") # 자동 화이트밸런스 끄기
            self._set("LightSourceSelector", opt["light_source"]) # 조명 프리셋 바꿈
        self._set("AcquisitionFrameRateEnable", True) # fps 제한 켜기 (켜야 아래 fps 값이 적용됨)
        self._set("AcquisitionFrameRateAbs", opt["fps"]) # 초당 촬영 장수
        self._set("ExposureTimeAbs", opt["exposure_us"]) # 노출 시간 (마이크로초)
        self._set("Gain", opt["gain_db"])
        self._set("GevSCPSPacketSize", opt["packet_size"])  # GigE 전용, 촬영 시작 전에만 바꿀 수 있음
        self._set("GevSCPD", opt["packet_delay"])  # GigE 전용, 패킷을 몰아 보내지 않게 간격을 둠
        self._set("MaxNumBuffer", opt["num_buffers"])
        self._set("BalanceWhiteAuto", opt["white_balance"]) #자동 화이트 밸런스 다시 켜기
        self._print_network_info()

    # 카메라 연결이 끝난 뒤 네트워크 관련 상태 출력
    def _print_network_info(self):
        # 수신 드라이버 종류 확인
        try: 
            # pc가 카메라 영상을 어떤 방식으로 받고 있는지 읽어서 driver에 담음
            driver = self.camera.StreamGrabber.Type.Value # streamGrabber : pc쪽에서 영상 받아주는 부분 / .type.Value : 그게 어떤 종류인지
        except Exception as error: # 카메라의 수신 드라이버 종류를 읽지 못했을 때
            driver = f"확인 실패 ({error})"

        # 패킷 설정(크기와 간격) 읽기
        try:
            size = self.camera.GevSCPSPacketSize.Value # 패킷 크기
            delay = self.camera.GevSCPD.Value # 패킷 사이 간격
        except Exception as error: # 패킷 설정을 못 읽으면
            print(f"[Basler] 수신 드라이버: {driver}, 패킷 설정 확인 실패 ({error})") # 드라이버 정보만 출력하고 끝
            return
        # 패킷 설정 읽었으면 출력
        print(f"[Basler] 수신 드라이버: {driver}, 패킷 크기: {size}, 패킷 간격: {delay}")

    # 카메라가 이미지를 보낼 형식(픽셀 포맷)을 고르는 함수
    # 후보 중 카메라가 지원하는 첫 포맷 사용 (변환은 converter 가 포맷 보고 알아서 BGR 로)
    def _apply_pixel_format(self):
        supported = list(self.camera.PixelFormat.Symbolics) # 카메라가 지원하는 포맷 이름 목록을 supported에 담음
        for name in self.opt["pixel_formats"]: # 후보 목록을 앞에서 부터 하나씩 꺼내서 name에 담음
            if name in supported: # 후보가 목록에 있는지
                self.camera.PixelFormat.Value = name # 카메라의 픽셀 포맷을 name으로 설정
                break
        # 설정된 포맷과 지원 목록 출력
        print(f"[Basler] 픽셀 포맷: {self.camera.PixelFormat.Value} (지원: {', '.join(supported)})")

    # 카메라 설정 항목 하나에 값을 넣는 함수
    def _set(self, name, value):
        # name : 설정 이름, value : 넣을 값 (None 이면 건너뜀 → 카메라 원래 값 사용)
        if value is None:
            return
        try:
            getattr(self.camera, name).Value = value # getattr() : 문자열로 속성을 가져오는 함수
        except Exception as error: # 지원 안 하거나 값이 범위를 벗어나면 경고만 남기고 넘어감
            print(f"[Basler] {name} 설정 실패: {error}")

    # 카메라가 연결돼서 영상 받고 있는지 t/f
    def isOpened(self):
        return self.camera is not None and self.camera.IsGrabbing() #IsGrabbing : 카메라가 지금 촬영 중인지

    # 카메라에서 프레임 한장을 받아서 돌려주는 함수
    def read(self):
        # 연결 끊김 처리
        # 끊겨 있으면 retry_seconds 마다 재연결 시도
        if not self.isOpened(): # 카메라가 연결 되어서 촬영중인 상태가 아니면
            if time.time() - self.last_try >= self.opt["retry_seconds"]: # (지금시각 - 마지막 시도 시각)이 지연 시각보다 더 크면
                self._open() # 다시 연결 시도
            return False, None

        # 프레임 받기
        try:
            # RetrieveResult:다음 프레임을 최대 timeout_ms 기다리고 받음
            # 성공하면 result에 이미지와 성공 여부 들어감
            result = self.camera.RetrieveResult(self.opt["timeout_ms"], pylon.TimeoutHandling_ThrowException) 
        except Exception as error:  
            print(f"[Basler] 프레임 수신 오류: {error} -> 재연결 대기")
            self.release() # 카메라 닫기 -> 다음 read() 때 재연결 시도함
            return False, None

        # result 열어보고 프레임 쓸만한지 판단
        try:
            if result.GrabSucceeded(): # 프레임이 온전히 있는지
                # 받은 포맷(지금 yuv)를 bgr로 바꿈
                frame = self.converter.Convert(result).GetArray()
                self._ok_count += 1 # 성공 갯수 1 늘림
            else: # 프레임이 깨졌을 때
                frame = None # 돌려줄 프레임 없움
                self._fail_count += 1 # 실패 개수 1늘림
                self._last_error = result.ErrorDescription.split(".")[0]  # 실패 이유: 첫 문장만 (원인 요약)
        except Exception as error: # 변환 중 오류 
            frame = None # 돌려줄 프레임 없음
            self._fail_count += 1 # 실패 개수 +1
            self._last_error = f"변환 실패: {error}"

        result.Release() # 버퍼 반납 (위에서 에러를 다 잡으니 항상 여기까지 옴, 안 하면 버퍼가 바닥남)
        self._report() # 실패가 있으면 통계 출력

        # 프레임 온전 : (True, BGR 이미지(넘파이 배열 형식))
        # 프레임 깨졌으면 (False, None)
        return frame is not None, frame 

    # report_seconds 마다, 그 사이 실패가 있었으면 정상/실패 장수를 한 줄로 출력
    def _report(self):
        # 지금 시각 - 마지막 출력 시각 -> 마지막 출력 후에 지난 시각
        elapsed = time.time() - self._last_report
        if elapsed < self.opt["report_seconds"]: # report_seconds가 안됐으면 끝
            return
        if self._fail_count: # 실패가 있으면
            total = self._ok_count + self._fail_count # report_seconds 동안 받은 전체 장수
            print(f"[Basler] {time.strftime('%H:%M:%S')} 최근 {elapsed:.0f}초: 정상 {self._ok_count}장, "
                  f"실패 {self._fail_count}장 ({self._fail_count / total:.1%}) - {self._last_error}")
        self._ok_count = self._fail_count = 0 # 성공, 실패 개수를 0으로 초기화
        self._last_report = time.time() # 마지막 출력 시각

    # 촬영 멈추고 카메라 닫기
    def release(self):
        if self.camera is not None: # 카메라가 있을 때만
            try:
                if self.camera.IsGrabbing(): # 촬영 중이면
                    self.camera.StopGrabbing() # 촬영 멈춤
                if self.camera.IsOpen(): # 카메라가 열려있으면
                    self.camera.Close() # 카메라 닫음
            except Exception as error:
                print(f"[Basler] 종료 중 오류: {error}")
            self.camera = None
