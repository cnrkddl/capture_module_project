# capture_module

Basler 카메라로 사진을 캡쳐하고, 학습된 모델(YOLOv8n-cls)로 재질을 분류하는 모듈입니다.

- 캡쳐 → jpg 저장 → 재질 분류 → 결과 기록(jsonl)을 한 번에 처리
- 웹 화면(실시간 영상 + 캡쳐 버튼) 또는 파이썬 코드에서 사용
- 분류 클래스 12종: `GLASS` `METAL` `PAPER` `PE` `PET_BLACK` `PET_CLEAR` `PET_COLOR` `PP` `PS` `RUBBER` `TEXTILE` `WOOD`

---

## 1. 설치

**필요 환경**: Python 3.10 이상, Basler 카메라 (acA1300-60gc 기준)

```
pip install dist/capture_module-0.1.7-py3-none-any.whl
```

- 필요한 라이브러리(opencv-python, numpy, ultralytics, pypylon, flask)는 함께 자동 설치됩니다.
- 처음 설치할 때는 ultralytics가 PyTorch를 받기 때문에 인터넷이 필요하고 시간이 걸립니다.
- 기본 모델(`model.pt`)이 패키지 안에 들어 있어서 따로 준비할 필요가 없습니다.

설치 확인:
```
pip show capture_module
```

---

## 2. 웹 화면으로 사용

