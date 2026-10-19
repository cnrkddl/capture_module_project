"""설정값 모음."""

from pathlib import Path

PACKAGE_DIR = Path(__file__).parent  # 패키지 안 (기본 모델, viewer.html) - 설치하면 site-packages 안
WORK_DIR = Path.cwd()                 # 실행한 폴더 (캡쳐 사진, 결과 파일 저장 위치)

# ── 카메라 (Basler acA1300-60gc) ──
BASLER_SERIAL = None                  # 카메라 여러 대일 때 시리얼 번호 (None: 처음 잡히는 카메라)
BASLER_FPS = 60                       # 초당 촬영 장수
BASLER_EXPOSURE_US = 10000           # 노출 시간 (마이크로초)
BASLER_GAIN_DB = None                 # 게인 (None: 카메라 기본값)
BASLER_PIXEL_FORMATS = ["BayerRG8", "YUV422Packed", "BGR8Packed"]   # 이미지 형식 후보 (앞에서부터, BayerRG8: 데이터 작아 fps 유리, YUV: 색 자연스러움)
BASLER_LIGHT_SOURCE = "Daylight6500K" # 색 보정 프리셋: "Off" / "Daylight" / "Daylight6500K" / "Tungsten" / None
BASLER_WHITE_BALANCE = "Continuous"   # 자동 화이트밸런스: "Off" / "Once" / "Continuous" / None
BASLER_EMULATE = False                # True: 카메라 없이 pylon 가상 카메라로 테스트

# 네트워크 (프레임이 깨질 때 조정)
BASLER_PACKET_SIZE = None             # 패킷 크기 (None: 카메라 기본 1500, 점보 프레임이면 9000)
BASLER_PACKET_DELAY = 1000            # 패킷 사이 간격 (깨지면 늘리기, None 이면 카메라 전원 껐다 켤 때 0 이 됨)

# 고급 (보통 안 바꿈)
BASLER_NUM_BUFFERS = 20               # 받는 쪽 버퍼 개수
BASLER_TIMEOUT_MS = 5000              # 프레임 최대 대기 시간
BASLER_RETRY_SECONDS = 3              # 끊겼을 때 재연결 간격
BASLER_REPORT_SECONDS = 5             # 수신 실패 요약 출력 간격

# ── 화면 ──
ZOOM = 1                              # 확대 배율 (1: 확대 안 함)

# ── 모델 ──
MODEL_DIR = PACKAGE_DIR / "models"
MODEL_PATH = MODEL_DIR / "model.pt"        # 기본 모델 (10/8 버전, 패키지에 포함)
# 다른 모델: Streamer(model_path="...") 또는 capture-server --model ...
CLASSES = [
    "GLASS", "METAL", "PAPER", "PE",
    "PET_BLACK", "PET_CLEAR", "PET_COLOR",
    "PP", "PS", "RUBBER", "TEXTILE", "WOOD",
]

# ── 저장 ──
CAPTURE_DIR = WORK_DIR / "captures"
RESULTS_FILE = WORK_DIR / "results" / "results.jsonl"
JPEG_QUALITY = 95                     # 캡처 저장 jpg 화질

# ── 웹 서버 (main.py 테스트용) ──
HOST = "0.0.0.0"
PORT = 5000
STREAM_JPEG_QUALITY = 70              # 화면 영상 jpg 화질
STREAM_FPS = 30                       # 화면 영상 초당 장수
