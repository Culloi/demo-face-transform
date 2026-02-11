# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, Tuple
import cv2
import numpy as np

def detect_face_roi(bgr: np.ndarray, min_face_size: int = 90) -> Optional[Tuple[int, int, int, int]]:
    """
    Detect the largest face bbox (x,y,w,h) using HaarCascade. Return None if not found.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    if not cascade_path:
        return None
    cascade = cv2.CascadeClassifier(cascade_path)
    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        flags=cv2.CASCADE_SCALE_IMAGE,
        minSize=(int(min_face_size), int(min_face_size)),
    )
    if faces is None or len(faces) == 0:
        return None
    rects = [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in faces]
    rects.sort(key=lambda r: r[2] * r[3], reverse=True)
    return rects[0]

def expand_rect(rect: Tuple[int, int, int, int], margin: float, w: int, h: int) -> Tuple[int, int, int, int]:
    x, y, rw, rh = rect
    cx = x + rw / 2.0
    cy = y + rh / 2.0
    rw2 = rw * (1.0 + margin)
    rh2 = rh * (1.0 + margin)
    nx = int(round(cx - rw2 / 2.0))
    ny = int(round(cy - rh2 / 2.0))
    nrw = int(round(rw2))
    nrh = int(round(rh2))
    nx = max(0, nx)
    ny = max(0, ny)
    nrw = min(w - nx, nrw)
    nrh = min(h - ny, nrh)
    if nrw <= 0 or nrh <= 0:
        return rect
    return (nx, ny, nrw, nrh)

def resize_max_side(bgr: np.ndarray, max_side: int) -> np.ndarray:
    h, w = bgr.shape[:2]
    m = max(h, w)
    if m <= max_side:
        return bgr
    scale = float(max_side) / float(m)
    nh = max(1, int(round(h * scale)))
    nw = max(1, int(round(w * scale)))
    return cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA)
