# -*- coding: utf-8 -*-
import os
import time
import urllib.request
import urllib.error

def force_https(url: str) -> str:
    if url.startswith("http://"):
        return "https://" + url[len("http://"):]
    return url

def head_content_length(url: str, timeout: int = 20) -> int:
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        cl = r.headers.get("Content-Length")
        return int(cl) if cl else -1

def download_https_overwrite(url: str, out_path: str, timeout: int = 30, retries: int = 8) -> None:
    """
    Robust download helper: HTTP->HTTPS fallback, overwrite, retry, validate by content-length when available.
    """
    url = force_https(url)
    if os.path.exists(out_path):
        os.remove(out_path)

    total = -1
    try:
        total = head_content_length(url, timeout=timeout)
    except Exception:
        pass

    downloaded = 0
    for attempt in range(1, retries + 1):
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                with open(out_path, "wb") as f:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)

            if total > 0 and downloaded < total:
                raise RuntimeError(f"Incomplete download: {downloaded}/{total}")
            return
        except (urllib.error.URLError, ConnectionResetError, TimeoutError, RuntimeError):
            if os.path.exists(out_path):
                try:
                    os.remove(out_path)
                except Exception:
                    pass
            downloaded = 0
            time.sleep(min(2 * attempt, 10))

    raise RuntimeError(f"Download failed after {retries} attempts. URL={url}")
