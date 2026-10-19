"""디지털 줌: 사진의 가운데를 잘라서 원래 크기로 늘린다 (돋보기 느낌).

참고: https://github.com/harimkang/openCV-with-Zoom (자르기 + 늘리기 방식)
렌즈로 확대하는 게 아니라 찍힌 사진을 늘리는 것이라, 배율이 클수록 흐려진다.

openCV-with-Zoom 과 다른 점
  - 배율은 2.0 = 2배 (openCV-with-Zoom 은 scale 0.5 = 2배)
  - 가로세로 비율을 항상 원본과 같게 잘라서 사진이 찌그러지지 않음
  - 확대 위치는 항상 화면 정가운데 (물건을 가운데에 놓고 찍는 기준)

[사용 예]
    from capture_module.utils.zoom import zoom
    zoomed = zoom(frame, 2.0)   # 가운데를 2배 확대
"""

import cv2


def zoom(frame, scale):
    """frame 의 가운데를 scale 배 확대한 사진을 돌려준다 (크기는 원본과 같음).

    scale : 확대 배율 (1.0 이하면 원본 그대로)
    """
    if scale <= 1.0: # 확대 안하면 원본 그대로
        return frame

    # 원본 크기 (높이, 폭, 색 3개)
    height, width = frame.shape[:2]

    # 잘라낼 크기 계산(원본 / 배율)
    crop_w = round(width / scale) # 잘라낼 폭 (원본과 같은 비율)
    crop_h = round(height / scale) # 잘라낼 높이

    # (x1, y1) = 잘라낼 사각형의 왼쪽 위 꼭짓점
    # 남는 여백(원본 - 잘라낼 크기)을 양쪽에 반씩 나눠 주면 사각형이 정가운데에 옴
    x1 = (width - crop_w) // 2 # 예) (1280 - 640) // 2 = 320
    y1 = (height - crop_h) // 2 # 예) (1024 - 512) // 2 = 256

    # 자르기 [세로 범위, 가로 범위] / 끝 숫자 포함x
    cropped = frame[y1:y1 + crop_h, x1:x1 + crop_w]

    # 원래 크기로 늘리기
    # resize(폭, 높이) 순서 / INTER_LINEAR : 늘릴 때 빈칸을 주변 점의 색을 섞어서 채움 (부드럽지만 약간 흐려짐)
    return cv2.resize(cropped, (width, height), interpolation=cv2.INTER_LINEAR)
