# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional
import os
import time
import threading
from collections import deque

import cv2
import numpy as np

from PySide6.QtCore import Qt, QTimer, QSize, QThreadPool, QRunnable, QObject, Signal
from PySide6.QtGui import QImage, QPixmap, QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QTextEdit,
    QHBoxLayout, QVBoxLayout, QGroupBox, QMessageBox, 
    QFileDialog, QProgressBar, QScrollArea, QFrame
)

from config import DEFAULTS
from app_utils import ensure_out_dir
from camera import open_camera
from tencent_api import build_clients
from effects import run_anime, run_gender_once, run_age_morph


DARK_QSS = """
QWidget {
    background: #0f1220;
    color: #e8eaf6;
    font-size: 13px;
}
QGroupBox {
    border: 1px solid #2b2f45;
    border-radius: 10px;
    margin-top: 10px;
    padding: 10px;
    background: #12162a;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #c7c9ff;
    font-weight: 600;
}
QPushButton {
    background: #1c2340;
    border: 1px solid #2e365a;
    border-radius: 10px;
    padding: 10px 12px;
    font-weight: 600;
}
QPushButton:hover { background: #232c52; }
QPushButton:pressed { background: #161c35; }
QPushButton:disabled {
    background: #15192b;
    color: #7a7f9c;
    border: 1px solid #222843;
}
 {
    background: #1c2340;
    border: 1px solid #2e365a;
    border-radius: 10px;
    padding: 8px 10px;
}
:focus {
    border: 1px solid #3a4573;
    outline: 0px;
}
::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border-left: 1px solid #2e365a;
    border-top-right-radius: 10px;
    border-bottom-right-radius: 10px;
}
::down-arrow {
    image: none;
}
 QAbstractItemView {
    background: #0d1020;
    color: #e8eaf6;
    selection-background-color: #232c52;
    selection-color: #ffffff;
    border: 1px solid #2b2f45;
    outline: 0px;
}
 QAbstractItemView::item {
    padding: 8px 10px;
    border: none;
}
 QAbstractItemView::item:selected {
    background: #232c52;
}
QTextEdit {
    background: #0d1020;
    border: 1px solid #2b2f45;
    border-radius: 10px;
}
QProgressBar {
    border: 1px solid #2b2f45;
    border-radius: 8px;
    background: #0d1020;
    text-align: center;
    height: 10px;
}
QProgressBar::chunk { background: #5c6bc0; border-radius: 8px; }
"""