```
capture-server
```
서버가 켜지면 브라우저에 웹 화면(**http://localhost:5000**)이 자동으로 열리고, 실시간 영상과 캡쳐 버튼이 나옵니다.

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--model 경로` | 다른 분류 모델(.pt) 사용 | 패키지 안 `model.pt` |
| `--port 번호` | 포트 번호 | `5000` |
| `--host 주소` | 접속 받을 주소 | `0.0.0.0` (다른 PC에서도 접속 가능) |
| `--no-browser` | 브라우저 자동으로 안 열기 | (자동으로 열림) |

```
capture-server --model D:/models/new.pt --port 8000
capture-server --help
```

종료: 터미널에서 `Ctrl + C`

### GUI 창으로 사용

```
capture-gui
```
브라우저 대신 프로그램 창이 뜨고, 웹 화면과 똑같이 실시간 영상, 캡쳐 버튼(Space 키), 결과 표가 나옵니다.

- 카메라가 없어도 창은 열립니다. 창 위쪽 **카메라** 목록에 PC에 연결된 Basler 카메라가 나오고, 찾으면 첫 번째 카메라에 자동으로 연결됩니다.
- 카메라를 나중에 꽂았으면 **[새로고침] → [연결]**
- 다른 카메라로 바꾸려면 **[해제] → 목록에서 선택 → [연결]**
- 노출, FPS 같은 촬영 설정은 `config.py`의 `BASLER_` 값을 사용합니다.

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--model 경로` | 다른 분류 모델(.pt) 사용 | 패키지 안 `model.pt` |

종료: 창 닫기

카메라는 한 프로그램만 쓸 수 있어서 `capture-server`와 `capture-gui`를 동시에 켤 수는 없습니다.

---

## 3. 코드에서 사용

### 카메라로 캡쳐

```python
import time
from capture_module import Streamer

with Streamer() as cam:       # 모델 불러오기 + 카메라 연결 + 영상 받기 시작
    time.sleep(1)             # 첫 프레임이 들어올 때까지 대기
    result = cam.capture()    # 지금 장면 캡쳐 → 저장 → 분류
    print(result)
# with 블록이 끝나면 카메라가 자동으로 닫힙니다
```

`with` 없이 사용할 때는 직접 시작하고 닫습니다.
```python
cam = Streamer().start()
...
cam.capture()
...
cam.stop()     # 꼭 닫아야 다른 프로그램에서 카메라를 쓸 수 있습니다
```

`capture()`는 아직 받은 프레임이 없으면 `None`을 돌려줍니다.

### 옵션

`Streamer`에 넘기지 않은 항목은 기본값을 사용합니다.

```python
Streamer(
    model_path="D:/models/new.pt",          # 분류 모델
    capture_dir="D:/사진",                   # 캡쳐 사진 저장 폴더
    results_file="D:/결과/results.jsonl",    # 결과 파일
    jpeg_quality=95,                        # 저장 jpg 화질
    zoom=1.5,                               # 화면 가운데 확대 배율 (1: 확대 안 함)
    camera_options={                        # Basler 카메라 설정
        "exposure_us": 20000,               #   노출 시간 (마이크로초)
        "fps": 20,                          #   초당 촬영 장수
        "serial_number": "12345678",        #   카메라가 여러 대일 때 시리얼 번호
    },
)
```

사용 가능한 `camera_options`: `serial_number` `exposure_us` `gain_db` `fps` `white_balance` `light_source` `pixel_formats` `packet_size` `packet_delay` `num_buffers` `timeout_ms` `retry_seconds` `report_seconds`
(모르는 이름을 넣으면 오류와 함께 가능한 목록을 알려줍니다)

---

## 4. 결과

### 결과 형식

`capture()`가 돌려주는 값이고, 결과 파일에도 한 줄씩 같은 형식으로 쌓입니다.

```json
{"image": "cap_20261008_141530_001.jpg", "captured_at": "2026-10-08T14:15:30", "class": "PET_CLEAR", "confidence": 96.4}
```

| 키 | 설명 |
|---|---|
| `image` | 저장된 사진 파일 이름 |
| `captured_at` | 캡쳐 시각 (초 단위) |
| `class` | 분류된 재질 |
| `confidence` | 확률 (%) |

### 저장 위치

옵션을 따로 주지 않으면 **명령어(또는 파이썬 코드)를 실행한 폴더** 기준으로 저장됩니다.

```
실행한 폴더/
├─ captures/
│   └─ 2026-10-08/
│       ├─ cap_20261008_141530_001.jpg     (날짜별 폴더, 순번은 매일 001부터)
│       └─ ...
└─ results/
    └─ results.jsonl                       (캡쳐할 때마다 한 줄씩 추가)
```

---

## 5. HTTP API

`capture-server`가 켜져 있을 때 다른 프로그램에서도 호출할 수 있습니다.

| 주소 | 방식 | 설명 |
|---|---|---|
| `/` | GET | 웹 화면 |
| `/video_feed` | GET | 실시간 영상 (MJPEG) |
| `/capture` | POST | 캡쳐 후 결과 JSON 반환. 프레임이 아직 없으면 `503` |

```
curl -X POST http://localhost:5000/capture
```

---

## 6. 개발자용

### 폴더 구조

```
capture_module/
├─ pyproject.toml          패키지 설정 (이름, 버전, 의존성, 명령어)
├─ README.md
├─ requirements.txt
├─ models_archive/         예전 모델 보관 (패키지에 포함 안 됨)
├─ captures/, results/     실행하면 생기는 캡쳐 사진, 결과 파일
├─ capture_module/         ← 설치되는 패키지
│   ├─ __init__.py         Streamer, CaptureProcessor, CameraSource 공개
│   ├─ main.py             웹 서버 (capture-server)
│   ├─ gui.py              GUI 창 (capture-gui)
│   ├─ streamer.py         카메라 프레임 계속 받기 + capture()
│   ├─ process.py          사진 한 장 → 저장 → 분류 → 결과 기록
│   ├─ classifier.py       모델 불러오기 + 분류
│   ├─ config.py           기본 설정값
│   ├─ camera/
│   │   ├─ camera_source.py   카메라 공통 틀 (다른 카메라 추가할 때 사용)
│   │   └─ basler_source.py   Basler 카메라 연결 (pypylon)
│   ├─ utils/
│   │   ├─ capture.py         사진 저장 (파일 이름 규칙)
│   │   ├─ schema.py          결과 형식
│   │   └─ zoom.py            가운데 확대
│   ├─ models/model.pt     기본 모델
│   └─ templates/viewer.html
└─ dist/
    └─ capture_module-0.1.7-py3-none-any.whl   설치 파일
```

### 코드 수정 후 다시 빌드

1. `pyproject.toml`의 `version`을 올립니다 (예: `0.1.0` → `0.1.1`). 버전은 이 한 곳에서만 관리합니다.
2. 빌드:
   ```
   pip wheel . --no-deps -w dist
   ```
3. 새로 만든 whl로 설치합니다.

개발 중에는 편집 모드로 설치하면 다시 빌드하지 않아도 수정한 코드가 바로 반영됩니다.
```
pip install -e .
```

설치 없이 실행: 프로젝트 폴더에서 `python -m capture_module.main`
(`python capture_module/main.py`로 직접 실행하면 import 오류가 납니다)
