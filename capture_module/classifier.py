"""분류기.

YOLOv8n-cls 모델(박지민 님 학습 모델)로 프레임을 분류한다.
모델을 바꾸려면 config.MODEL_PATH 의 파일만 교체하면 된다 (입출력 형식은 유지).
다른 경로의 모델은 Classifier(model_path) 로 사용.
모델은 process.py 의 CaptureProcessor 가 만들 때 한 번만 불러 두고 재사용한다.
"""

import threading
from pathlib import Path

from ultralytics import YOLO

from . import config


class Classifier:
    """모델 경로를 받아서 그 모델로 분류. (None: config.MODEL_PATH)

    만들 때 모델을 한 번 불러 두므로, classify() 를 부르면 바로 추론한다.
    """

    def __init__(self, model_path):
        # 모델 경로 정함, 안 넘기면 config에 기본경로 사용
        self.model_path = Path(model_path or config.MODEL_PATH)

        # 파일이 실제로 있는지 확인
        if not self.model_path.exists():
            raise FileNotFoundError(f"모델 파일이 없습니다: {self.model_path}")
        
        # 모델 파일을 실제로 불러옴
        self.model = YOLO(str(self.model_path))

        # 한 모델을 여러 요청이 동시에 쓰면 안전하지 않아서, 분류는 한 번에 하나씩
        self.lock = threading.Lock()
        print(f"[모델] {self.model_path.name} 사용")

        # 모델 안의 클래스 이름과 config.CLASSES 가 다르면 알려 줌
        model_class_names = [self.model.names[class_id] for class_id in sorted(self.model.names)]
        
        if model_class_names != config.CLASSES:
            print(f"[경고] 모델 클래스와 config.CLASSES 가 다릅니다.\n"
                  f"  모델  : {model_class_names}\n  config: {config.CLASSES}")


    # 사진 분류
    def classify(self, frame):
        """BGR 프레임을 받아 (label, score)를 돌려준다. score는 0~1."""
        with self.lock:
            result = self.model.predict(frame, verbose=False)[0] # verbose=False : yolo가 분류할 때 터미널에 찍는 로그 끔
        probs = result.probs                       # 모든 클래스의 확률
        label = result.names[probs.top1]           # 가장 높은 클래스 이름
        score = float(probs.top1conf)              # 그 클래스의 확률 (0~1)
        return label, score
