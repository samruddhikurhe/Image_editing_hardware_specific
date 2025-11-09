// static/main.js
document.addEventListener("DOMContentLoaded", () => {
  const startBtn = document.getElementById("startBtn");
  const rawPathInput = document.getElementById("rawPath");
  const theImage = document.getElementById("theImage");
  const sat = document.getElementById("sat");
  const warm = document.getElementById("warm");
  const bright = document.getElementById("bright");
  const contrast = document.getElementById("contrast");
  const applyPreview = document.getElementById("applyPreview");
  const applyFull = document.getElementById("applyFull");
  const spinner = document.getElementById("spinner");
  const zoomIn = document.getElementById("zoomIn");
  const zoomOut = document.getElementById("zoomOut");
  const resetZoom = document.getElementById("resetZoom");
  const zoomLevel = document.getElementById("zoomLevel");
  const imageWrap = document.getElementById("imageWrap");

  let currentPreview = SERVER_PREVIEW || null;
  let currentFull = SERVER_FULL || null;
  let scale = 0.08;
  let translate = {x:0, y:0};
  let dragging = false;
  let dragStart = {x:0, y:0};
  let translateStart = {x:0, y:0};

  function setSpinner(vis) {
    spinner.style.display = vis ? "block" : "none";
  }

  function setImageSrcFromBasename(basename) {
    if (!basename) {
      theImage.src = "";
      return;
    }
    // Append timestamp to avoid cached stale image
    theImage.onload = () => {
      // reset translate so centering is consistent if you want
      translate = {x:0, y:0};
      updateTransform();
    };

  theImage.src = `/image?f=${encodeURIComponent(basename)}&t=${Date.now()}`;
  }

  // If server provided a preview at render time, show it immediately
  if (currentPreview) {
    setImageSrcFromBasename(currentPreview);
  }

  // Poll status so we can swap to full image once ready
  async function pollStatus() {
    try {
      const resp = await fetch("/status");
      const j = await resp.json();
      if (j.done && j.full) {
        currentFull = j.full;
        setImageSrcFromBasename(currentFull);
        // update current preview pointer
        currentPreview = j.preview || currentPreview;
        return;
      }
      // if preview is provided in status, but full not ready, ensure preview displayed
      if (j.preview && !theImage.src) {
        setImageSrcFromBasename(j.preview);
      }
    } catch (e) {
      console.error("status poll error", e);
    } finally {
      setTimeout(pollStatus, 2000);
    }
  }
  pollStatus();

  startBtn.onclick = async () => {
    setSpinner(true);
    const raw_path = rawPathInput.value;
    const res = await fetch("/start", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({raw_path})
    });
    const j = await res.json();
    if (j.preview_fname) {
      currentPreview = j.preview_fname;
      setImageSrcFromBasename(currentPreview);
    } else if (j.error) {
      alert("Start error: " + j.error);
    }
    setSpinner(false);
  };

  // Instant visual preview using CSS filters (fast)
  applyPreview.onclick = () => {
    const satV = sat.value;
    const warmV = warm.value;
    const brightV = bright.value;
    const contrastV = contrast.value;
    // Warmth not directly supported via CSS, approximate by overlay using filter + mix-blend not used here.
    theImage.style.filter = `brightness(${brightV}) contrast(${contrastV}) saturate(${satV})`;
  };

  // Apply filter to full (or preview if full not ready)
  applyFull.onclick = async () => {
    const target = currentFull || currentPreview;
    if (!target) {
      alert("No image loaded yet.");
      return;
    }
    const filter = {
      "saturation": parseFloat(sat.value),
      "warmth": parseFloat(warm.value),
      "brightness": parseFloat(bright.value),
      "contrast": parseFloat(contrast.value)
    };
    setSpinner(true);
    const res = await fetch("/apply_filter", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({filter, image_fname: target})
    });
    const j = await res.json();
    setSpinner(false);
    if (j.edited) {
      // show edited image
      setImageSrcFromBasename(j.edited);
      // make edited the new preview pointer
      currentPreview = j.edited;
    } else {
      alert("Edit failed: " + JSON.stringify(j));
    }
  };

  // Zoom / pan logic
  function updateTransform() {
    theImage.style.transform = `translate(${translate.x}px, ${translate.y}px) scale(${scale})`;
    zoomLevel.textContent = scale.toFixed(2) + "x";
  }

  zoomIn.onclick = () => { scale *= 1.1; updateTransform(); };
  zoomOut.onclick = () => { scale /= 1.1; updateTransform(); };
  resetZoom.onclick = () => { scale = 0.08; translate = {x:0,y:0}; updateTransform(); };

  // Mouse wheel zoom
  imageWrap.addEventListener("wheel", (e) => {
    e.preventDefault();
    const prev = scale;
    if (e.deltaY < 0) scale *= 1.1; else scale /= 1.1;
    // keep scale min/max
    scale = Math.max(0.2, Math.min(8.0, scale));
    updateTransform();
  }, {passive:false});

  // Drag to pan
  theImage.addEventListener("mousedown", (e) => {
    dragging = true;
    dragStart = {x: e.clientX, y: e.clientY};
    translateStart = {x: translate.x, y: translate.y};
    theImage.style.cursor = "grabbing";
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const dx = e.clientX - dragStart.x;
    const dy = e.clientY - dragStart.y;
    translate.x = translateStart.x + dx;
    translate.y = translateStart.y + dy;
    updateTransform();
  });
  window.addEventListener("mouseup", (e) => {
    dragging = false;
    theImage.style.cursor = "grab";
  });

  // Touch: pan & pinch
  let lastTouchDist = null;
  imageWrap.addEventListener("touchstart", (e) => {
    if (e.touches.length === 1) {
      dragging = true;
      dragStart = {x: e.touches[0].clientX, y: e.touches[0].clientY};
      translateStart = {x: translate.x, y: translate.y};
    } else if (e.touches.length === 2) {
      // pinch start
      lastTouchDist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
    }
  }, {passive:true});

  imageWrap.addEventListener("touchmove", (e) => {
    if (e.touches.length === 1 && dragging) {
      const dx = e.touches[0].clientX - dragStart.x;
      const dy = e.touches[0].clientY - dragStart.y;
      translate.x = translateStart.x + dx;
      translate.y = translateStart.y + dy;
      updateTransform();
    } else if (e.touches.length === 2) {
      // pinch to zoom
      const dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      if (lastTouchDist) {
        const ratio = dist / lastTouchDist;
        scale *= ratio;
        scale = Math.max(0.2, Math.min(8.0, scale));
        updateTransform();
      }
      lastTouchDist = dist;
    }
  }, {passive:true});

  imageWrap.addEventListener("touchend", (e) => {
    if (e.touches.length === 0) {
      dragging = false;
      lastTouchDist = null;
    }
  });

  // set initial image style for panning cursor
  theImage.style.cursor = "grab";
});
