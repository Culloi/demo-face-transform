# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple, Callable
import time
import gc

def _translate_job_status(s: str) -> str:
    """Translate Tencent job status text to English (handles CN statuses)."""
    if not s:
        return s
    m = {
        "\u6392\u961f\u4e2d": "Queued",          # 排队中
        "\u5904\u7406\u4e2d": "Processing",     # 处理中
        "\u5904\u7406\u5b8c\u6210": "Completed",  # 处理完成
        "\u6210\u529f": "Succeeded",            # 成功
        "\u5931\u8d25": "Failed",               # 失败
        "\u5df2\u53d6\u6d88": "Cancelled",      # 已取消
    }
    return m.get(s, s)

import os
import cv2
import numpy as np

from config import DEFAULTS
from app_utils import ensure_out_dir, ts_str
from vision import detect_face_roi, expand_rect, resize_max_side
from blend import apply_face_only, match_color_lab
from tencent_api import (
    cv2_to_jpg_b64, b64_to_bgr_image,
    change_age_pic_base64, face_cartoon_pic_base64, swap_gender_pic_base64,
    morph_face_submit, query_morph_job
)
from downloader import download_https_overwrite, force_https

@dataclass
class RoiPack:
    roi_bgr: np.ndarray
    roi_xywh: Tuple[int, int, int, int]
    detected_face_xywh: Optional[Tuple[int, int, int, int]]

def prepare_roi(snap_bgr: np.ndarray) -> RoiPack:
    H, W = snap_bgr.shape[:2]
    face = None
    if bool(DEFAULTS.get("enable_face_roi", True)):
        face = detect_face_roi(snap_bgr, min_face_size=int(DEFAULTS.get("min_face_size", 90)))

    if face is None:
        return RoiPack(roi_bgr=snap_bgr.copy(), roi_xywh=(0, 0, W, H), detected_face_xywh=None)

    roi = expand_rect(face, float(DEFAULTS.get("roi_margin", 0.5)), W, H)
    x, y, w, h = roi
    return RoiPack(roi_bgr=snap_bgr[y:y+h, x:x+w].copy(), roi_xywh=roi, detected_face_xywh=face)

def call_api_on_roi(ft, roi_bgr: np.ndarray, api_fn: Callable, *api_args) -> np.ndarray:
    roi_in = resize_max_side(roi_bgr, int(DEFAULTS.get("api_input_max_side", 720)))
    roi_b64 = cv2_to_jpg_b64(roi_in, jpeg_quality=int(DEFAULTS.get("jpeg_quality", 95)))
    out_b64 = api_fn(ft, roi_b64, *api_args)
    out_roi = b64_to_bgr_image(out_b64)

    # API 输出尺寸可能变化：拉回输入尺寸，再拉回原 roi
    out_roi = cv2.resize(out_roi, (roi_in.shape[1], roi_in.shape[0]), interpolation=cv2.INTER_LINEAR)
    out_roi = cv2.resize(out_roi, (roi_bgr.shape[1], roi_bgr.shape[0]), interpolation=cv2.INTER_LINEAR)
    return out_roi

