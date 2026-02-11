# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Tuple, Optional
import cv2
import numpy as np

def ellipse_mask(shape_hw: Tuple[int, int]) -> np.ndarray:
    h, w = shape_hw
    mask = np.zeros((h, w), dtype=np.uint8)
    ax = max(10, int(w * 0.42))
    ay = max(10, int(h * 0.50))
    cx, cy = w // 2, h // 2
    ax = min(ax, max(10, w // 2 - 6))
    ay = min(ay, max(10, h // 2 - 6))
    cv2.ellipse(mask, (cx, cy), (ax, ay), 0, 0, 360, 255, -1)
    return mask

def match_color_lab(src_patch_bgr: np.ndarray, dst_patch_bgr: np.ndarray) -> np.ndarray:
    """
    Match LAB mean/std of src_patch to dst_patch (color/brightness match).
    Goal: reduce obvious pasted/stitched look.
    """
    src = cv2.cvtColor(src_patch_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    dst = cv2.cvtColor(dst_patch_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)

    src_mean, src_std = cv2.meanStdDev(src)
    dst_mean, dst_std = cv2.meanStdDev(dst)

    src_std = np.maximum(src_std, 1.0)
    dst_std = np.maximum(dst_std, 1.0)

    out = (src - src_mean.reshape(1, 1, 3)) * (dst_std.reshape(1, 1, 3) / src_std.reshape(1, 1, 3)) + dst_mean.reshape(1, 1, 3)
    out = np.clip(out, 0, 255).astype(np.uint8)
    return cv2.cvtColor(out, cv2.COLOR_LAB2BGR)

def feather_blend(src: np.ndarray, dst: np.ndarray, roi_xywh: Tuple[int, int, int, int], sigma: float = 9.0) -> np.ndarray:
    x, y, w, h = roi_xywh
    out = dst.copy()
    src_roi = src[y:y+h, x:x+w]
    dst_roi = dst[y:y+h, x:x+w]
    if src_roi.size == 0 or dst_roi.size == 0:
        return out
    mask = ellipse_mask((h, w)).astype(np.float32) / 255.0
    k = int(max(3, (sigma * 4) // 2 * 2 + 1))
    mask = cv2.GaussianBlur(mask, (k, k), sigmaX=float(sigma), sigmaY=float(sigma))
    mask3 = np.repeat(mask[:, :, None], 3, axis=2)
    blended = (src_roi.astype(np.float32) * mask3 + dst_roi.astype(np.float32) * (1.0 - mask3)).clip(0, 255).astype(np.uint8)
    out[y:y+h, x:x+w] = blended
    return out

def paste_with_seamless_clone(src_patch: np.ndarray, dst: np.ndarray, roi_xywh: Tuple[int, int, int, int], feather_sigma_fallback: float = 9.0) -> np.ndarray:
    x, y, w, h = roi_xywh
    if w <= 2 or h <= 2:
        return dst
    patch = src_patch
    if patch.shape[0] != h or patch.shape[1] != w:
        patch = cv2.resize(patch, (w, h), interpolation=cv2.INTER_LINEAR)
    mask = ellipse_mask((h, w))
    center = (x + w // 2, y + h // 2)
    try:
        return cv2.seamlessClone(patch, dst, mask, center, cv2.NORMAL_CLONE)
    except Exception:
        tmp = dst.copy()
        tmp[y:y+h, x:x+w] = patch
        return feather_blend(tmp, dst, roi_xywh, sigma=float(feather_sigma_fallback))

def apply_face_only(api_full_bgr: np.ndarray, orig_bgr: np.ndarray, roi_xywh: Optional[Tuple[int, int, int, int]],
                    mode: str = "seamless", feather_sigma: float = 9.0) -> np.ndarray:
    if roi_xywh is None or mode == "none":
        return api_full_bgr

    x, y, w, h = roi_xywh
    x2, y2 = x + w, y + h
    x2 = min(orig_bgr.shape[1], x2)
    y2 = min(orig_bgr.shape[0], y2)
    w = max(1, x2 - x)
    h = max(1, y2 - y)
    roi_xywh = (x, y, w, h)

    patch = api_full_bgr[y:y+h, x:x+w]
    if patch.size == 0:
        return api_full_bgr

    if mode == "seamless":
        return paste_with_seamless_clone(patch, orig_bgr, roi_xywh, feather_sigma_fallback=feather_sigma)
    if mode == "feather":
        tmp = orig_bgr.copy()
        tmp[y:y+h, x:x+w] = patch
        return feather_blend(tmp, orig_bgr, roi_xywh, sigma=float(feather_sigma))
    return api_full_bgr
