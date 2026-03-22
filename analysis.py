import os
import numpy as np
from PIL import Image

# Try to load Cellpose at module level
try:
    from cellpose import models as cellpose_models
    cellpose_model = cellpose_models.Cellpose(model_type="cyto3", gpu=False)
    HAS_CELLPOSE = True
except Exception:
    cellpose_model = None
    HAS_CELLPOSE = False


MAX_DIM = 1024  # all images are downscaled to this before any processing


def downscale(img, max_dim):
    """Downscale so the longest side is at most max_dim. No-op if already small."""
    w, h = img.size
    if max(w, h) <= max_dim:
        return img
    scale = max_dim / max(w, h)
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


def otsu_threshold(gray_array):
    """Compute optimal threshold via between-class variance maximisation."""
    hist, _ = np.histogram(gray_array.ravel(), bins=256, range=(0, 256))
    total = gray_array.size
    sum_total = np.dot(np.arange(256), hist)

    best_thresh = 0
    best_var = 0.0
    weight_bg = 0
    sum_bg = 0.0

    for t in range(256):
        weight_bg += hist[t]
        if weight_bg == 0:
            continue
        weight_fg = total - weight_bg
        if weight_fg == 0:
            break
        sum_bg += t * hist[t]
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_total - sum_bg) / weight_fg
        var_between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
        if var_between > best_var:
            best_var = var_between
            best_thresh = t

    return best_thresh


def segment_otsu(img_array):
    """Return a boolean mask where True = cell pixel (darker regions in brightfield)."""
    if img_array.ndim == 3:
        gray = np.mean(img_array[:, :, :3], axis=2).astype(np.uint8)
    else:
        gray = img_array.astype(np.uint8)
    thresh = otsu_threshold(gray)
    return gray < thresh


def segment_cellpose(img_array):
    """Return a boolean mask of detected cell regions via Cellpose."""
    masks, _flows, _styles, _diams = cellpose_model.eval(
        img_array,
        diameter=None,
        channels=[0, 0],
        flow_threshold=0.4,
    )
    return masks > 0


def make_overlay(img_array, mask):
    """Return an RGB array with a green tint on cell regions."""
    overlay = img_array.copy()
    if overlay.shape[2] == 4:
        overlay = overlay[:, :, :3]
    overlay[mask, 1] = np.clip(overlay[mask, 1].astype(np.int16) + 120, 0, 255).astype(np.uint8)
    return overlay


def make_outline_image(img_array, mask):
    """Return an RGB array with cell boundary pixels drawn in accent green."""
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    eroded = (
        padded[1:-1, 1:-1]
        & padded[:-2, 1:-1]
        & padded[2:, 1:-1]
        & padded[1:-1, :-2]
        & padded[1:-1, 2:]
    )
    outline_mask = mask & ~eroded

    result = img_array.copy()
    if result.shape[2] == 4:
        result = result[:, :, :3]
    result[outline_mask] = [0, 229, 160]
    return result


def analyse_image(image_path, output_dir, method="cellpose"):

    img = downscale(Image.open(image_path).convert("RGB"), MAX_DIM)
    img_array = np.array(img)

    if method == "cellpose":
        if not HAS_CELLPOSE:
            raise RuntimeError("Cellpose is not installed")
        mask = segment_cellpose(img_array)
        used_method = "cellpose"
    else:
        mask = segment_otsu(img_array)
        used_method = "otsu"

    confluency = float(np.sum(mask) / mask.size * 100)

    base = os.path.splitext(os.path.basename(image_path))[0]

    overlay_path = os.path.join(output_dir, f"{base}_overlay.png")
    Image.fromarray(make_overlay(img_array, mask)).save(overlay_path)

    outline_path = os.path.join(output_dir, f"{base}_outline.png")
    Image.fromarray(make_outline_image(img_array, mask)).save(outline_path)

    raw_png_path = os.path.join(output_dir, f"{base}_raw.png")
    img.save(raw_png_path)

    return {
        "confluency": round(confluency, 2),
        "overlay_path": overlay_path,
        "outline_path": outline_path,
        "raw_png_path": raw_png_path,
        "method": used_method,
    }
