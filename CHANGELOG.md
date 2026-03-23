# Changelog

## v1.1

### New Feature: Segment Folder

A standalone batch segmentation tool accessible from the sidebar. Analyse an entire directory of microscopy images in one go without needing to create a culture. Added this as an easy way to use instantly apply CellPose segmentation and get confluency measurements of existing image sets.
- **Batch processing**: Select an input folder containing images (`.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`) and all will be segmented sequentially.
- **Method selection**: Choose between Cellpose (deep learning) or Otsu (classical thresholding) before starting.
- **CSV output**: A `results.csv` file is written to the output directory with columns `img_name`, `method`, and `confluency`.
- **Organised output**: Segmentation images (raw, overlay, outline PNGs) are saved into an `images/` subfolder within the output directory, keeping the CSV at the top level.

Other:

- **Progress Animation**: Added progress animation so users will know that processing is taking place. Cellpose takes time in CPU-only mode so it could seem like the system was hung.

## v1.0

Initial release.

- Segmentation - Use either Cellpose (deep learning) or Otsu (traditional thresholding).
- Confluency tracking - Confluency plots with passage annotations and colour-coded proliferation cycles
- Logging - View per-passage growth status, compare proliferation dynamics
- Cell lines & organoids - works with any brightfield culture imaging workflow
- Measurement log - full history with date, passage, confluency, segmentation method, and delta tracking
- Image review - raw, mask overlay, and cell outline views for every measurement
- Editable records - correct dates, passages, or replace images after the fact
- File-based storage - each culture is a self-contained folder, easy to back up or share
- Multi-user ready - host on a shared machine or host on a server and access from anywhere
