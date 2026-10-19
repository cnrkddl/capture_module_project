"""캡쳐 모듈 GUI 창 (웹 브라우저 대신 프로그램 창으로 확인).

[하는 일]
  1. 분류 모델을 불러오고 창을 띄운다. (카메라가 없어도 창은 열림)
  2. PC에 연결된 Basler 카메라를 찾아서 목록에 보여 주고, 찾으면 첫 번째 카메라에 자동으로 연결한다.
     카메라를 나중에 꽂았으면 [새로고침] → [연결], 다른 카메라로 바꾸려면 [해제] → 선택 → [연결].
  3. 창 가운데에 실시간 영상을 보여 준다.
  4. 캡쳐 버튼(또는 Space 키)을 누르면 streamer.capture() 로 캡쳐 → 저장 → 분류 → 결과 기록하고,
     결과를 아래 표 맨 위에 한 줄씩 추가한다.

  main.py (웹)와 하는 일은 같고, 화면만 브라우저 대신 tkinter(파이썬 기본 GUI) 창으로 보여 준다.

[실행]
  capture-gui                             패키지 설치 후 (기본 모델)
  capture-gui --model D:/new.pt           다른 모델로 실행
  python -m capture_module.gui            설치 없이 프로젝트 폴더에서 실행
"""

import argparse
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk

import cv2
from PIL import Image, ImageTk

from . import config
from .camera.basler_source import BaslerSource, list_cameras
from .process import CaptureProcessor
from .streamer import Streamer

NO_CAMERA_TEXT = "카메라가 연결되지 않았습니다."

# ── 색 / 글꼴 (웹 화면 viewer.html 과 같은 어두운 테마) ──
BG = "#1e1e1e"          # 배경
FIELD = "#2d2d2d"       # 목록 칸 / 보조 버튼 배경
FG = "#eeeeee"          # 글자
MUTED = "#aaaaaa"       # 흐린 글자 (안내 / 진행 중 메시지)
LINE = "#333333"        # 표 테두리
ACCENT = "#2d7ff9"      # 캡쳐 버튼 (파랑)
DISABLED = "#555555"    # 잠긴 캡쳐 버튼
OK = "#4cc76a"          # 성공 메시지 (초록)
ERROR = "#ff6b6b"       # 실패 메시지 (빨강)
FONT = "맑은 고딕"


# 버튼 만들기 (tkinter 기본 버튼은 회색 입체 모양이라 평평하게)
# color : 평소 배경색, disabled_color : 잠겼을 때 배경색
def make_button(parent, text, command, color, disabled_color, font_size, padx, pady):
    button = tk.Button(parent, text=text, command=command, font=(FONT, font_size),
                       bg=color, fg="white", activebackground=color, activeforeground="white",
                       disabledforeground="#888888", relief="flat", bd=0, cursor="hand2",
                       padx=padx, pady=pady,
                       takefocus=False) # takefocus=False : 버튼에 포커스가 가면 Space 키가 버튼도 눌러서 두 번 캡쳐될 수 있어서 끔
    button.colors = (color, disabled_color) # 잠금 / 풀기 할 때 쓸 색 기억
    return button


# 버튼 잠금 / 풀기 (tkinter 버튼은 잠가도 배경색이 안 바뀌어서 직접 바꿈)
def set_enabled(button, enabled):
    color, disabled_color = button.colors
    button.configure(state="normal" if enabled else "disabled", # 버튼
                     bg=color if enabled else disabled_color, # 버튼 색
                     cursor="hand2" if enabled else "arrow") # cursor : 마우스 모양 (hand2 : 손가락)


