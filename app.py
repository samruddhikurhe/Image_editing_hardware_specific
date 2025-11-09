import os
from flask import Flask, render_template, send_file, request, jsonify
from preprocess import fast_preview_raw, full_process_raw, apply_filters_to_jpeg, CACHE_DIR
from hardware import processing_policy
from concurrent.futures import ThreadPoolExecutor
import threading

# Configure paths
RAW_DEFAULT = os.path.join("data", "raw", "RAW_SONY_ILCE-7RM2.ARW")
os.makedirs(os.path.dirname(RAW_DEFAULT), exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="templates")
executor = ThreadPoolExecutor(max_workers=2)
TASKS = {}       # store background results
LATEST = {}      # store latest preview/full basenames

def ensure_preview_on_start():
    """
    Generate a fast preview at server startup (synchronous, but fast).
    Also schedule the full-res processing in background.
    """
    global LATEST, TASKS
    if not os.path.exists(RAW_DEFAULT):
        # nothing to do if RAW not present
        LATEST["preview"] = None
        LATEST["full"] = None
        return

    # Use default filters (or you can customize)
    preset_filters = {
        "saturation": 1.15,
        "warmth": 1.02,
        "brightness": 1.0,
        "contrast": 1.02,
        "sharpen": 0.0
    }

    try:
        preview_path = fast_preview_raw(RAW_DEFAULT, filters_config=preset_filters, max_dim=1024, quality=80)
        LATEST["preview"] = os.path.basename(preview_path)
    except Exception as e:
        LATEST["preview"] = None
        print("Preview generation failed at startup:", e)
        return

    # Background full processing
    def run_full():
        try:
            full_path = full_process_raw(RAW_DEFAULT, filters_config=preset_filters, quality=92)
            LATEST["full"] = os.path.basename(full_path)
            TASKS["last"] = {"preview": LATEST.get("preview"), "full": LATEST.get("full")}
            print("Full processing complete:", LATEST["full"])
        except Exception as e:
            TASKS["last"] = {"preview": LATEST.get("preview"), "full": None, "error": str(e)}
            print("Full processing error:", e)

    executor.submit(run_full)

# Generate preview during module import/startup (fast on most machines)
ensure_preview_on_start()

@app.route("/")
def index():
    policy = processing_policy()
    # pass preview filename to template so page can show it immediately
    preview_fname = LATEST.get("preview")
    full_fname = LATEST.get("full")
    return render_template("viewer.html", raw_default=RAW_DEFAULT, policy=policy,
                           preview_fname=preview_fname, full_fname=full_fname)

@app.route("/start", methods=["POST"])
def start():
    """
    Trigger reprocessing manually (e.g., after changing raw_path in the UI).
    Returns preview filename (immediate) and schedules full processing in background.
    Body: { "raw_path": "<path>", "preset_filters": {...} }
    """
    data = request.get_json(force=True)
    raw_path = data.get("raw_path", RAW_DEFAULT)
    preset_filters = data.get("preset_filters", None)

    if not os.path.exists(raw_path):
        return jsonify({"error": "raw not found", "path": raw_path}), 400

    try:
        preview_path = fast_preview_raw(raw_path, filters_config=preset_filters, max_dim=1024, quality=80)
    except Exception as e:
        return jsonify({"error": f"preview failed: {e}"}), 500

    preview_fname = os.path.basename(preview_path)
    LATEST["preview"] = preview_fname

    def run_full():
        try:
            full_path = full_process_raw(raw_path, filters_config=preset_filters, quality=92)
            LATEST["full"] = os.path.basename(full_path)
            TASKS["last"] = {"preview": LATEST.get("preview"), "full": LATEST.get("full")}
        except Exception as e:
            TASKS["last"] = {"preview": LATEST.get("preview"), "full": None, "error": str(e)}

    executor.submit(run_full)

    return jsonify({"preview_fname": preview_fname, "status": "processing"})

@app.route("/image")
def image():
    """
    Serve images from CACHE_DIR by basename param 'f'.
    Example: /image?f=preview_abcd1234.jpg
    """
    fname = request.args.get("f")
    if not fname:
        return "filename required", 400
    safe = os.path.basename(fname)
    path = os.path.join(CACHE_DIR, safe)
    if not os.path.exists(path):
        return "Not found", 404
    return send_file(path, mimetype="image/jpeg")

@app.route("/status")
def status():
    """
    Return processing status: whether full image is ready and the cached basenames.
    """
    last = TASKS.get("last")
    if not last:
        # still processing or no full processed yet; return latest preview if available
        resp = {"done": False, "preview": LATEST.get("preview")}
        if LATEST.get("full"):
            resp["full"] = LATEST.get("full")
        return jsonify(resp)
    resp = {"done": bool(last.get("full")), "preview": last.get("preview")}
    if last.get("full"):
        resp["full"] = last.get("full")
    if last.get("error"):
        resp["error"] = last.get("error")
    return jsonify(resp)

@app.route("/apply_filter", methods=["POST"])
def apply_filter():
    """
    Apply filter to an existing cached image (preview or full) and return new edited basename.
    Body: {"filter": {...}, "image_fname": "<basename>"}
    """
    data = request.get_json(force=True)
    filter_cfg = data.get("filter", {})
    image_fname = data.get("image_fname")

    if not image_fname:
        return jsonify({"error": "image_fname required"}), 400

    image_path = os.path.join(CACHE_DIR, os.path.basename(image_fname))
    if not os.path.exists(image_path):
        return jsonify({"error": "image not found"}), 404

    try:
        out_path = apply_filters_to_jpeg(image_path, filter_cfg)
    except Exception as e:
        return jsonify({"error": f"apply filter failed: {e}"}), 500

    return jsonify({"edited": os.path.basename(out_path)})

if __name__ == "__main__":
    # Run development server
    # threaded=True helps background thread + request handling during development
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)
