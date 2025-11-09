import cv2
import numpy as np

def to_umat_if_needed(img, use_opencl):
    if use_opencl:
        try:
            return cv2.UMat(img)
        except Exception:
            return img
    return img

def from_umat_if_needed(img):
    if isinstance(img, cv2.UMat):
        return img.get()
    return img

def apply_saturation(img, factor=1.2, use_opencl=False):
    """factor >1 increases saturation, <1 decreases"""
    umat = to_umat_if_needed(img, use_opencl)
    img_cvt = cv2.cvtColor(umat, cv2.COLOR_BGR2HSV)
    img_arr = from_umat_if_needed(img_cvt).astype(np.float32)
    img_arr[...,1] = np.clip(img_arr[...,1] * factor, 0, 255)
    img_arr = img_arr.astype(np.uint8)
    out = cv2.cvtColor(img_arr, cv2.COLOR_HSV2BGR)
    return out

def apply_warmth(img, strength=1.05, use_opencl=False):
    """Warmth: boost reds slightly and reduce blues slightly. strength ~ [0.9..1.2]"""
    umat = to_umat_if_needed(img, use_opencl)
    arr = from_umat_if_needed(umat).astype(np.float32)
    # BGR ordering in OpenCV
    arr[...,2] = np.clip(arr[...,2] * strength, 0, 255)  # R
    arr[...,0] = np.clip(arr[...,0] * (2.0 - strength), 0, 255)  # B slightly down
    return arr.astype(np.uint8)

def adjust_brightness_contrast(img, brightness=1.0, contrast=1.0, use_opencl=False):
    """brightness: multiplier (1.0 no-change), contrast: multiplier"""
    umat = to_umat_if_needed(img, use_opencl)
    arr = from_umat_if_needed(umat).astype(np.float32)
    arr = arr * contrast
    arr = arr + (brightness - 1.0) * 128
    arr = np.clip(arr, 0, 255)
    return arr.astype(np.uint8)

def sharpen(img, strength=1.0, use_opencl=False):
    umat = to_umat_if_needed(img, use_opencl)
    arr = from_umat_if_needed(umat)
    kernel = np.array([[0, -1, 0], [-1, 5 + strength, -1], [0, -1, 0]], dtype=np.float32)
    sharp = cv2.filter2D(arr, -1, kernel)
    return sharp
