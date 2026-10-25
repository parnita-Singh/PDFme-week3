# PDFme progress

## Phase 1 — Compression at a fixed resolution
- [x] `pdftoolkit/compress.py` with `compress_pdf(..., max_dpi=150, jpeg_quality=90)`
- [x] CLI: `python -m pdftoolkit compress input.pdf output.pdf --max-dpi 150 --quality 90 --report report.json`
- [x] Tests: output opens, same page count/sizes, smaller than sample, below-max-DPI images unchanged, original hash unchanged
- [x] Tests run at this checkpoint — **5 passed** (`python -m pytest -q`, 0.69s)

```
.....                                                                    [100%]
5 passed in 0.69s
```

CLI on `samples/test_banner.pdf` (`--max-dpi 150 --quality 90`): 7 350 659 → 575 159 bytes; both rasters downsampled; original file not modified.

## Phase 2 — Compress to a target size
- [ ] Not started

## Phase 3 — Merge and split
- [ ] Not started

## Phase 4 — Background removal (rembg)
- [ ] Not started

## Phase 5 — Optional Gemma page classifier
- [ ] Not started

## Phase 6 — Gradio UI
- [ ] Not started

## Documentation
- [x] README.md current for Phase 1
- [x] NOTES.md records unprompted decisions
- [x] OPEN_AI_NOTES.md
- [ ] benchmark.py (later)
