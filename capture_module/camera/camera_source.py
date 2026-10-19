"""카메라 소스의 틀 (추상 클래스).

Streamer 는 카메라가 어떤 종류인지 몰라도 이 틀의 기능(isOpened / read / release)만으로 카메라를 쓴다.
새 카메라를 쓰려면 이 틀을 따르는 클래스를 만들면 된다. (예: basler_source.py 의 BaslerSource)
"""

from abc import ABC, abstractmethod


class CameraSource(ABC):
    """카메라라면 꼭 있어야 하는 기능. 이 틀을 따르는 클래스는 아래 세 함수를 모두 만들어야 한다."""

    @abstractmethod
    def isOpened(self):
        """카메라가 연결돼서 영상을 받고 있으면 True."""

    @abstractmethod
    def read(self):
        """프레임 한 장을 받아 (True, BGR 이미지) 로 돌려준다. 못 받으면 (False, None)."""

    @abstractmethod
    def release(self):
        """카메라를 닫는다."""
