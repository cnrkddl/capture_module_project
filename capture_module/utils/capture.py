"""프레임 저장 + 파일명 규칙.
캡쳐한 사진을 규칙에 맞는 이름으로 저장하는 파일

저장 위치: <capture_dir>/<YYYY-MM-DD>/cap_<YYYYMMDD>_<HHMMSS>_<순번>.jpg
순번은 그날 폴더 안에서 001부터 하나씩 증가한다.

[사용 예]
    saver = FrameSaver("captures", 95)   # 저장 폴더, jpg 화질은 만들 때 한 번만 정함
    path = saver.save(frame, now)         # 저장할 때는 사진과 캡쳐 시각만 넘김
"""

import re
import threading
from pathlib import Path

import cv2


class FrameSaver:
    """캡쳐 사진을 규칙에 맞는 이름으로 저장하는 클래스."""

    # 캡쳐 파일명 규칙 (cap_날짜8자리_시간6자리_순번.jpg), 괄호 안이 순번
    _FILE_NAME_PATTERN = re.compile(r"^cap_\d{8}_\d{6}_(\d+)\.jpg$")

    def __init__(self, capture_dir, jpeg_quality):
        """
        capture_dir  : 캡쳐 사진 저장 폴더
        jpeg_quality : jpg 화질 (config.JPEG_QUALITY)
        """
        self.capture_dir = Path(capture_dir) # 저장 폴더 (한 번만 정함)
        self.jpeg_quality = jpeg_quality # jpg 화질 (한 번만 정함)
        self._lock = threading.Lock() # 캡쳐 요청이 동시에 와도 순번이 겹치지 않도록

    # 사진을 실제 파일로 저장하는 함수
    def save(self, frame, now):
        """프레임을 jpg로 저장하고 저장된 경로를 돌려준다.

        now: 파일명에 쓸 캡쳐 시각 (JSON 의 captured_at 과 같은 값)
        """
        # cv2.imwrite는 윈도우에서 한글 경로를 못 쓰므로 인코딩 후 직접 저장
        # 프레임을 jpg로 압축(메모리 안에서만)
        encoded, jpg_data = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        if not encoded: # 압축 실패하면
            raise RuntimeError("이미지 인코딩 실패") # 오류

        # 경로 결정~저장을 묶어서 잠금 (동시에 와도 같은 순번을 받지 않게)
        with self._lock:
            save_path = self._make_path(now) # 저장할 경로 만듦
            jpg_data.tofile(str(save_path)) # 압축한 jpg를 그 경로에 파일로 쓰기
        return save_path # 저장한 경로 돌려줌

    # 사진 저장할 경로를 만드는 함수 (날짜 폴더도 함께 생성)
    def _make_path(self, now):
        date_folder = self.capture_dir / now.strftime("%Y-%m-%d") # 날짜 폴더 경로
        date_folder.mkdir(parents=True, exist_ok=True) # 폴더가 없으면 만들기 / exist_ok=True: 이미 있으면 그냥 넘어가기 / parents=True: 중간 폴더도 같이 만들기

        sequence_number = self._next_sequence_number(date_folder) # 날짜 폴더 넘겨서 몇번째 사진인지 계산
        file_name = f"cap_{now:%Y%m%d}_{now:%H%M%S}_{sequence_number:03d}.jpg" # 파일 이름 만듦
        return date_folder / file_name # 날짜 폴더 경로 / 파일 이름 해서 전체 경로로 반환

    # 날짜 폴더 경로 받고 다음 번호가 몇번인지 계산하는 함수
    def _next_sequence_number(self, date_folder):
        """그날 폴더에 있는 파일 중 가장 큰 순번 + 1."""
        max_number = 0
        for file_path in date_folder.glob("cap_*.jpg"): # .glob() : 이름 규칙에 맞는 파일을 찾아주는 기능
            name_match = self._FILE_NAME_PATTERN.match(file_path.name) # 파일명이 정해둔 패턴과 맞는지 확인 -> 맞으면 Match 객체, 아니면 None
            if name_match: # 맞으면
                max_number = max(max_number, int(name_match.group(1))) # group(1) : 첫번째 괄호 그룹 (순번)
        return max_number + 1