# 표 / 목록 칸 색 바꾸기 (ttk 위젯은 색을 Style 로 정함)
def setup_style(root):
    root.configure(bg=BG) # 창 자체의 배경색
    style = ttk.Style(root) # ttk 위젯의 스타일 관리자
    style.theme_use("clam") # 색 바꾸기 쉬운 clam 테마 사용

    # 결과 표
    style.configure("Treeview", background=BG, fieldbackground=BG, foreground=FG, font=(FONT, 10),
                    rowheight=30, borderwidth=1, bordercolor=LINE, lightcolor=BG, darkcolor=BG)
    # style.map : 상태에 따라 달라지는 모양 정함
    style.map("Treeview", background=[("selected", "#2a3f63")], foreground=[("selected", FG)]) # 고른 줄

    # 표 제목 줄
    style.configure("Treeview.Heading", background=BG, foreground=MUTED, font=(FONT, 10, "bold"),
                    relief="flat", borderwidth=0, padding=(6, 6))
    style.map("Treeview.Heading", background=[("active", BG)]) # active = 마우스가 올라간 상태 -> BG로 색 안바뀌게

    # 카메라 목록 칸
    style.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=FG,
                    arrowcolor=FG, bordercolor=FIELD, lightcolor=FIELD, darkcolor=FIELD, padding=4) # arrowcolor 화살표 색
    style.map("TCombobox",
              fieldbackground=[("readonly", FIELD), ("disabled", FIELD)], # 읽기 전용/ 잠김일때 같은 배경
              foreground=[("disabled", "#777777"), ("readonly", FG)], # 잡겼으면 흐린 글자
              arrowcolor=[("disabled", "#777777")],
              selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", FG)])
    
    # 목록 칸을 눌렀을 때 펼쳐지는 목록 색
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT) # 펼친 목록에서 마우스 올린 항목 파랑색으로
    root.option_add("*TCombobox*Listbox.selectForeground", "white")
    root.option_add("*TCombobox*Listbox.font", f"{{{FONT}}} 10")


