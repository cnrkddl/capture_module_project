"""사진 한 장 처리: 저장 → 분류 → 결과 기록 → 결과 dict 리턴 (카메라 종류 상관없음).

Streamer 가 시작할 때 CaptureProcessor 를 한 번 만들어 두고, 캡쳐할 때마다 process() 를 부른다.
카메라 없이 사진 파일로 바로 써도 된다.

[사용 예]
    import cv2
    from capture_module import CaptureProcessor

    processor = CaptureProcessor()        # 모델 불러오기 (설정은 안 넘기면 config.py 값)
    result = processor.process(cv2.imread("test.jpg"))
    # {"image": "cap_20261002_151530_001.jpg", "captured_at": "2026-10-02T15:15:30",
    #  "class": "GLASS", "confidence": 95.0}
"""

import json
import threading
from datetime import datetime
from pathlib import Path

from . import config
from .classifier import Classifier
from .utils.capture import FrameSaver
from .utils.schema import CaptureResult


class CaptureProcessor:
    """사진 한 장을 저장 → 분류 → 결과 기록까지 처리하는 클래스.

    모델 / 저장기 / 결과 파일은 만들 때 한 번만 준비해 두고, process() 할 때마다 재사용한다.
    """

    def __init__(self, model_path=None, capture_dir=None, results_file=None, jpeg_quality=None):
        """
        model_path   : 분류 모델 .pt 경로    (None: config.MODEL_PATH)
        capture_dir  : 캡쳐 사진 저장 폴더    (None: config.CAPTURE_DIR)
        results_file : 결과 jsonl 파일       (None: config.RESULTS_FILE)
        jpeg_quality : 캡쳐 저장 jpg 화질     (None: config.JPEG_QUALITY)
        """
        # 모델은 여기서 한 번만 불러 둠 -> process() 하면 바로 분류
        self.classifier = Classifier(model_path)
        # 저장기: 저장 폴더와 화질을 기억해 둠
        self.saver = FrameSaver(capture_dir or config.CAPTURE_DIR, jpeg_quality or config.JPEG_QUALITY)
        # 결과 파일 경로
        self.results_file = Path(results_file or config.RESULTS_FILE)
        # 결과 jsonl에 한번에 하나만 쓸 수 있도록
        self._results_lock = threading.Lock()

    # 처리: 사진 한 장 -> 저장 -> 분류 -> 결과 기록 -> 결과 dict 리턴
    def process(self, frame, captured_at=None):
        """BGR 사진(numpy 배열) 한 장을 저장하고 분류해서 결과를 돌려준다.

        captured_at : 캡쳐 시각 (None: 지금 시각)
        리턴 예) {"image": "cap_20261002_151530_001.jpg", "captured_at": "2026-10-02T15:15:30",
                  "class": "GLASS", "confidence": 95.0}
        """
        if frame is None: # 사진이 없으면
            raise ValueError("frame 이 None 입니다 (사진을 제대로 읽었는지 확인)")
        captured_at = captured_at or datetime.now() # 캡쳐 시각 받았으면 쓰고 없으면 지금 시각 씀

        # 이미지 저장 (사진, 시각)
        path = self.saver.save(frame, captured_at)

        # 불러 둔 모델로 사진 분류
        label, score = self.classifier.classify(frame)

        # 결과 형식 맞추기
        result = CaptureResult.create(path.name, captured_at, label, score)

        # 파일에 기록
        self._append_result(result) # jsonl에 추가

        # 터미널에 로그 출력
        print(f"[캡쳐] {result.image} -> {result.class_name} ({result.confidence}%)")

        # 결과를 딕셔너리로 바꿔서 돌려줌
        return result.to_dict()

    # 결과를 json 파일에 추가
    def _append_result(self, result):
        # 결과 파일이 들어갈 폴더가 없으면 만듦
        # parent : 파일이 들어있는 폴더 / parents=True : 중간폴더까지 다 만들기 / exist_ok=True: 이미 있으면 그냥 넘어감
        self.results_file.parent.mkdir(parents=True, exist_ok=True)
        # 'a' : 이어쓰기 모드
        with self._results_lock, open(self.results_file, "a", encoding="utf-8") as results_jsonl:
            results_jsonl.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n") # result 객체를 딕셔너리로 -> json으로 -> 끝에 줄바꿈 붙여서 파일 끝에 쓰기
