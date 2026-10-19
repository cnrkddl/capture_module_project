# 장희정 - CameraStream: 카메라와 송출 서버를 묶어 시작/종료/상태를 관리하는 오케스트레이터
"""camera_stream/stream.py - 모듈 전체를 켜고 끄는 진입점.

- 여기서 start를 부름 (카메라.py를)
- camera와 streamer는 서로를 모른다. 둘을 잇는 건 이 파일의 한 줄뿐이다: camera.on_frame = server.push_frame
- 카메라와 송출 상태를 함께 찍는 1초 상태 로그도 둘을 다 아는 이 파일이 맡는다.
- 종료는 시작의 역순으로: 상태 로그 정지 -> 서버 정지 -> 카메라 정지.
"""
import asyncio
import logging

from .camera import CameraSource
from .config import load_config
from .schema import AppConfig
from .streamer import StreamServer

log = logging.getLogger("camera_stream")


class CameraStream:
    """카메라 수집과 WebSocket 송출을 함께 시작하고 종료한다."""

    def __init__(self, config: AppConfig | None = None): #객체생성 . 
        self.config = config or load_config() #설정을 읽음 
        self.camera = CameraSource(self.config.camera) #객체만듦. 만들어지는순간 카메라.py의 __init__()가 실행된다.
        self.server = StreamServer(self.config.stream)#값만 준비할 뿐, 카메라연결과 서버여는 것은 아직. 
        self.camera.on_frame = self.server.push_frame  #카메라가 프레임 받으면 push_frmae이 불림 
        self._shutdown = asyncio.Event()  # stop()이 불리면 run()이 깨어나 종료 절차를 밟는다
        self._status_task: asyncio.Task | None = None

    async def start(self):
        """카메라와 송출 서버를 시작한다. async 함수 안에서 호출해야 한다(실행 중인 루프가 필요)."""
        self.camera.start()
        await self.server.start()
        self._status_task = asyncio.create_task(self._status_loop(), name="camera-stream-status")
        log.info("카메라 시작, 송출 서버 시작")

    async def stop(self):
        """시작의 역순으로 정리한다."""
        self._shutdown.set()

        if self._status_task is not None:
            self._status_task.cancel()

            try:
                await self._status_task

            except asyncio.CancelledError:
                pass

            self._status_task = None

        try:
            await self.server.stop()

        # 서버 정리가 어떤 이유로 실패하든 카메라는 반드시 닫아야 해서 일부러 넓게 잡는다
        except Exception as error:  # pylint: disable=broad-exception-caught
            log.error("송출 서버 종료 중 오류: %s", error)

        # camera.stop()은 수집 스레드가 끝날 때까지 기다리는 동기 함수라
        # 그냥 부르면 그동안 이벤트 루프가 멈춘다
        await asyncio.to_thread(self.camera.stop)
        log.info("카메라 종료, 송출 서버 종료")

    async def _status_loop(self):
        """1초마다 카메라와 송출 상태를 한 줄로 찍는다. (예전엔 streamer.py가 카메라 값을 빌려 찍었음)"""
        prev_captured = 0
        prev_sent = 0

        while True:
            await asyncio.sleep(1)
            captured = self.camera.frame_count
            sent = self.server.sent_frames

            log.info(
                "상태 | 카메라=%s | 수집 %dfps | 송출(send) %dfps 누적 %.1fMB | 클라이언트 %d명",
                "연결" if self.camera.connected else "끊김",
                captured - prev_captured,
                sent - prev_sent,
                self.server.sent_bytes / 1_000_000,
                len(self.server.clients),
            )

            prev_captured, prev_sent = captured, sent

    def status(self) -> dict[str, int | bool]:
        """현재 상태 요약. 로그나 상태 출력에 사용한다."""
        return {
            "connected": self.camera.connected,
            "frame_count": self.camera.frame_count,
            "clients": len(self.server.clients),
            "sent_frames": self.server.sent_frames,
        }

    async def run(self):
        """시작한 뒤 종료 신호(stop() 또는 Ctrl+C)가 올 때까지 돌린다."""
        await self.start()

        try:
            await self._shutdown.wait()

        finally:
            await self.stop()