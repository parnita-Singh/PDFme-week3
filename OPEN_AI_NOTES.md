# Open components in PDFme

PDFme is a **local** toolkit. PDFs never leave the machine. No cloud APIs, uploads, telemetry, or accounts.

## In Phase 1
- **pikepdf** (open source, QPDF) — rewrite image streams without rasterising text or vectors.
- **pypdf** — reserved for merge/split (Phase 3).
- **Pillow** — LANCZOS downsample and JPEG encode.
- **pytest** — local tests.

## Planned (later phases)
- **rembg** + **onnxruntime** and the **ISNet** family of open models (`isnet-general-use` by default) — background removal on selected raster images. Weights download **once**, then the app is fully offline.
- **Ollama** + an open **Gemma** weight (Phase 5, optional) — local page labels only. If Ollama is not running, classification is skipped; nothing is sent to Google or any hosted API.
- **Gradio** — localhost-only UI (Phase 6).

## Why local
Banner PDFs from Canva often contain unpublished design work. Running compression and background removal on-device avoids uploading those files to a third-party renderer.
