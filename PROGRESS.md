# PDFme progress

Last updated: 2026-10-25

## Status

All planned phases are built and tested. The remaining work is checking the results on the real banner, the two documents below, and the submission post.

Expected test total on your machine: **135 passed**, with `python -m pytest -q`.

## Phases

- [x] **Phase 1: compression at a fixed resolution** (`compress`, inventory fixes). 20 tests.
- [x] **Print copy without editing data** (`python -m pdftoolkit.editing`). 10 tests.
- [x] **Phase 2: compress to a size limit** (`fit`, and its command-line entry). 17 tests.
- [x] **Phase 3: merge and split** (`merge`, `split`). 15 tests.
- [x] **Phase 4: background removal and pipeline** (`removebg`, `pipeline`). 29 tests.
- [x] **Phase 5: Gemma page labels** (`classify`, `removebg --classify`). 20 tests.
- [x] **Phase 6: web page** (`app.py`). 24 tests.

Running total: 20 + 10 + 17 + 15 + 29 + 20 + 24 = **135**.

## Checked on real files

- [x] **Banner print copy:** B---Standee_3x6 [--- for not disclosing the name], 515.9 MB → 39.0 MB. Editing data removed from page 1. The four 300 dpi images are unchanged.
- [x] **Banner size fit:** `fit --max-mb 2000` gives 284.9 MB at 300 dpi, quality 92. The first setting tried already fits.
- [x] **Web page:** tested by hand and working.

## Checked with test data only

- [x] **Background removal:** with the real model on a synthetic image, the background becomes transparent (alpha 0 at the corners) and the subject stays opaque (alpha 254 in the centre).
- [x] **Gemma labels:** tested with a fake model. Each label, unclear reply and Ollama-down case is covered.

## Open before submission

- [ ] **Print copy, visual check:** open `print.pdf` next to the original at full size and compare the banner.
- [ ] **Background removal on the banner:** run it on the real file and check each result on screen.
- [ ] **Gemma labels on the banner:** run `classify` and check each label against the design.
- [ ] **Offline check:** with both models already downloaded, turn off the internet and run `pipeline` once.
- [ ] **`benchmark.py`:** times the same inputs with the chosen settings. No paid or closed APIs.
- [ ] **`OPEN_AI_NOTES.md`:** lists each open component, what it does in the project, and why running locally matters.
- [ ] **`.gitignore`:** add `outputs/` and `.venv/` before the first commit.
- [ ] **DEV submission post:** after the items above.

## Decisions

Each decision, and why it was made, is in `NOTES.md`. The phase install guides have the lines to add to it.
