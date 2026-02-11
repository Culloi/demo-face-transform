# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Tuple
import os
import json

import numpy as np
import cv2
import base64

from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.ft.v20200304 import ft_client, models
from tencentcloud.common.common_client import CommonClient

def cv2_to_jpg_b64(frame_bgr: np.ndarray, jpeg_quality: int = 95) -> str:
    ok, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
    if not ok:
        raise RuntimeError("cv2.imencode(.jpg) failed")
    return base64.b64encode(buf).decode("utf-8")

def b64_to_bgr_image(img_b64: str) -> np.ndarray:
    raw = base64.b64decode(img_b64)
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("cv2.imdecode failed for base64 image")
    return img

def build_clients(region: str, endpoint: str, ft_version: str) -> Tuple[ft_client.FtClient, CommonClient]:
    sid = os.getenv("TENCENTCLOUD_SECRET_ID")
    sk = os.getenv("TENCENTCLOUD_SECRET_KEY")
    if not sid or not sk:
        raise SystemExit(
            "Missing secrets. Please set env vars:\n"
            "  export TENCENTCLOUD_SECRET_ID='...'\n"
            "  export TENCENTCLOUD_SECRET_KEY='...'\n"
        )

    cred = credential.Credential(sid, sk)
    httpProfile = HttpProfile()
    httpProfile.endpoint = endpoint
    clientProfile = ClientProfile()
    clientProfile.httpProfile = httpProfile

    ft = ft_client.FtClient(cred, region, clientProfile)
    try:
        common = CommonClient(credential=cred, region=region, service="ft", version=ft_version, profile=clientProfile)
    except TypeError:
        common = CommonClient(cred, region, "ft", ft_version, clientProfile)
    return ft, common

def common_call_json(common: CommonClient, action: str, params: dict) -> dict:
    if hasattr(common, "call_json"):
        return common.call_json(action, params)
    return json.loads(common.call(action, params))

def change_age_pic_base64(ft: ft_client.FtClient, img_b64: str, age: int) -> str:
    req = models.ChangeAgePicRequest()
    params = {"Image": img_b64, "AgeInfos": [{"Age": int(age)}], "RspImgType": "base64"}
    req.from_json_string(json.dumps(params))
    resp = ft.ChangeAgePic(req)
    out_b64 = getattr(resp, "ResultImage", "")
    if not out_b64:
        raise RuntimeError(f"ChangeAgePic empty ResultImage for age={age}")
    return out_b64

def face_cartoon_pic_base64(ft: ft_client.FtClient, img_b64: str, disable_global_effect: bool = False) -> str:
    req = models.FaceCartoonPicRequest()
    params = {"Image": img_b64, "RspImgType": "base64"}
    if disable_global_effect:
        params["DisableGlobalEffect"] = "true"
    req.from_json_string(json.dumps(params))
    resp = ft.FaceCartoonPic(req)
    out_b64 = getattr(resp, "ResultImage", "")
    if not out_b64:
        raise RuntimeError("FaceCartoonPic empty ResultImage")
    return out_b64

def swap_gender_pic_base64(ft: ft_client.FtClient, img_b64: str, direction: int) -> str:
    req = models.SwapGenderPicRequest()
    params = {"Image": img_b64, "GenderInfos": [{"Gender": int(direction)}], "RspImgType": "base64"}
    req.from_json_string(json.dumps(params))
    resp = ft.SwapGenderPic(req)
    out_b64 = getattr(resp, "ResultImage", "")
    if not out_b64:
        raise RuntimeError(f"SwapGenderPic empty ResultImage direction={direction}")
    return out_b64

def morph_face_submit(common: CommonClient, images_b64_list: List[str], fps: int, out_w: int, out_h: int,
                     tempo: float, morph_time: float) -> str:
    out_w = max(128, min(int(out_w), 1280))
    out_h = max(128, min(int(out_h), 1280))
    params = {
        "Images": images_b64_list,
        "GradientInfos": [{"Tempo": float(tempo), "MorphTime": float(morph_time)}],
        "Fps": int(fps),
        "OutputType": 0,
        "OutputWidth": out_w,
        "OutputHeight": out_h,
    }
    raw = common_call_json(common, "MorphFace", params)
    job_id = raw.get("Response", {}).get("JobId")
    if not job_id:
        raise RuntimeError(f"MorphFace response missing JobId: {raw}")
    return job_id

def query_morph_job(common: CommonClient, job_id: str) -> dict:
    raw = common_call_json(common, "QueryFaceMorphJob", {"JobId": job_id})
    return raw.get("Response", {})
