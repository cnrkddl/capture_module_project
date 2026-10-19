"""캡쳐 결과 JSON 형식 정의

results.jsonl 한 줄 예시:
{"image": "cap_20261001_104012_001.jpg", "captured_at": "2026-10-01T10:40:12",
 "class": "PET_CLEAR", "confidence": 96.4}
"""

# 타입 힌트를 나중에 볼 수 있게
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime


@dataclass
class CaptureResult:
    image: str          # 이미지 파일명
    captured_at: str    # 캡쳐 시각
    class_name: str     # 분류된 클래스명
    confidence: float   # 해당 클래스 확률

    @classmethod
    # 아직 객체가 없을 때 처음 만드는 함수라서 틀인 클래스가 cls로 들어옴
    def create(cls, image: str, captured_at: datetime, label: str, score: float) -> CaptureResult:
        # "" : 이 줄이 실행되는 시점에는 CaptureResult라는 이름이 없음
        # 클ㄹ스 블록을 위에서부터 읽으면서 메서드를 만들고, 블록을 끝까지 다 읽은 다음에 이름 등록
        # 반환 힌트 함수는 함수 정의 순간에 바로 평가 됨
        """분류 결과로 결과 객체를 만든다."""
        return cls(
            image=image,                                            # 파일명만
            captured_at=captured_at.isoformat(timespec="seconds"),  # 초 단위
            class_name=label,
            confidence=round(score * 100, 1),                       # 0~1 → % (0.964 → 96.4)
        )

    # create로 이미 만들어진 결과 객체를 다루는 함수 -> self
    def to_dict(self) -> dict: # json으로 바꾸려면 딕셔너리 필요
        return {
            "image": self.image,
            "captured_at": self.captured_at,
            "class": self.class_name,
            "confidence": self.confidence,
        }
