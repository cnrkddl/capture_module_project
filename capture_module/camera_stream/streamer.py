# StreamServer: WebSocket 송출, 느린 클라이언트 건너뛰기(백프레셔)
"""camera_stream/streamer.py - 카메라 프레임을 JPEG로 압축해 WebSocket으로 송출한다.

- camera.py가 만드는 raw 프레임(Frame.image, BGR/uint8)을 받아 여기서 JPEG로 압축한다.
  압축률(jpeg_quality)과 리사이즈, 출력 fps 제한도 전부 이 파일(전송 계층)의 책임이다.
- 프레임은 push_frame(frame)으로 받는다 (연결은 __init__.py가 camera.on_frame에 이어 준다).
  camera.py를 모르고, 깨어날 때마다 최신 프레임 하나만 압축해서 보낸다 (중간에 여러 장 와도 최신 것만 처리).
- 클라이언트별로 송신 버퍼가 밀리면 그 클라이언트만 이번 프레임을 건너뛴다(백프레셔).
- 수신(ack) 처리는 receive_excluded.py로 분리했다. 송신 버퍼 검사만 쓰므로, 느린 클라이언트는
  OS 소켓 버퍼(실측 약 9MB)에 쌓인 프레임 때문에 3~5초 전 영상을 받을 수 있다.
"""
import asyncio
from collections import deque
import logging
import threading
import time

import cv2
import websockets

from .schema import CRC_OFFSET, Frame, StreamSettings, frame_crc32, pack_header

log = logging.getLogger("camera_stream.streamer")


