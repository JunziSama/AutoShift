"""Input ownership and click scheduling, independently testable."""
from enum import Enum
import time

class State(Enum):
    IDLE = "已停止"
    COUNTDOWN = "准备开启"
    RUNNING = "每秒点击中"
    ERROR = "输入失败"
    UNCONFIRMED = "释放未确认"

class Controller:
    CLICK_INTERVAL = 1.0
    PRESS_DURATION = 0.05

    def __init__(self, backend, clock=time.monotonic):
        self.backend, self.clock = backend, clock
        self.target = None
        self.state, self.message = State.IDLE, "请选择目标窗口"
        self.owns_shift = False
        self.deadline = self.started = None
        self.next_click_at = self.release_at = None

    @property
    def is_running(self):
        return self.state is State.RUNNING

    def select(self, target):
        if not self.stop("已停止：目标已变更"):
            return False
        self.target = target
        self.message = "已选择目标；切回目标后按开启热键"
        return True

    def countdown(self):
        if self.is_running or self.owns_shift or not self.target:
            self.message = "请先停止并选择目标窗口"
            return False
        self.deadline = self.clock() + 3
        self.state = State.COUNTDOWN
        self.message = "请在三秒内切回目标窗口"
        return True

    def start(self):
        if self.is_running or self.owns_shift:
            return False
        self.deadline = None
        now = self.clock()
        self.state = State.RUNNING
        self.started = now
        if not self._click(now):
            return False
        self.message = "目标在前台；每秒点击左 Shift，按下 50 毫秒后松开"
        return True

    def _click(self, now):
        if not self.target or not self.backend.is_target_foreground(self.target):
            self.stop("已停止：目标窗口不在前台")
            return False
        if self.backend.shift_is_down():
            self.stop("已停止：请先松开键盘上的 Shift")
            return False
        self.owns_shift = True
        try:
            self.backend.press_shift()
        except Exception as exc:
            self.stop("点击失败：" + str(exc))
            if not self.owns_shift:
                self.state = State.ERROR
            return False
        self.release_at = now + self.PRESS_DURATION
        self.next_click_at = now + self.CLICK_INTERVAL
        return True

    def _release(self):
        try:
            self.backend.release_shift()
        except Exception as exc:
            self.deadline = self.next_click_at = self.release_at = None
            self.state = State.UNCONFIRMED
            self.message = "释放未确认，请按停止热键重试：" + str(exc)
            return False
        self.owns_shift = False
        self.release_at = None
        return True

    def stop(self, reason="已停止"):
        self.deadline = self.next_click_at = self.release_at = None
        if self.owns_shift and not self._release():
            return False
        self.started = None
        self.state, self.message = State.IDLE, reason
        return True

    def toggle(self):
        if self.is_running or self.owns_shift or self.state is State.COUNTDOWN:
            return self.stop()
        return self.start()

    def tick(self):
        now = self.clock()
        if self.is_running:
            if not self.backend.is_target_foreground(self.target):
                self.stop("已停止：目标退出或已切换窗口")
                return
            if self.owns_shift and now >= self.release_at:
                missed_next_click = now >= self.next_click_at
                if not self._release():
                    return
                # A stalled UI must not produce an immediate up/down burst.
                if missed_next_click:
                    self.next_click_at = now + self.CLICK_INTERVAL
            if not self.owns_shift and now >= self.next_click_at:
                self._click(now)
        elif self.state is State.COUNTDOWN and now >= self.deadline:
            self.start()

    def elapsed(self):
        return max(0, self.clock() - self.started) if self.started is not None else 0
