# -*- coding: utf-8 -*-
import os
import time

def ensure_out_dir(path: str) -> str:
    path = (path or "").strip() or "."
    os.makedirs(path, exist_ok=True)
    return path

def ts_str() -> str:
    return time.strftime("%Y%m%d_%H%M%S")
