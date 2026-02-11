# -*- coding: utf-8 -*-
"""
Centralized configuration (camera / ROI / blending / Tencent Cloud / outputs).

Camera defaults:
- Device: /dev/video2
- Resolution: 1280x720
- FPS: 30
"""
DEFAULTS = {
    # UI: Limit the maximum number of log lines
    "max_log_lines": 500,

    # Tencent Cloud
    "region": "ap-guangzhou",
    "endpoint": "ft.tencentcloudapi.com",
    "ft_version": "2020-03-04",

    # Output
    "out_dir": "./outputs",

    # Camera (Linux V4L2)
    "cam_device": "/dev/video2",
  # Clearly use "video2"
    "cam_index_fallback": 2,      
    "cam_width": 1280,
    "cam_height": 720,
    "cam_fps": 30,

    # Input quality
    "jpeg_quality": 95,
    "api_input_max_side": 720,

    # Face ROI
    "enable_face_roi": True,
    "roi_margin": 0.50,     
    "min_face_size": 90,

    # Blend
    "blend_mode": "seamless",  # "seamless" | "feather" | "none"
    "feather_sigma": 9.0,
    "color_match_lab": True,  

    # Age morph
    "ages": [15, 30, 45, 60, 75],  # 2 to 5
    "morph_fps": 12,
    "tempo": 1.0,
    "morph_time": 1.0,
    "show_each_age_seconds": 0.8,
    # Age variation: The maximum duration (in seconds) that each image is displayed. It will be overwritten when the next image is generated; the last image will remain until the video starts playing.
    "age_preview_hold_seconds": 3600.0,

    # Anime
    "anime_show_seconds": 3.0,
    "anime_disable_global_effect": False,

    # Gender
    "gender_duration_seconds": 4.0,
    "gender_full_image": True,      
    "gender_global_color_match": True,
    # Gender swap target: 0=female, 1=male (single output)
    "gender_target": 0,
    # Gender swap display duration (seconds)
    "gender_show_seconds": 4.0,  
    "gender_toggle_interval": 1.0,

    # Download
    "dl_timeout": 30,
    "dl_retries": 8,
}