def _badge(text: str, bg: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(
        f"QLabel{{background:{bg}; color:#0b0d14; padding:4px 10px; border-radius:10px; font-weight:700;}}"
    )
    lab.setMinimumHeight(24)
    return lab


class UiBus(QObject):
    log = Signal(str)
    busy = Signal(bool)
    override = Signal(object, float)  # (bgr ndarray, seconds)
    play_video = Signal(str)          # local mp4 path


class EffectTask(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        self.fn()


class MainWindow(QWidget):
    """
    Dark-themed UI (user-facing).
    - Responsive layout for available screen area
    - Scrollable control panel
    - Header bar with fullscreen button
    - Status badges: camera / task / FPS
    - Logs collapsed by default
    """
    def __init__(self) -> None:
        super().__init__()
        self.setStyleSheet(DARK_QSS)

        self.pool = QThreadPool.globalInstance()
        self.bus = UiBus()
        self.bus.log.connect(self._append_log)
        self.bus.busy.connect(self._set_busy)
        self.bus.override.connect(self._set_override)
        self.bus.play_video.connect(self._start_video_playback)

        self._video_playing = False
        self._video_cap = None
        self._video_fps = 0.0
        self._saved_timer_interval_ms = None
        self._video_done_event = None

        self._busy = False
        self._last_frame: Optional[np.ndarray] = None
        self._override_frame: Optional[np.ndarray] = None
        self._override_until: float = 0.0

        self.ft = None
        self.common = None

        # FPS estimate for camera preview
        self._tick_times = deque(maxlen=30)

        self.setWindowTitle("Face Transform")

        # ✅ 用可用屏幕区域（扣掉顶部栏/任务栏）
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            ag = screen.availableGeometry()
            target_w = min(1280, ag.width())
            target_h = min(800, ag.height())
            target_w = max(920, target_w)
            target_h = max(650, target_h)
            self.resize(target_w, target_h)
        else:
            self.resize(1200, 760)
        self.setMinimumSize(QSize(920, 650))

        # --------- Header ----------
        self.title_label = QLabel("Ai Face Swap")
        self.title_label.setStyleSheet("font-size:18px; font-weight:800; color:#ffffff;")

        self.btn_fullscreen = QPushButton("Full Screen")
        self.btn_fullscreen.setFixedHeight(36)
        self.btn_fullscreen.clicked.connect(self._toggle_fullscreen)

        self.btn_quit = QPushButton("Quit")
        self.btn_quit.setFixedHeight(36)
        self.btn_quit.clicked.connect(self.close)

        header_left = QVBoxLayout()
        header_left.setSpacing(2)
        header_left.addWidget(self.title_label)

        header = QHBoxLayout()
        header.addLayout(header_left)
        header.addStretch(1)
        header.addWidget(self.btn_fullscreen)
        header.addWidget(self.btn_quit)

        header_frame = QFrame()
        header_frame.setLayout(header)
        header_frame.setStyleSheet("QFrame{background:#0c1020; border:1px solid #2b2f45; border-radius:12px; padding:8px;}")

        # --------- Preview ----------
        self.preview = QLabel("Initializing camera...")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(QSize(780, 560))
        self.preview.setStyleSheet(
            "background:#050712; border:1px solid #2b2f45; border-radius:12px; color:#cfd3ff; font-size:16px;"
        )

        gb_preview = QGroupBox("Camera Feed")
        vb_prev = QVBoxLayout()
        vb_prev.addWidget(self.preview)
        gb_preview.setLayout(vb_prev)

        # --------- User controls ----------
        self.btn_age = QPushButton("Face Age Change")
        self.btn_anime = QPushButton("Anime Portrait")
        self.btn_gender = QPushButton("Face Gender Swap")

        self.btn_age.clicked.connect(self._on_age)
        self.btn_anime.clicked.connect(self._on_anime)
        self.btn_gender.clicked.connect(self._on_gender)

        gb_ops = QGroupBox("Functions")
        v_ops = QVBoxLayout()
        v_ops.setSpacing(10)
        v_ops.addWidget(self.btn_age)
        v_ops.addWidget(self.btn_anime)
        v_ops.addWidget(self.btn_gender)
        gb_ops.setLayout(v_ops)

        # --------- Save ----------
        self.out_dir = ensure_out_dir(DEFAULTS.get("out_dir", "./outputs"))
        self.out_dir_label = QLabel(f"Output folder: {self.out_dir}")
        self.out_dir_label.setWordWrap(True)
        self.out_dir_label.setStyleSheet("color:#cdd1ff;")
        self.btn_choose_out = QPushButton("Choose output folder...")
        self.btn_choose_out.clicked.connect(self._choose_out_dir)

        gb_out = QGroupBox("Save")
        v_out = QVBoxLayout()
        v_out.setSpacing(10)
        v_out.addWidget(self.out_dir_label)
        v_out.addWidget(self.btn_choose_out)
        gb_out.setLayout(v_out)

        # --------- Status ----------
        self.badge_camera = _badge("Camera: Starting", "#f7c948")
        self.badge_task = _badge("Task: Idle", "#b8f7d4")
        self.badge_fps = _badge("FPS: --", "#b3d4ff")

        badges = QHBoxLayout()
        badges.setSpacing(8)
        badges.addWidget(self.badge_camera)
        badges.addWidget(self.badge_task)
        badges.addWidget(self.badge_fps)
        badges.addStretch(1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)

        self.btn_toggle_log = QPushButton("Show Logs")
        self.btn_toggle_log.clicked.connect(self._toggle_log)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        # 限制日志最大行数，避免长时间运行占用过多内存
        self.log.document().setMaximumBlockCount(int(DEFAULTS.get("max_log_lines", 500)))
        self.log.setVisible(False)
        self.log.setMinimumHeight(180)

        gb_status = QGroupBox("Status")
        v_status = QVBoxLayout()
        v_status.setSpacing(10)
        v_status.addLayout(badges)
        v_status.addWidget(self.progress)
        v_status.addWidget(self.btn_toggle_log)
        v_status.addWidget(self.log)
        gb_status.setLayout(v_status)

        # --------- Layout root ----------
        main = QVBoxLayout()
        main.setContentsMargins(10, 10, 10, 10)
        main.setSpacing(10)
        main.addWidget(header_frame)

        body = QHBoxLayout()
        body.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(10)
        left.addWidget(gb_preview)
        body.addLayout(left, stretch=3)

        # Right panel -> scroll area
        right_content = QWidget()
        right = QVBoxLayout(right_content)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        right.addWidget(gb_ops)
        right.addWidget(gb_out)
        right.addWidget(gb_status, stretch=1)
        right.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(right_content)
        scroll.setStyleSheet("QScrollArea{border:none; background:transparent;}")

        body.addWidget(scroll, stretch=2)

        main.addLayout(body)
        self.setLayout(main)

        # --------- Camera ----------
        self.cap: Optional[cv2.VideoCapture] = None
        self._open_camera()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(int(1000 // max(5, int(DEFAULTS.get("cam_fps", 30)))))

    # ---------------- Header actions ----------------
    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.btn_fullscreen.setText("Full Screen")
        else:
            self.showFullScreen()
            self.btn_fullscreen.setText("Exit Full Screen")

    # ---------------- Logs / badges ----------------
    def _append_log(self, msg: str) -> None:
        self.log.append(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def _emit_log(self, msg: str) -> None:
        self.bus.log.emit(msg)

    def _set_badge(self, badge: QLabel, text: str, bg: str) -> None:
        badge.setText(text)
        badge.setStyleSheet(
            f"QLabel{{background:{bg}; color:#0b0d14; padding:4px 10px; border-radius:10px; font-weight:800;}}"
        )

    def _set_busy(self, v: bool) -> None:
        self._busy = v
        for b in (self.btn_age, self.btn_anime, self.btn_gender, self.btn_choose_out, self.btn_fullscreen, self.btn_quit):
            b.setEnabled(not v)
        self.progress.setVisible(v)

        if v:
            self._set_badge(self.badge_task, "Task: Running", "#ffd166")
        else:
            self._set_badge(self.badge_task, "Task: Idle", "#b8f7d4")

    def _toggle_log(self) -> None:
        vis = not self.log.isVisible()
        self.log.setVisible(vis)
        self.btn_toggle_log.setText("Hide Logs" if vis else "Show Logs")

    def _choose_out_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose Output Folder", self.out_dir)
        if d:
            self.out_dir = ensure_out_dir(d)
            self.out_dir_label.setText(f"Output folder: {self.out_dir}")
            self._emit_log(f"Output folder set to: {self.out_dir}")

    def _warn(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, text)

    # ---------------- Camera ----------------
    def _open_camera(self) -> None:
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

        dev = str(DEFAULTS.get("cam_device", "/dev/video2"))
        idx = int(DEFAULTS.get("cam_index_fallback", 2))
        self._emit_log(f"Opening camera device={dev} (fallback index={idx}) ...")

        try:
            cap = open_camera(
                device=dev,
                fallback_index=idx,
                width=int(DEFAULTS.get("cam_width", 1280)),
                height=int(DEFAULTS.get("cam_height", 720)),
                fps=int(DEFAULTS.get("cam_fps", 30)),
            )
        except Exception as e:
            self.preview.setText("Failed to open camera")
            self._set_badge(self.badge_camera, "Camera: Error", "#ef476f")
            self._emit_log(f"Failed to open camera: {e}")
            return

        ok = False
        for _ in range(12):
            ret, frame = cap.read()
            if ret and frame is not None and frame.size > 0:
                ok = True
                self._last_frame = frame
                break
        if not ok:
            self.preview.setText("Camera read failed")
            self._set_badge(self.badge_camera, "Camera: Error", "#ef476f")
            self._emit_log("Camera warm-up read failed.")
            cap.release()
            return

        self.cap = cap
        self._set_badge(self.badge_camera, "Camera: Running", "#06d6a0")
        self._emit_log("Camera ready (requested 1280x720@30; actual depends on driver).")

    # ---------------- Preview override ----------------
    def _set_override(self, bgr: object, seconds: float) -> None:
        if not isinstance(bgr, np.ndarray):
            return
        self._override_frame = bgr
        self._override_until = time.time() + max(0.0, float(seconds))

    def _current_frame_for_display(self) -> Optional[np.ndarray]:
        now = time.time()
        if self._override_frame is not None and now < self._override_until:
            return self._override_frame
        self._override_frame = None
        return self._last_frame

    def _pixmap_from_bgr(self, bgr: np.ndarray) -> QPixmap:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, int(rgb.strides[0]), QImage.Format_RGB888).copy()
        return QPixmap.fromImage(qimg)

    def _update_fps_badge(self) -> None:
        self._tick_times.append(time.time())
        if len(self._tick_times) >= 2:
            dt = self._tick_times[-1] - self._tick_times[0]
            if dt > 0:
                fps = (len(self._tick_times) - 1) / dt
                self._set_badge(self.badge_fps, f"FPS: {fps:.1f}", "#b3d4ff")

    # ---------------- Main timer tick ----------------
    def _tick(self) -> None:
        if self._video_playing and self._video_cap is not None:
            ret, frame = self._video_cap.read()
            if not ret or frame is None:
                self._stop_video_playback()
                return
            self._last_frame = frame
            bgr = frame
        else:
            if self.cap is not None:
                try:
                    ret, frame = self.cap.read()
                except Exception as e:
                    self._emit_log(f"Camera read error: {e}")
                    ret, frame = False, None
                if ret and frame is not None and frame.size > 0:
                    self._last_frame = frame

            bgr = self._current_frame_for_display()
            if bgr is None:
                return

        pix = self._pixmap_from_bgr(bgr)
        target = self.preview.size()
        pix = pix.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setPixmap(pix)

        self._update_fps_badge()

    def _snapshot(self) -> Optional[np.ndarray]:
        if self._last_frame is None:
            return None
        return self._last_frame.copy()

    # ---------------- Tencent clients ----------------
    def _ensure_clients(self):
        if self.ft is None or self.common is None:
            self._emit_log("Initializing Tencent Cloud client (region/endpoint from config.py)...")
            self.ft, self.common = build_clients(
                region=str(DEFAULTS["region"]),
                endpoint=str(DEFAULTS["endpoint"]),
                ft_version=str(DEFAULTS["ft_version"]),
            )
        return self.ft, self.common

    def _start_task(self, fn, snap: np.ndarray) -> None:
        def task():
            try:
                fn(snap)
            except Exception as e:
                self._emit_log(f"Task error: {e}")
                self._set_badge(self.badge_task, "Task: Error", "#ef476f")
            finally:
                self.bus.busy.emit(False)

        self.bus.busy.emit(True)
        self.pool.start(EffectTask(task))

    # ---------------- User actions ----------------
    def _on_age(self) -> None:
        if self._busy:
            return
        snap = self._snapshot()
        if snap is None:
            self._warn("Notice", "Camera frame is not ready yet. Please wait.")
            return
        self._start_task(self._run_age, snap)

    def _on_anime(self) -> None:
        if self._busy:
            return
        snap = self._snapshot()
        if snap is None:
            self._warn("Notice", "Camera frame is not ready yet. Please wait.")
            return
        self._start_task(self._run_anime, snap)

    def _on_gender(self) -> None:
        if self._busy:
            return
        snap = self._snapshot()
        if snap is None:
            self._warn("Notice", "Camera frame is not ready yet. Please wait.")
            return
        self._start_task(self._run_gender, snap)

    # ---------------- Effect runners ----------------
    def _run_anime(self, snap_bgr: np.ndarray) -> None:
        ft, _ = self._ensure_clients()
        self._emit_log("Starting anime portrait...")
        img, path = run_anime(ft, snap_bgr, self.out_dir)
        self.bus.override.emit(img, float(DEFAULTS.get("anime_show_seconds", 3.0)))
        self._emit_log(f"Anime portrait saved: {path}")

    def _run_gender(self, snap_bgr: np.ndarray) -> None:
        ft, _ = self._ensure_clients()
        self._emit_log("Starting face gender swap (full-frame)...")
        img, path = run_gender_once(ft, snap_bgr, self.out_dir)

        show_s = float(DEFAULTS.get("gender_show_seconds", 4.0))
        show_s = max(0.5, show_s)
        self.bus.override.emit(img, show_s)

        self._emit_log(f"Gender swap image saved: {path}")
    def _run_age(self, snap_bgr: np.ndarray) -> None:
        ft, common = self._ensure_clients()
        self._emit_log("Starting face age change (video)...")
        mp4 = run_age_morph(
            ft, common, snap_bgr, self.out_dir,
            log_cb=self._emit_log,
            preview_cb=lambda img, sec: self.bus.override.emit(img, float(sec))
        )

        self._emit_log("Playing generated video...")
        self._video_done_event = threading.Event()
        self.bus.play_video.emit(mp4)
        self._video_done_event.wait()
        self._emit_log(f"Age change video saved: {mp4}")

    # ---------------- Local video playback ----------------
    def _start_video_playback(self, path: str) -> None:
        try:
            if not path or not os.path.exists(path):
                self._emit_log(f"Local video not found: {path}")
                if self._video_done_event is not None:
                    self._video_done_event.set()
                return

            self._stop_video_playback(silent=True)

            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                self._emit_log(f"Cannot open local video: {path}")
                if self._video_done_event is not None:
                    self._video_done_event.set()
                return

            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps is None or fps <= 1.0 or fps > 120.0:
                fps = 25.0

            self._video_cap = cap
            self._video_fps = float(fps)
            self._video_playing = True

            if self._saved_timer_interval_ms is None:
                self._saved_timer_interval_ms = self.timer.interval()
            target_ms = int(1000 / max(5.0, self._video_fps))
            self.timer.setInterval(max(5, target_ms))

        except Exception as e:
            self._emit_log(f"Failed to start video playback: {e}")
            if self._video_done_event is not None:
                self._video_done_event.set()

    def _stop_video_playback(self, silent: bool = False) -> None:
        if not self._video_playing:
            return
        self._video_playing = False
        try:
            if self._video_cap is not None:
                self._video_cap.release()
        except Exception:
            pass
        self._video_cap = None
        self._video_fps = 0.0

        try:
            if self._saved_timer_interval_ms is not None:
                self.timer.setInterval(self._saved_timer_interval_ms)
        except Exception:
            pass
        self._saved_timer_interval_ms = None

        self._override_frame = None
        self._override_until = 0.0

        if self._video_done_event is not None:
            try:
                self._video_done_event.set()
            except Exception:
                pass
            self._video_done_event = None

    def closeEvent(self, event):  # type: ignore
        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:
            pass
        event.accept()
