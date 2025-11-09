import os
import hashlib
import uuid
import rawpy
import numpy as np
from PIL import Image
import cv2
from filters import apply_saturation, apply_warmth, adjust_brightness_contrast, sharpen
from hardware import processing_policy

# Ensure cache dir exists
CACHE_DIR = os.path.join("data", "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

def file_hash_of_raw_and_filters(raw_path, filters_config):
    """Create a stable cache key from file metadata and filters config."""
    st = os.stat(raw_path)
    h = hashlib.sha256()
    # include path, size, mtime, and filter config string (sorted for determinism)
    h.update(raw_path.encode("utf-8"))
    h.update(str(st.st_size).encode("utf-8"))
    h.update(str(int(st.st_mtime)).encode("utf-8"))
    if filters_config:
        h.update(str(sorted(filters_config.items())).encode("utf-8"))
    return h.hexdigest()[:16]

def _save_cv2_jpeg(img_bgr, out_path, quality=85):
    """Save BGR numpy image to JPEG using cv2.imencode for speed."""
    try:
        ret, enc = cv2.imencode('.jpg', img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if ret:
            with open(out_path, 'wb') as f:
                f.write(enc.tobytes())
            return True
    except Exception:
        pass
    # fallback to PIL
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    Image.fromarray(rgb).save(out_path, 'JPEG', quality=quality, optimize=True)
    return True

def fast_preview_raw(raw_path, filters_config=None, max_dim=1024, quality=80):
    """
    Fast preview:
      - uses rawpy.postprocess with half_size=True and LINEAR demosaic for speed
      - applies light filters (CPU)
      - resizes to max_dim
      - caches the result by a key derived from file metadata + filters
    Returns preview_path (absolute path)
    """
    if filters_config is None:
        filters_config = {
            "saturation": 1.15,
            "warmth": 1.02,
            "brightness": 1.0,
            "contrast": 1.02,
            "sharpen": 0.0
        }

    key = file_hash_of_raw_and_filters(raw_path, filters_config)
    preview_fname = f"preview_{key}.jpg"
    preview_path = os.path.join(CACHE_DIR, preview_fname)
    if os.path.exists(preview_path):
        return preview_path

    # Load RAW and produce a fast preview (half size + linear demosaic)
    try:
        with rawpy.imread(raw_path) as raw:
            try:
                rgb = raw.postprocess(output_bps=8,
                                      half_size=True,
                                      no_auto_bright=True,
                                      use_camera_wb=True,
                                      demosaic_algorithm=rawpy.DemosaicAlgorithm.LINEAR)
            except Exception:
                # fallback to default fast postprocess
                rgb = raw.postprocess(output_bps=8, half_size=True, no_auto_bright=True)
    except Exception as e:
        raise RuntimeError(f"Failed to read RAW for preview: {e}")

    # Convert to BGR for OpenCV
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    # Ensure max dimension
    h, w = bgr.shape[:2]
    scale = min(1.0, float(max_dim) / max(h, w))
    if scale < 1.0:
        bgr = cv2.resize(bgr, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)

    # Apply quick filters on CPU for predictable latency
    proc = bgr
    if filters_config.get("saturation", 1.0) != 1.0:
        proc = apply_saturation(proc, factor=filters_config["saturation"], use_opencl=False)
    if filters_config.get("warmth", 1.0) != 1.0:
        proc = apply_warmth(proc, strength=filters_config["warmth"], use_opencl=False)
    if (filters_config.get("brightness", 1.0) != 1.0 or
            filters_config.get("contrast", 1.0) != 1.0):
        proc = adjust_brightness_contrast(proc,
                                         brightness=filters_config.get("brightness",1.0),
                                         contrast=filters_config.get("contrast",1.0),
                                         use_opencl=False)
    if filters_config.get("sharpen", 0) > 0:
        proc = sharpen(proc, strength=filters_config.get("sharpen",0), use_opencl=False)

    # Save compressed JPEG preview (fast)
    _save_cv2_jpeg(proc, preview_path, quality=quality)
    return preview_path

def full_process_raw(raw_path, filters_config=None, quality=92):
    """
    Full res processing (slower). Uses higher-quality demosaic (AHD if available),
    can use hardware policy (OpenCL) depending on hardware.processing_policy().
    Caches result and returns final JPEG path.
    """
    if filters_config is None:
        filters_config = {
            "saturation": 1.15,
            "warmth": 1.02,
            "brightness": 1.0,
            "contrast": 1.02,
            "sharpen": 0.5
        }

    key = file_hash_of_raw_and_filters(raw_path, filters_config)
    full_fname = f"full_{key}.jpg"
    full_path = os.path.join(CACHE_DIR, full_fname)
    if os.path.exists(full_path):
        return full_path

    policy = processing_policy()
    use_opencl = policy.get("use_opencl", False)

    # read full raw and use higher-quality demosaic where possible
    try:
        with rawpy.imread(raw_path) as raw:
            try:
                rgb = raw.postprocess(output_bps=8,
                                      no_auto_bright=False,
                                      use_camera_wb=True,
                                      demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD)
            except Exception:
                rgb = raw.postprocess(output_bps=8)
    except Exception as e:
        raise RuntimeError(f"Failed to read RAW for full processing: {e}")

    # Convert to BGR
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    # Apply filters; allow OpenCL usage depending on policy
    proc = bgr
    proc = apply_saturation(proc, factor=filters_config.get("saturation",1.0), use_opencl=use_opencl)
    proc = apply_warmth(proc, strength=filters_config.get("warmth",1.0), use_opencl=use_opencl)
    proc = adjust_brightness_contrast(proc,
                                     brightness=filters_config.get("brightness",1.0),
                                     contrast=filters_config.get("contrast",1.0),
                                     use_opencl=use_opencl)
    if filters_config.get("sharpen",0) > 0:
        proc = sharpen(proc, strength=filters_config.get("sharpen",0), use_opencl=use_opencl)

    # adapt JPEG quality by battery state to save I/O if battery is low
    battery = policy.get("battery")
    if battery is not None and battery <= 15:
        q = max(85, quality - 6)
    else:
        q = quality

    _save_cv2_jpeg(proc, full_path, quality=q)
    return full_path

# A helper to apply filters to an existing JPEG/preview image (used by /apply_filter)
def apply_filters_to_jpeg(image_path, filter_cfg, out_name=None, quality=90):
    """Load image_path (jpeg), apply filter_cfg (same keys as above), save to cache and return path."""
    if out_name is None:
        out_name = f"edit_{uuid.uuid4().hex[:8]}.jpg"
    out_path = os.path.join(CACHE_DIR, out_name)

    img = cv2.imread(image_path)
    if img is None:
        raise RuntimeError("Failed to read image for editing.")

    # Apply filters quickly on CPU for responsiveness
    proc = img
    if filter_cfg.get("saturation", 1.0) != 1.0:
        proc = apply_saturation(proc, factor=filter_cfg["saturation"], use_opencl=False)
    if filter_cfg.get("warmth", 1.0) != 1.0:
        proc = apply_warmth(proc, strength=filter_cfg["warmth"], use_opencl=False)
    if (filter_cfg.get("brightness", 1.0) != 1.0 or
            filter_cfg.get("contrast", 1.0) != 1.0):
        proc = adjust_brightness_contrast(proc,
                                         brightness=filter_cfg.get("brightness",1.0),
                                         contrast=filter_cfg.get("contrast",1.0),
                                         use_opencl=False)
    if filter_cfg.get("sharpen", 0) > 0:
        proc = sharpen(proc, strength=filter_cfg.get("sharpen",0), use_opencl=False)

    _save_cv2_jpeg(proc, out_path, quality=quality)
    return out_path