def compose_roi_back(snap_bgr: np.ndarray, out_roi_bgr: np.ndarray, roi_xywh: Tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = roi_xywh
    if out_roi_bgr.shape[:2] != (h, w):
        out_roi_bgr = cv2.resize(out_roi_bgr, (w, h), interpolation=cv2.INTER_LINEAR)

    # 关键：颜色/亮度匹配，降低贴图感
    if bool(DEFAULTS.get("color_match_lab", True)):
        try:
            orig_roi = snap_bgr[y:y+h, x:x+w]
            if orig_roi is not None and orig_roi.size > 0:
                out_roi_bgr = match_color_lab(out_roi_bgr, orig_roi)
        except Exception:
            pass

    api_full = snap_bgr.copy()
    api_full[y:y+h, x:x+w] = out_roi_bgr

    blended = apply_face_only(
        api_full, snap_bgr, roi_xywh,
        mode=str(DEFAULTS.get("blend_mode", "seamless")),
        feather_sigma=float(DEFAULTS.get("feather_sigma", 9.0))
    )
    return blended

def run_anime(ft, snap_bgr: np.ndarray, out_dir: str) -> Tuple[np.ndarray, str]:
    out_dir = ensure_out_dir(out_dir)

    in_bgr = resize_max_side(snap_bgr, int(DEFAULTS.get("api_input_max_side", 720)))
    snap_b64 = cv2_to_jpg_b64(in_bgr, jpeg_quality=int(DEFAULTS.get("jpeg_quality", 95)))

    out_b64 = face_cartoon_pic_base64(ft, snap_b64, disable_global_effect=bool(DEFAULTS["anime_disable_global_effect"]))
    anime_bgr = b64_to_bgr_image(out_b64)
    anime_bgr = cv2.resize(anime_bgr, (snap_bgr.shape[1], snap_bgr.shape[0]), interpolation=cv2.INTER_LINEAR)

    out_path = os.path.join(out_dir, f"anime_{ts_str()}.jpg")
    cv2.imwrite(out_path, anime_bgr)
    return anime_bgr, out_path

def run_gender_pair(ft, snap_bgr: np.ndarray, out_dir: str) -> Tuple[np.ndarray, np.ndarray, str, str]:
    """
    Gender swap (full-frame mode):
    - Call SwapGenderPic on the full image (no ROI crop + paste-back)
    - Optional: global LAB color/brightness match to reduce color shift
    """
    out_dir = ensure_out_dir(out_dir)

    api_max_side = int(DEFAULTS.get("api_input_max_side", 720))
    jpeg_quality = int(DEFAULTS.get("jpeg_quality", 95))
    do_global_match = bool(DEFAULTS.get("gender_global_color_match", True))

    # 输入整图（控制尺寸/质量）
    in_bgr = resize_max_side(snap_bgr, api_max_side)
    in_b64 = cv2_to_jpg_b64(in_bgr, jpeg_quality=jpeg_quality)

    out_b64_f = swap_gender_pic_base64(ft, in_b64, 0)
    out_b64_m = swap_gender_pic_base64(ft, in_b64, 1)

    out_f = b64_to_bgr_image(out_b64_f)
    out_m = b64_to_bgr_image(out_b64_m)

    # 拉回原始分辨率
    out_f = cv2.resize(out_f, (snap_bgr.shape[1], snap_bgr.shape[0]), interpolation=cv2.INTER_LINEAR)
    out_m = cv2.resize(out_m, (snap_bgr.shape[1], snap_bgr.shape[0]), interpolation=cv2.INTER_LINEAR)

    # 可选：整图颜色/亮度匹配到原图（减少“风格漂移/色偏”）
    if do_global_match:
        try:
            out_f = match_color_lab(out_f, snap_bgr)
            out_m = match_color_lab(out_m, snap_bgr)
        except Exception:
            pass

    path_f = os.path.join(out_dir, f"gender_f_{ts_str()}.jpg")
    path_m = os.path.join(out_dir, f"gender_m_{ts_str()}.jpg")
    cv2.imwrite(path_f, out_f)
    cv2.imwrite(path_m, out_m)
    return out_f, out_m, path_f, path_m


def run_gender_once(ft, snap_bgr: np.ndarray, out_dir: str) -> Tuple[np.ndarray, str]:
    """
    Face gender swap (full-frame, single output):
    - Call SwapGenderPic on the full image (no ROI crop + paste-back)
    - Call the API once and return a single converted image
    - Target gender controlled by DEFAULTS['gender_target']: 0=female, 1=male
    """
    out_dir = ensure_out_dir(out_dir)

    api_max_side = int(DEFAULTS.get("api_input_max_side", 720))
    jpeg_quality = int(DEFAULTS.get("jpeg_quality", 95))
    do_global_match = bool(DEFAULTS.get("gender_global_color_match", True))
    target = int(DEFAULTS.get("gender_target", 0))  # 0=female, 1=male

    in_bgr = resize_max_side(snap_bgr, api_max_side)
    in_b64 = cv2_to_jpg_b64(in_bgr, jpeg_quality=jpeg_quality)

    out_b64 = swap_gender_pic_base64(ft, in_b64, target)
    out_img = b64_to_bgr_image(out_b64)

    out_img = cv2.resize(out_img, (snap_bgr.shape[1], snap_bgr.shape[0]), interpolation=cv2.INTER_LINEAR)

    if do_global_match:
        try:
            out_img = match_color_lab(out_img, snap_bgr)
        except Exception:
            pass

    suffix = "f" if target == 0 else "m"
    path = os.path.join(out_dir, f"gender_{suffix}_{ts_str()}.jpg")
    cv2.imwrite(path, out_img)
    return out_img, path



def run_age_morph(ft, common, snap_bgr: np.ndarray, out_dir: str, log_cb: Callable[[str], None],
                 preview_cb: Callable[[np.ndarray, float], None] | None = None) -> str:
    out_dir = ensure_out_dir(out_dir)
    ages: List[int] = list(DEFAULTS["ages"])
    if not (2 <= len(ages) <= 5):
        raise ValueError("DEFAULTS['ages'] must contain 2 to 5 ages")

    log_cb(f"Age sequence: {ages}")
    roi_pack = prepare_roi(snap_bgr)

    imgs_full_b64: List[str] = []
    for age in ages:
        log_cb(f"ChangeAgePic -> age={age}")
        out_roi = call_api_on_roi(ft, roi_pack.roi_bgr, change_age_pic_base64, int(age))
        full = compose_roi_back(snap_bgr, out_roi, roi_pack.roi_xywh)
        # 预览：每张年龄图会一直显示到下一张生成（最后一张保持到视频开始播放）
        if preview_cb is not None:
            try:
                # 用很长的持续时间，让预览保持到下一次 override 或视频播放开始
                preview_cb(full, float(DEFAULTS.get("age_preview_hold_seconds", 3600.0)))
            except Exception:
                pass
        imgs_full_b64.append(cv2_to_jpg_b64(full, jpeg_quality=int(DEFAULTS.get("jpeg_quality", 95))))

    log_cb("Submitting MorphFace job...")
    job_id = morph_face_submit(
        common, imgs_full_b64, int(DEFAULTS["morph_fps"]),
        int(snap_bgr.shape[1]), int(snap_bgr.shape[0]),
        float(DEFAULTS["tempo"]), float(DEFAULTS["morph_time"])
    )
    log_cb(f"JobId={job_id}, polling...")

    while True:
        r = query_morph_job(common, job_id)
        code = r.get("JobStatusCode")
        jstatus = r.get("JobStatus")

        if code in (1, 2, 3):
            log_cb(f"In progress: {_translate_job_status(jstatus)} (code={code})")
            time.sleep(2)
            continue

        if code == 5:
            raise RuntimeError(f"MorphFace failed: {r}")

        if code == 7:
            out = r.get("FaceMorphOutput") or {}
            morph_url = out.get("MorphUrl")
            if not morph_url:
                raise RuntimeError(f"Completed but MorphUrl missing: {r}")
            url_https = force_https(morph_url)
            out_mp4 = os.path.join(out_dir, f"age_morph_{job_id}_{ts_str()}.mp4")
            log_cb("Downloading video...")
            download_https_overwrite(
                url_https, out_mp4,
                timeout=int(DEFAULTS["dl_timeout"]),
                retries=int(DEFAULTS["dl_retries"])
            )
            log_cb(f"Saved: {out_mp4}")
            # ---- memory cleanup ----
            # 年龄渐变会产生多张中间图/bytes/base64；显式清理引用，帮助 Python 更快回收内存
            try:
                for _name in ("imgs_full_b64",):
                    if _name in locals() and locals()[_name] is not None:
                        try:
                            locals()[_name].clear()
                        except Exception:
                            pass
                for _name in ("imgs_full_b64", "full", "out_roi"):
                    if _name in locals():
                        try:
                            del locals()[_name]
                        except Exception:
                            pass
            except Exception:
                pass
            gc.collect()
            return out_mp4

        log_cb(f"Unknown job status: code={code}, status={_translate_job_status(jstatus)}")
        time.sleep(2)
