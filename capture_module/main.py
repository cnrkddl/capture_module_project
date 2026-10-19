"""캡쳐 모듈을 브라우저로 확인하는 테스트용 웹서버 (모듈 자체에는 필요 없음).

[하는 일]
  1. Basler 카메라를 켜고, 뒤에서 계속 최신 장면을 읽게 한다.
  2. 웹서버를 켜서 브라우저 요청을 기다린다.
  3. 브라우저에 화면과 영상을 보내 주고,
     캡쳐 버튼이 눌리면 streamer.capture() 로 캡쳐 → 저장 → 분류 → 결과 기록 → JSON 응답까지 처리한다.

  main.py는 직접 일하기보다 각 파일에 순서대로 일을 시키는 역할.
    streamer.py              Basler 카메라 영상 읽기 (최신 장면 보관) + capture()
    process.py               사진 한 장 → 저장 → 분류 → 결과 기록 (CaptureProcessor)
    classifier.py            분류 (학습된 YOLOv8n-cls 모델)
    config.py                설정값 (카메라, 모델 경로, 저장 경로, 화질, 포트 등)
    camera/
      camera_source.py       카메라 틀 (isOpened / read / release)
      basler_source.py       Basler 카메라 연결, 설정, 재연결
    utils/
      capture.py             이미지 저장 + 파일명 규칙 (cap_날짜_시간_순번.jpg)
      schema.py              결과 JSON 형식
      zoom.py                디지털 줌

[실행]
  capture-server                          패키지 설치 후 (기본 모델, 5000번 포트)
  capture-server --model D:/new.pt        다른 모델로 실행
  capture-server --port 8000              다른 포트로 실행
  capture-server --no-browser             브라우저 자동으로 안 열기
  python -m capture_module.main           설치 없이 프로젝트 폴더에서 실행
"""

import argparse
import socket
import sys
import threading
import time
import webbrowser

import cv2
from flask import Flask, Response, render_template

from . import config
from .streamer import Streamer

app = Flask(__name__)

camera = None

# 서버에 있는 카메라 영상을 사람이 브라우저에서 직접 볼 수 있도럭 보여주는 함수
def generate_stream():
    # 사진 한장 보낸 뒤에 몇 초 쉴지 간격 설정
    interval = 1.0 / config.STREAM_FPS
    params = [cv2.IMWRITE_JPEG_QUALITY, config.STREAM_JPEG_QUALITY] # jpg로 압축할 때 옵션 -> config
  
    while camera.is_running(): # 카메라가 돌고 있는 동안 반복
        frame = camera.get_frame() # 최근 장면을 가져옴
        if frame is not None: 
            ok, buf = cv2.imencode(".jpg", frame, params) #imencode -> jpg로 압축
            if ok: # 압축에 성공하면
                # 브라우저로 사진 전송
                yield (b"--frame\r\n" # 여기부터 새 사진
                       b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n") #buf.tobytes() : imencode로 압축한 결과라서 보낼 수 있는 바이트로 바꿈
                        
        time.sleep(interval)

# 첫 화면
@app.route("/")
def index(): # /로 들어오면 함수 실행
    return render_template("viewer.html")

# 영상을 끝 없이 보내주는 
@app.route("/video_feed") 
def video_feed():
    return Response(generate_stream(), # generate_stream() : 사진 끝없이 yield
                    mimetype="multipart/x-mixed-replace; boundary=frame") # mimetype : 응답 형식 표시 - 브라우저한테 지금부터 보내는 응답이 어떤 종류인지알려준ㅁ

# 캡처를 웹에 요청
@app.route("/capture", methods=["POST"]) # post 요청이 오면
def capture_api(): # 웹 요청 창구 (실제 캡쳐는 Streamer.capture() 가 함)
    result = camera.capture()
    # 프레임이 아직 없으면 503(잠깐 처리 불가) → 브라우저(viewer.html)가 상태 코드를 보고 실패로 표시
    if result is None:
        # 503 : http 상태 코드 -> 응답 내용 밖에 따로 둬야함 / 서버가 브라우저한테 응답할 때 쓰는
        # 브라우저인 viewer.html이 이 상태 코드를 통해 캡쳐 성공, 실패를 판단함
        # 상태코드로 실패를 알리는게 웹 표준 방식
        return {"error": "아직 프레임이 없습니다."}, 503
    return result


# 서버가 켜질 때까지 기다렸다가 브라우저로 웹 화면을 여는 함수
def open_browser_when_ready(port):
    url = f"http://127.0.0.1:{port}" # 0.0.0.0은 접속 받는 주소라 브라우저로는 못 열어서 내 컴퓨터 주소(127.0.0.1)로 엶
    for _ in range(100): # 최대 10초 기다림 (0.1초 x 100번)
        try:
            # 포트에 연결이 되면 서버가 켜진 것
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                webbrowser.open(url) # 기본 브라우저로 열기
                return
        except OSError: # 아직 서버가 안 켜짐
            time.sleep(0.1)


def main():
    global camera

    # 실행할 때 옵션 받기 (안 넘기면 config 값)
    parser = argparse.ArgumentParser(description="캡쳐 모듈 웹 화면 서버")
    parser.add_argument("--model", default=config.MODEL_PATH, help="분류 모델 .pt 경로 (기본: 패키지 안 모델)")
    parser.add_argument("--host", default=config.HOST, help="접속 받을 주소 (기본: %(default)s)")
    parser.add_argument("--port", type=int, default=config.PORT, help="포트 번호 (기본: %(default)s)")
    parser.add_argument("--no-browser", action="store_true", help="브라우저 자동으로 안 열기")
    args = parser.parse_args()

    # streamer 만들고 시작
    # streamer() : 모델 불러오기, 카메라 연결,설정,촬영 시작
    # .start() : 백그라운드에서 프레임 받기 시작
    # 실패하면 긴 에러(Traceback) 대신 이유만 한 줄 출력하고 종료 (카메라가 아직 안 열렸으니 닫을 필요 없음)
    try:
        camera = Streamer(model_path=args.model).start()
        camera.start_stream() # WebSocket 송출 서버 켜기 (같은 카메라 프레임을 8765번 포트로 송출)
    except FileNotFoundError as error: # 모델 파일이 없을 때
        print(f"[오류] {error}")
        sys.exit(1) # 1 : 비정상 종료라는 표시
    except RuntimeError as error: # 카메라를 못 열 때 (연결 안 됨 / 다른 프로그램이 사용 중)
        print(f"[오류] {error}")
        sys.exit(1)

    # 브라우저 자동 열기 (app.run()은 서버가 꺼질 때까지 안 끝나서 따로 스레드로 돌림)
    # daemon=True : 프로그램이 끝나면 이 스레드도 같이 끝남
    if not args.no_browser:
        threading.Thread(target=open_browser_when_ready, args=(args.port,), daemon=True).start()

    try: # 웹서버 실행, 서버 꺼질 때까지
        # threaded=True : 요청을 동시에 여러개 처리
        # use_reloader=False : 켜면 카메라를 두 번 열게 되므로 끔 (코드 고치면 자동 재시작 하는 기능 끔)
        # 포트 충돌 등 서버 시작 오류는 Werkzeug(Flask 내부 서버)가 메시지 출력 후 종료함
        app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)
    finally: # 정상 종료, Ctrl+C, 에러 상관없이 카메라는 꼭 닫음 (안 닫으면 다음 실행 때 카메라를 못 엶)
        camera.stop()


if __name__ == "__main__":
    main()
