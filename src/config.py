# -*- coding: utf-8 -*-
"""
Centralized configuration (camera / ROI / blending / Tencent Cloud / outputs).

Camera defaults:
- Device: /dev/video2
- Resolution: 1280x720
- FPS: 30
"""
DEFAULTS = {
    # UI: 限制日志最大行数，避免长时间运行占用过多内存
    "max_log_lines": 500,

    # Tencent Cloud
    "region": "ap-guangzhou",
    "endpoint": "ft.tencentcloudapi.com",
    "ft_version": "2020-03-04",

    # Output
    "out_dir": "./outputs",

    # Camera (Linux V4L2)
    "cam_device": "/dev/video2",
    # 建议：优先用稳定设备路径（避免 /dev/videoX 变动）
    # 例如：/dev/v4l/by-id/usb-XXXX-video-index0
  # 明确使用 video2
    "cam_index_fallback": 2,      # 如果用 device 打不开，退化到 index
    "cam_width": 1280,
    "cam_height": 720,
    "cam_fps": 30,

    # Input quality
    "jpeg_quality": 95,
    "api_input_max_side": 720,

    # Face ROI
    "enable_face_roi": True,
    "roi_margin": 0.50,     # 更自然：适当更大一点
    "min_face_size": 90,

    # Blend
    "blend_mode": "seamless",  # "seamless" | "feather" | "none"
    "feather_sigma": 9.0,
    "color_match_lab": True,  # 关键：降低贴图感（肤色断层）

    # Age morph
    "ages": [15, 30, 45, 60, 75],  # 2~5 个
    "morph_fps": 12,
    "tempo": 1.0,
    "morph_time": 1.0,
    "show_each_age_seconds": 0.8,
    # 年龄渐变：每张图保持显示的最大时长（秒）。实际会在下一张生成时被覆盖；最后一张会保持到视频播放开始。
    "age_preview_hold_seconds": 3600.0,

    # Anime
    "anime_show_seconds": 3.0,
    "anime_disable_global_effect": False,

    # Gender
    "gender_duration_seconds": 4.0,
    "gender_full_image": True,      # 关键：性别转换改为处理整张图
    "gender_global_color_match": True,
    # Gender swap target: 0=female, 1=male (single output)
    "gender_target": 0,
    # Gender swap display duration (seconds)
    "gender_show_seconds": 4.0,  # 可选：整图颜色/亮度匹配到原图，减少色偏
    "gender_toggle_interval": 1.0,

    # Download
    "dl_timeout": 30,
    "dl_retries": 8,
}