# 클라이언트별 상태(건너뜀, 보낸 장수 등)를 따로 관리해서 속성 개수 제한을 넘는다
class StreamServer:  # pylint: disable=too-many-instance-attributes
    """push_frame으로 받은 raw 프레임을 JPEG로 압축해, 접속한 모든 클라이언트에게 WebSocket으로 송출한다."""

    # 헤더 규격(포맷/크기/pack 함수)은 schema.py에 정의돼 있고, 받는 쪽도 같은 것을 import해서 쓴다.

    # 카메라 객체는 받지 않는다. 프레임은 push_frame으로만 받는다
    def __init__(self, settings: StreamSettings | None = None):
        self.settings = settings or StreamSettings()
        self._loop: asyncio.AbstractEventLoop | None = None  # 객체 생성시에는 none 
        # 압축이 끝난 메시지를 만드는 대로 쌓는 버퍼. 가득 차면 가장 오래된 것이 밀려난다 (메모리가 끝없이 늘지 않게).
        # 카메라 스레드(push_frame)와 메인 스레드(_broadcast_loop)가 같이 쓰는 값이라 락을 건다.
        self._buffer: deque[bytes] = deque(maxlen=120)   # 60fps 기준 약 2초 분량
        self._buffer_lock = threading.Lock()
        self.dropped_frames = 0                          # 버퍼가 가득 차서 밀려난 장수
        # 아래 dict들은 "접속한 클라이언트(ServerConnection) -> 장수(int)" 모양이다
        self.clients: set[websockets.ServerConnection] = set()
        # 클라이언트별 건너뛴 프레임 수 (누적)
        self.skipped: dict[websockets.ServerConnection, int] = {}
        # 클라이언트별 실제로 보낸 장수
        self.client_sent: dict[websockets.ServerConnection, int] = {}
        self.sent_frames = 0
        self.sent_bytes = 0
        self._frame_ready = asyncio.Event()
        self._last_sent_monotonic = 0.0  # output_fps 스로틀링 기준 시각
        self._server: websockets.Server | None = None
        self._tasks: list[asyncio.Task] = []

    def push_frame(self, frame: Frame):
        """카메라 스레드에서 불린다. 압축까지 여기서 하고 끝난 메시지를 보관한 뒤 메인 스레드에 알린다."""
        loop = self._loop

        if loop is None or not self.clients:  # 서버 꺼짐 또는 접속자 없음 -> 압축도 생략
            return

        if not self._should_send_now():  # output_fps 제한에 걸리면 이번 프레임은 건너뜀
            return

        try:
            message = self._encode(frame)  # 리사이즈, JPEG 압축, 헤더·CRC

        # 여기서 예외가 밖으로 나가면 카메라가 재연결되므로, 이 프레임만 건너뛴다
        except Exception as error:  # pylint: disable=broad-exception-caught
            log.error("프레임 인코딩 실패, 이번 프레임 건너뜀: %s", error)
            return

        with self._buffer_lock:
            if len(self._buffer) == self._buffer.maxlen:   # 가득 찼으면 가장 오래된 것이 밀려난다
                self.dropped_frames += 1
            self._buffer.append(message)                   # 새 메시지를 끝에 추가

        try:
            loop.call_soon_threadsafe(self._frame_ready.set)  # 메인 스레드에 알림

        except RuntimeError:  # 종료 중 이벤트 루프가 이미 닫힌 경우
            pass


    async def _handler(self, websocket: websockets.ServerConnection): #클라이언트의 접속부터 종료까지 관리 .
        self.clients.add(websocket)
        self.client_sent[websocket] = 0
        log.info("클라이언트 접속: %s (총 %d명)", websocket.remote_address, len(self.clients))

        try:
            # 수신 내용은 처리하지 않는다 (receive_excluded.py로 분리). 연결 유지와 받은 메시지 비우기만 한다.
            async for _ in websocket:
                pass

        except websockets.ConnectionClosed:
            pass

        finally: #끊기면 다시 실행 
            self.clients.discard(websocket)
            skipped = self.skipped.pop(websocket, 0)
            sent = self.client_sent.pop(websocket, 0) #pop은 꺼내서 센다.

            # 끊길 때 이 클라이언트에게 보낸 장수를 남겨 받는 쪽 수신 장수와 바로 비교할 수 있게 한다.
            log.info(
                "클라이언트 종료: %s (총 %d명) | 보낸 %d장, 스킵 %d장",
                websocket.remote_address, len(self.clients), sent, skipped,
            )

    def _encode(self, frame: Frame) -> bytes:
        """raw 프레임을 (필요하면 리사이즈하고) JPEG로 압축한 뒤 헤더 36바이트를 붙인다."""
        image = frame.image
        width, height = frame.width, frame.height

        if self.settings.resize_width and self.settings.resize_height:
            image = cv2.resize(image, (self.settings.resize_width, self.settings.resize_height))
            width, height = self.settings.resize_width, self.settings.resize_height

        ok, buffer = cv2.imencode(
            ".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, self.settings.jpeg_quality]
        )

        if not ok:
            raise ValueError("JPEG 인코딩 실패")

        jpeg_bytes = buffer.tobytes()

        sent_at = time.time()  # 송출 시각
        # CRC 칸을 0으로 채운 헤더를 먼저 만들어 앞 32바이트(프레임 번호·시각·가로·세로)만 떼어 낸다.
        head = pack_header(frame.frame_no, frame.timestamp, sent_at, width, height, 0)
        head = head[:CRC_OFFSET]
        # 그 32바이트와 JPEG를 이어서 CRC를 계산해 헤더에 넣는다.
        # 헤더가 바뀌어도 받는 쪽 CRC가 달라져서 잡힌다.
        crc = frame_crc32(head, jpeg_bytes)
        header = pack_header(frame.frame_no, frame.timestamp, sent_at, width, height, crc)
        return header + jpeg_bytes

    def _select_targets(self, message_size: int) -> list[websockets.ServerConnection]:
        """송신 버퍼가 밀린 클라이언트는 이번 프레임을 건너뛴다 (느린 클라이언트 때문에 지연이 쌓이지 않게).

        ws.transport는 websockets 라이브러리의 공개 API가 아니라 내부 구현 세부사항이다.
        버전이 바뀌면 이름/구조가 바뀌어 깨질 수 있으니 requirements.txt에 websockets==17.1로
        정확히 고정해뒀다. 라이브러리 버전을 올릴 일이 생기면 이 부분부터 다시 확인해야 한다.
        """
        limit = message_size * self.settings.skip_frames #기준...
        targets = [] 

        #예외처리할 때 만든건가..검토 fb 
        for ws in self.clients: 
            buffer_full = ws.transport.get_write_buffer_size() >= limit#서버 송신하는 버퍼가 꽉 찼나

            if buffer_full:
                self.skipped[ws] = self.skipped.get(ws, 0) + 1 
            else:
                targets.append(ws)

        return targets

    def _should_send_now(self) -> bool:
        """output_fps가 지정돼 있으면, 목표 주기보다 일찍 온 프레임은 건너뛴다. None이면 항상 즉시 송출."""
        if self.settings.output_fps is None:
            return True

        min_interval = 1.0 / self.settings.output_fps
        now = time.monotonic()

        if now - self._last_sent_monotonic < min_interval:
            return False

        self._last_sent_monotonic = now
        return True

    async def _broadcast_loop(self): #메인스레드 쌓인 메시지를 순서대로 꺼내 대상 선택, 전송 (압축은 push_frame에서 끝났다)
        while True: #끝나지않음

            await self._frame_ready.wait()  # 신호가 올 때까지 대기 (카메라 스레드가 알려주면 이어서 실행)
            self._frame_ready.clear() #다음 신호도 올테니 다시 꺼둠

            while True:  # 쌓인 메시지를 다 꺼낼 때까지 반복
                with self._buffer_lock: #두 스레드 동시 접근 방지
                    if not self._buffer:  # 비었으면 이번 처리 끝
                        break

                    message = self._buffer.popleft()  # 가장 오래된 것부터 하나씩 꺼냄

                if not self.clients:
                    continue

                targets = self._select_targets(len(message)) #메시지 크기 넘겨줄것. 보낼 대상 고르기
                websockets.broadcast(targets, message)  # 대상들에게 메시지 전송

                for ws in targets:
                    if ws in self.client_sent:
                        self.client_sent[ws] += 1  # 클라이언트에게 실제로 보낸 장수.

                self.sent_frames += 1
                self.sent_bytes += len(message) * len(targets)  # 헤더 포함 전체 크기로 집계

    async def _status_loop(self):
        # 카메라 상태가 들어간 "상태 | ..." 한 줄은 카메라와 서버를 둘 다 아는 __init__.py로 옮긴다.
        # 여기는 송출 쪽 경고(느린 클라이언트)만 남는다.
        prev_skipped: dict[websockets.ServerConnection, int] = {}

        while True:#에이싱크 안에 또 에이싱크. 
            await asyncio.sleep(1) #timesleep 사용하면 await가 적용되지않아 실행시간줄일수없음 

            for ws, count in list(self.skipped.items()):
                skipped_now = count - prev_skipped.get(ws, 0)

                if skipped_now:
                    log.warning(
                        "느린 클라이언트 %s | 건너뜀 %d장/초 (누적 %d장) | 송신 버퍼 %.0fKB",
                        ws.remote_address,
                        skipped_now,
                        count,
                        ws.transport.get_write_buffer_size() / 1000,
                    )

            prev_skipped = dict(self.skipped)

    async def start(self):
        """서버를 띄우고 백그라운드 태스크로 돌린 뒤 바로 리턴한다 (오케스트레이터의 이벤트 루프 안에서 호출).

        asyncio.run()을 쓰지 않아서, CameraStream과 같은 이벤트 루프 안에서
        await로 호출할 수 있다. 끝나면 stop()으로 정리해야 한다.
        """
        self._loop = asyncio.get_running_loop()  #지금 돌고있는 이벤트 루프를 저장.push_frame(카메라 스레드)이 이 루프에 신호를 보낼 때 쓴다.

        # compression=None: websockets가 기본으로 켜는 permessage-deflate(zlib)를 끈다.
        # JPEG는 이미 압축된 데이터라 다시 압축해도 크기는 거의 안 줄고,
        # 그 작업이 이벤트 루프의 CPU 시간만 쓰기 때문이다.
        self._server = await websockets.serve(# 서버(포트)열고 접속하면 핸들러 실행 
            self._handler, self.settings.host, self.settings.port, compression=None
        )

        log.info("stream 서버 시작: ws://%s:%d", self.settings.host, self.settings.port)

        self._tasks = [
            asyncio.create_task(self._broadcast_loop(), name="stream-broadcast"),#백그라운드 테스크 두 개 실행 
            asyncio.create_task(self._status_loop(), name="stream-status"),
        ]

    async def stop(self):
        """start()로 띄운 서버와 백그라운드 태스크를 정리한다."""
        self._loop = None  #  카메라 등록 해제 대신: 이후 push_frame은 보관/알림 모두 생략

        for task in self._tasks:
            task.cancel()

        for task in self._tasks:
            try:
                await task

            except asyncio.CancelledError:
                pass

        self._tasks = []

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
