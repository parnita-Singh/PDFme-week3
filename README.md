# PDFme

Local, offline toolkit for large design PDFs (for example Canva exports with full-page banners): compress images, remove backgrounds with an open model, merge, and split under a size cap (default 2 GB, WhatsApp’s document limit).

Nothing is uploaded. The only network use later will be a **one-time** download of AI model weights; after that the app is meant to run with no internet.

## Status

Phase 1 is implemented: compression at a maximum effective DPI.

## Install (Windows, macOS, Linux)

Python 3.11 or newer.

```bash
cd PDFme
python -m venv .venv
```

Windows:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS / Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Generate the sample PDF (needed for tests):

```bash
python make_sample.py
```

## Commands (Phase 1)

Inspect images and effective DPI:

```bash
python -m pdftoolkit inspect samples/test_banner.pdf --report inspect.json
```

Compress rasters above 150 DPI to 150 DPI JPEG quality 90:

```bash
python -m pdftoolkit compress samples/test_banner.pdf out.pdf --max-dpi 150 --quality 90 --report report.json
```

The original file is never overwritten. A JSON report and a `.txt` summary list each image’s pixels, DPI, bytes, and the action taken.

## Tests

```bash
python -m pytest
```

## Later phases (not in this checkpoint)

- Fit to a target file size
- Merge and split
- Background removal with rembg (default model `isnet-general-use`; first run downloads weights; vector Canva shapes are reported, not processed)
- Optional local Gemma classifier via Ollama
- Gradio UI bound to localhost

## Known limitations

- Vector backgrounds (shapes, not photos) are not raster-compressed and will not be removed in Phase 4.
- Very large files need enough RAM and disk for a second copy plus decoded bitmaps.
- Inline PDF images are not rewritten yet.
- Gemma is optional and unused in Phase 1.