class CaptureApp:
    """카메라 선택 + 실시간 영상 + 캡쳐 버튼 + 결과 표가 있는 창."""

    def __init__(self, root, processor):
        """
        root      : tkinter 창 (tk.Tk())
        processor : 미리 만들어 둔 CaptureProcessor (모델은 창 띄우기 전에 한 번만 불러 둠)
        """
        self.root = root # tk.TK()창 / 다른 메서드에서도 쓸 수 있도록 저장
        self.processor = processor # main에서 만든 captureprocesser (모델)
        self.camera = None # 연결된 Streamer 
        self.cameras = [] # 찾은 카메라 목록 (시리얼 번호, 모델 이름)...
        self.camera_working = False # 카메라 찾기 / 연결 / 해제 중이면 True (버튼 잠금)
        self.auto_connect = True # 처음 한 번만: 카메라를 찾으면 바로 연결
        self.busy = False # 캡쳐 중이면 True (중복 캡쳐 방지)
        self.jobs = queue.Queue() # 작업 스레드에서 메인 스레드로 결과 전달
        self.photo = None # 화면에 띄운 영상 이미지 

        root.title("캡쳐 모듈") # 창 제목 표시줄 글자
        root.geometry("960x780") # 처음 창 크기 (가로x세로)
        setup_style(root) # 어두운 테마 색 적용

        # ── 카메라 선택 줄 ──
        top = tk.Frame(root, bg=BG)
        top.pack(fill="x", padx=16, pady=(16, 0))# padx/pady : 바깥여백
        tk.Label(top, text="카메라", font=(FONT, 11), bg=BG, fg=MUTED).pack(side="left")
        # readonly : 목록에서 고르기만 하고 글자를 직접 쓰지는 못하게
        self.camera_box = ttk.Combobox(top, state="readonly", width=36, font=(FONT, 11)) # 글자 36개 들어가는 너비

        # 새로고침 버튼
        self.camera_box.pack(side="left", padx=8)
        self.refresh_button = make_button(top, "새로고침", self.refresh_cameras,
                                          FIELD, FIELD, font_size=10, padx=14, pady=4)
        # 연결 버튼
        self.refresh_button.pack(side="left")
        self.connect_button = make_button(top, "연결", self.toggle_connect,
                                          FIELD, FIELD, font_size=10, padx=14, pady=4)
        self.connect_button.pack(side="left", padx=6)

        # ── 영상 영역 ──
        # tkinter 상자는 안에 든 것 크기에 맞춰서 크기를 바꿈
        self.video_box = tk.Frame(root, bg="black") # 검은 상자 만듦 -> 영상 비율이 상자와 다르면 검은 여백으로 보이게
        self.video_box.pack(fill="both", expand=True, padx=16, pady=(12, 0)) # pack : 위젯을 위에서부터 차례로 쌓음
        self.video_box.pack_propagate(False) # pack_propagate(False) : 안에 든 영상 크기에 맞춰 영역이 커지지 않게 고정

        # 영상 넣을 칸 
        self.video_label = tk.Label(self.video_box, bg="black", fg=MUTED, font=(FONT, 14),
                                    text=NO_CAMERA_TEXT) # .Label : image 있으면 이미지, 없으면 text 보여줌
        self.video_label.place(relx=0.5, rely=0.5, anchor="center") # .place : 좌표로 배치하는 방법 / anchor="center" : 칸을 상자 가운데에 놓기

        # ── 버튼 + 상태 메시지 ──
        bar = tk.Frame(root, bg=BG)
        bar.pack(fill="x", padx=16, pady=12)

        # 버튼
        self.button = make_button(bar, "캡쳐 (Space)", self.capture,
                                  ACCENT, DISABLED, font_size=14, padx=24, pady=8) # 파랑 / 회색
        self.button.pack(side="left")

        # 상태
        self.status = tk.Label(bar, text="", font=(FONT, 11), bg=BG, fg=MUTED) # 처음엔 빈 글자
        self.status.pack(side="left", padx=14)

        # ── 결과 표 ──
        columns = ("time", "image", "class", "confidence") # 열
        self.table = ttk.Treeview(root, columns=columns, show="headings", height=7)

        for name, title, width in [("time", "캡쳐 시각", 120), ("image", "파일명", 320), # 숫자는 각 열의 너비
                                   ("class", "분류 결과", 160), ("confidence", "확률", 100)]:
            self.table.heading(name, text=title, anchor="w") # 제목줄 글자 / anchor='w' : 왼쪽 정렬
            self.table.column(name, width=width, anchor="w") # 열 너비, 칸 글자 왼쪽 정렬
        # anchor은 지도 방위 : n, s, e, w, center    
        self.table.pack(fill="x", padx=16, pady=(0, 16))

        # bind(이벤트, 함수) : 이벤트가 생기면 함수 실행
        root.bind("<space>", lambda event: self.capture()) # Space 키 -> 캡쳐

        self.update_controls() # 처음 버튼 상태 맞추기 (카메라 없음 -> 캡쳐 잠금)
        self.update_video()   # 영상 그리기 반복 시작
        self.check_jobs()     # 스레드 작업 결과 확인 시작 (이후 스스로 반복)
        self.refresh_cameras() # 카메라 찾기 시작 -> 찾으면 자동 연결

    # 지금 상태에 맞게 버튼을 잠그거나 풀기
    def update_controls(self):
        connected = self.camera is not None # 카메라 연결되어 있는지
        # 연결 중에는 카메라를 못 바꾸게 목록 / 새로고침 잠금 (바꾸려면 먼저 해제)
        locked = connected or self.camera_working
        self.camera_box.configure(state="disabled" if locked else "readonly") # 목록 칸 잠금/풀기
        set_enabled(self.refresh_button, not locked) #새로 고침 
        self.connect_button.configure(text="해제" if connected else "연결") # 버튼 글자 바꾸기(연결 되어 있으면 해제)
        set_enabled(self.connect_button, not self.camera_working and (connected or bool(self.cameras)))
        set_enabled(self.button, connected and not self.busy) # 캡쳐 버튼

    # 최신 장면을 창 크기에 맞게 줄여서 화면에 표시, STREAM_FPS 마다 반복
    def update_video(self):
        frame = self.camera.get_frame() if self.camera else None # 카메라 연결 되어 있면 최신 프레임의 복사본(BGR) 받음
        box_w, box_h = self.video_box.winfo_width(), self.video_box.winfo_height() # 영상 상자의 지금 실제 크기

        if frame is not None and box_w > 1 and box_h > 1: # 창이 아직 안 그려졌으면 크기가 1이라 건너뜀
            h, w = frame.shape[:2] # 넘파이 배열 모양 (높이, 너비, 3) 중 앞의 두개
            scale = min(box_w / w, box_h / h) # 비율 유지한 채 영역 안에 들어가는 배율
            frame = cv2.resize(frame, (max(1, int(w * scale)), max(1, int(h * scale)))) # (너비, 높이)로 줄임
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) # OpenCV(BGR) -> 화면용(RGB) 변환
            self.photo = ImageTk.PhotoImage(Image.fromarray(frame)) # 넘파이 -> PIL 이미지 -> tkinter이미지
            self.video_label.configure(image=self.photo) # label에 표시(글자 대신 이미지)

        # after(ms, 함수) : 정해진 시간(ms) 뒤에 함수 다시 실행하도록 예약 (멈추지 않고 반복하는 tkinter 방식)
        self.root.after(int(1000 / config.STREAM_FPS), self.update_video)

    # 오래 걸릴 수 있는 일(func)을 따로 스레드로 돌리고, 결과를 (작업 이름, "ok"/"error", 값) 으로 큐에 넣음
    # 화면은 check_jobs() 가 메인 스레드에서 바꿈 (tkinter 화면은 메인 스레드에서만 바꿔야 함)
    def run_in_thread(self, job, func, *args):
        def worker():
            try:
                self.jobs.put((job, "ok", func(*args))) # 성공 (이름표, ok, 결과값)을 큐에 넣음
            except Exception as error:
                self.jobs.put((job, "error", error)) # 실패 : (이름표, error, 예외 객체)
        threading.Thread(target=worker, daemon=True).start()

    # ── 카메라 ──

    # [새로고침] 버튼 : PC에 연결된 카메라 찾기 (GigE 카메라는 찾는 데 몇 초 걸릴 수 있어서 스레드로)
    def refresh_cameras(self):
        self.camera_working = True # 카메라 작업중 표시
        self.update_controls() # 버튼 잠금
        self.status.configure(text="카메라 찾는 중...", fg=MUTED) # 진행 상황 안내
        self.run_in_thread("find", list_cameras) # 작업 스레드 list_cameras 실행

    # [연결] / [해제] 버튼 (연결돼 있으면 해제, 아니면 고른 카메라에 연결)
    def toggle_connect(self):
        if self.camera is not None: # 연결 되어 있으면
            self.disconnect() # 해제 역할
            return # 실행 없이 넘어감
        index = self.camera_box.current() # 목록에서 고른 번호 (안 골랐으면 -1)
        if index < 0: # 아무것도 안골라씅면 
            return # 실행 없이 넘어감
        serial, _ = self.cameras[index] # (시리얼번호, 모델명) 에서 시리얼 번호만 꺼냄 / _ : 이 값(모델명) 안 쓴다는 뜻 

        self.camera_working = True
        self.update_controls()
        self.status.configure(text="카메라 연결 중...", fg=MUTED)
        self.run_in_thread("connect", self.open_camera, serial)

    # (작업 스레드) 카메라 연결 + 프레임 받기 시작. 못 열면 Streamer 가 RuntimeError
    def open_camera(self, serial):
        camera = BaslerSource(serial_number=serial) # 노출 / FPS 등 나머지 설정은 config.py 값
        return Streamer(camera=camera, processor=self.processor).start() # 모델은 이미 불러 둔 것 사용

    # [해제]: 영상 받기 멈추고 카메라 닫기
    def disconnect(self):
        camera, self.camera = self.camera, None # 먼저 None 으로 바꿔서 화면 갱신이 카메라를 안 쓰게
        self.photo = None
        self.video_label.configure(image="", text=NO_CAMERA_TEXT)

        self.camera_working = True
        self.update_controls()
        self.status.configure(text="카메라 연결 해제 중...", fg=MUTED)
        self.run_in_thread("disconnect", camera.stop)

    # 창을 닫을 때 카메라 닫기
    def close(self):
        if self.camera is not None: # 연결 되어 있을때만
            self.camera.stop() # 바로 닫음
            self.camera = None

    # ── 캡쳐 ──

    # 캡쳐 버튼: 분류에 시간이 걸려도 화면이 멈추지 않게 따로 스레드로 처리
    def capture(self):
        if self.busy or self.camera is None: # 이미 캡쳐 중이거나 카메라가 없으면 무시
            return
        self.busy = True # 캡쳐 중(상태)
        self.update_controls() # 버튼 잠금
        self.status.configure(text="캡쳐 중...", fg=MUTED)
        self.run_in_thread("capture", self.camera.capture)

    # ── 스레드 작업 결과 처리 ──
    # 스레드 작업 결과가 왔는지 50ms마다 확인하고, 왔으면 화면에 반영
    def check_jobs(self):
        try:
            job, kind, value = self.jobs.get_nowait() # 큐에서 하나 꺼냄
        except queue.Empty: # 큐가 비어있음
            pass 
        else: # try에서 예외가 안났을 때만 
            if job == "find":
                self.on_found(kind, value)
            elif job == "connect":
                self.on_connected(kind, value)
            elif job == "disconnect":
                self.camera_working = False
                self.status.configure(text="카메라 연결 해제됨", fg=MUTED)
            elif job == "capture":
                self.on_captured(kind, value)
            self.update_controls()
        self.root.after(50, self.check_jobs)

    # 카메라 찾기 결과 -> 목록 채우기
    def on_found(self, kind, value):
        self.camera_working = False
        if kind == "error": # 찾아 보기 실패
            self.cameras = []
            self.status.configure(text=f"✖ 카메라 찾기 실패: {value}", fg=ERROR)
        else: # 찾기 성공
            self.cameras = value
            self.camera_box["values"] = [f"{model} ({serial})" for serial, model in value] # 목록에 보일 글자 : 모델명(시리얼번호)
            if not value: # 찾아봤는데 0대 찾음
                self.camera_box.set("") # 목록 칸에 남아 있는 글자 지움
                self.status.configure(text="✖ 카메라를 찾지 못했습니다 (연결 확인 후 [새로고침])", fg=ERROR)
            else: # 1대 이상 찾음
                serials = [serial for serial, _ in value]
                # config 에 시리얼 번호를 정해 뒀으면 그 카메라, 아니면 첫 번째 카메라 선택
                self.camera_box.current(serials.index(config.BASLER_SERIAL) # config에 적어둔 시리얼번호가 목록에 있으면
                                        if config.BASLER_SERIAL in serials else 0)
                self.status.configure(text=f"카메라 {len(value)}대 찾음", fg=MUTED)

        if self.auto_connect: # 처음 한 번만 자동 연결    
            self.auto_connect = False
            if self.cameras:
                self.toggle_connect()

    # 카메라 연결 결과
    def on_connected(self, kind, value): # value : open_camera에서 난 예외
        self.camera_working = False
        if kind == "error": # 연결 안 됨 / 다른 프로그램이 사용 중
            self.status.configure(text=f"✖ 카메라 연결 실패: {value}", fg=ERROR)
        else: # 성공
            self.camera = value
            self.status.configure(text="✔ 카메라 연결됨", fg=OK)

    # 캡쳐 결과 -> 표 맨 위에 추가
    def on_captured(self, kind, value):
        self.busy = False 
        if kind == "error": # 오류
            self.status.configure(text=f"✖ 캡쳐 실패: {value}", fg=ERROR)
        elif value is None: # 아직 프레임이 없음 
            self.status.configure(text="✖ 캡쳐 실패: 아직 프레임이 없습니다.", fg=ERROR)
        else: # 성공
            time_text = value["captured_at"].split("T")[1] # 2026-10-01T11:07:07 → 11:07:07
            prob = f"{value['confidence']:.1f}%"           # 65.7 → 65.7%
            self.table.insert("", 0, values=(time_text, value["image"], value["class"], prob)) # 0 : 맨 위에 추가
            self.status.configure(text=f"✔ 캡쳐 저장 완료 · {value['class']}일 확률 {prob}", fg=OK)


def main():
    # 실행할 때 옵션 받기 (안 넘기면 config 값)
    parser = argparse.ArgumentParser(description="캡쳐 모듈 GUI 창")
    parser.add_argument("--model", default=config.MODEL_PATH, help="분류 모델 .pt 경로 (기본: 패키지 안 모델)")
    args = parser.parse_args()

    # 모델은 창을 띄우기 전에 한 번만 불러 둠 (카메라는 창에서 연결)
    # 모델 파일이 없으면 긴 에러(Traceback) 대신 이유만 한 줄 출력하고 종료
    try:
        processor = CaptureProcessor(model_path=args.model)
    except FileNotFoundError as error:
        print(f"[오류] {error}")
        sys.exit(1)

    root = tk.Tk()
    app = CaptureApp(root, processor)
    try: # 창을 닫을 때까지
        root.mainloop()
    finally: # 창 닫기, 에러 상관없이 카메라는 꼭 닫음 (안 닫으면 다음 실행 때 카메라를 못 엶)
        app.close()


if __name__ == "__main__":
    main()
