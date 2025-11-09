import os
import psutil
import cv2

def cpu_count():
    return os.cpu_count() or 1

def battery_percent():
    try:
        b = psutil.sensors_battery()
        if b is None:
            return None
        return int(b.percent)
    except Exception:
        return None

def have_opencl():
    try:
        return cv2.ocl.haveOpenCL()
    except Exception:
        return False

def enable_opencl():
    try:
        if have_opencl():
            cv2.ocl.setUseOpenCL(True)
            return True
    except Exception:
        pass
    return False

def processing_policy():
    """
    Decide policy values based on hardware & battery:
      - preview_max_dim: max preview size (fast)
      - n_workers: number of worker threads for heavy tasks
      - use_opencl: bool
    """
    cpu = cpu_count()
    battery = battery_percent()
    opencl = enable_opencl()

    # default policy
    preview_max_dim = 1024
    if cpu >= 8:
        n_workers = min(6, cpu - 1)
    elif cpu >= 4:
        n_workers = cpu - 1
    else:
        n_workers = 1

    # if battery is low, reduce workers but keep preview fast
    if battery is not None and battery <= 20:
        # keep preview fast, reduce heavy parallelism
        n_workers = max(1, int(n_workers / 2))
        # prefer opencl (hardware acceleration) if present
        use_opencl = opencl
    else:
        use_opencl = opencl

    return {
        "cpu_count": cpu,
        "battery": battery,
        "use_opencl": use_opencl,
        "n_workers": n_workers,
        "preview_max_dim": preview_max_dim
    }
