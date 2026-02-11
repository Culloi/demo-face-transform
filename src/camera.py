# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import glob
import time
from typing import Optional, List

import cv2


def _try_open_one(source, width: int, height: int, fps: int) -> Optional[cv2.VideoCapture]:
    """Try open a camera/video node and read a few warmup frames."""
    # Prefer V4L2 backend on Linux
    try:
        cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
    except Exception:
        cap = cv2.VideoCapture(source)

    if cap is None or not cap.isOpened():
        try:
            cap.release()
        except Exception:
            pass
        return None

    # Apply requested format (driver may not honor it)
    try:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
        cap.set(cv2.CAP_PROP_FPS, float(fps))
        # Try MJPG for many USB cams
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    except Exception:
        pass

    ok = False
    for _ in range(12):
        ret, frame = cap.read()
        if ret and frame is not None and getattr(frame, "size", 0) > 0:
            ok = True
            break
        time.sleep(0.02)

    if not ok:
        try:
            cap.release()
        except Exception:
            pass
        return None

    return cap


def _enumerate_candidates(preferred_device: str, fallback_index: int) -> List[object]:
    """Candidate sources to try, in order."""
    cands: List[object] = []
    if preferred_device:
        cands.append(preferred_device)

    # Stable symlinks (recommended)
    for pat in ("/dev/v4l/by-id/*", "/dev/v4l/by-path/*"):
        for p in sorted(glob.glob(pat)):
            if p not in cands:
                cands.append(p)

    # Raw nodes
    for i in range(10):
        p = f"/dev/video{i}"
        if os.path.exists(p) and p not in cands:
            cands.append(p)

    if fallback_index is not None:
        cands.append(int(fallback_index))

    # de-dup keep order
    out: List[object] = []
    seen = set()
    for c in cands:
        key = str(c)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def open_camera(device: str, fallback_index: int, width: int, height: int, fps: int) -> cv2.VideoCapture:
    """Robust camera open with auto-probe for node changes."""
    candidates = _enumerate_candidates(device, fallback_index)
    last_err = None

    for src in candidates:
        try:
            cap = _try_open_one(src, width, height, fps)
            if cap is not None:
                return cap
        except Exception as e:
            last_err = e
            continue

    raise RuntimeError(
        "Cannot open any camera source. "
        f"Tried: {', '.join(map(str, candidates))}. "
        + (f"Last error: {last_err}" if last_err else "")
    )
