# PDFme

A local, offline PDF toolkit for large print designs. It compresses big PDFs to a size you can share, removes image backgrounds with an open-source AI model, labels pages with a local Gemma model, and merges and splits PDFs by size.

Everything runs on your own computer. Your files are never uploaded, and the app needs no account, no cloud service and no internet connection after the one-time downloads described below.

## Why local and private

Design files often contain client work that must not leave the building. PDFme works on your machine only:

- Your PDFs are read and written on your disk.
- Background removal uses an open model (rembg with isnet-general-use) that runs on your CPU.
- Page labels come from Gemma, an open-weight model that runs through Ollama on your machine.
- The original file is never changed. Every operation writes a new file.

## What it does

| Task | Command |
|---|---|
| List images, sizes and effective DPI | `inspect` |
| Compress at a maximum resolution | `compress` |
| Compress until the output fits a size limit | `fit` |
| Make a print copy without Adobe editing data | `python -m pdftoolkit.editing` |
| Merge PDFs | `merge` |
| Split a PDF into parts under a size limit | `split` |
| Remove image backgrounds | `removebg` |
| Label pages with Gemma | `classify` |
| Remove backgrounds on the pages Gemma picks | `removebg --classify` |
| Remove backgrounds, then fit to a size limit | `pipeline` |
| Do all of the above with buttons in a browser | `python app.py` |

## Install

You need Python 3.11 or newer. On Windows, install it from python.org and tick **Add python.exe to PATH**. The commands below use a virtual environment, so the packages stay in the project folder.

### Windows (PowerShell)

```
cd C:\path\to\PDFme
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements-bg.txt
python -m pip install ollama pypdfium2 gradio
```

### macOS and Linux

```
cd /path/to/PDFme
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-bg.txt
python -m pip install ollama pypdfium2 gradio
```

### Gemma (optional, for page labels)

Install Ollama from https://ollama.com/download, then download the model once. It is a few gigabytes:

```
ollama pull gemma3:4b
```

Ollama must be running when you use `classify` or `removebg --classify`. If it is not running, those commands say so and carry on without the labels.

### Check the install

```
python -m pytest -q
```

All tests should pass. The first run also downloads the background-removal model (about 180 MB).

## First run and offline use

Two things download from the internet, once each:

1. **The background-removal model** (isnet-general-use, about 180 MB) is downloaded the first time you remove a background. It is saved to:
   - Windows: `%USERPROFILE%\.rembg\models\isnet-general-use\`
   - macOS and Linux: `~/.rembg/models/isnet-general-use/`
2. **The Gemma model** is downloaded by `ollama pull`.

After both are in place, you can disconnect from the internet and everything still works.

To use a model file you copied from another computer, pass it with `--model-file "C:\path\isnet-general-use.onnx"`. The file is copied into the folder above on first use.

## Web page

To use PDFme with buttons instead of commands:

```
python app.py
```

Your browser opens the page. If it doesn't, go to http://127.0.0.1:7860. Leave the window open while you work. Closing it stops the page.

The page has one tab for each feature: Inspect, Compress, Print copy, Merge and split, Remove background, Page labels and Pipeline. Results are saved in the `outputs` folder next to `app.py`, and each one can be downloaded from the page.

The page listens on your own computer only (127.0.0.1). It is not published on the internet or shared with anyone else.

## Commands

Commands print a short summary. Most of them also write a JSON report, which lists what happened to every image. The print copy writes one when you add `--report`.

### Inspect

```
python -m pdftoolkit inspect input.pdf
```

Lists each image with its pixel size, colour space, transparency, and effective DPI on the page.

### Compress at a fixed resolution

```
python -m pdftoolkit compress input.pdf output.pdf --max-dpi 150 --quality 90
```

Images above the maximum DPI are reduced to that DPI and re-encoded as JPEG. Images at or below it are left unchanged. The page count and page sizes do not change.

### Compress to a size limit

```
python -m pdftoolkit fit input.pdf output.pdf --max-mb 2000 --min-dpi 100
```

Tries resolutions from 300 dpi down to `--min-dpi`, and qualities from 92 down to 80. It measures the real output size each time and keeps the first result that fits: the highest resolution, then the highest quality. If nothing fits, no output file is written, and the message says how far off the best result was.

MB here means 1,000,000 bytes, so `--max-mb 2000` is 2 GB by the safer figure.

### Print copy without editing data

```
python -m pdftoolkit.editing input.pdf print.pdf --report print_report.json
```

Photoshop and Illustrator save the layered design inside each page. Printing does not use it, so this removes it and keeps the print unchanged. The original file is not changed. After this, the copy cannot be opened as a layered design, so keep the original for that.

### Merge

```
python -m pdftoolkit merge a.pdf b.pdf -o merged.pdf
```

Joins the pages in the order given.

### Split by size

```
python -m pdftoolkit split big.pdf --max-mb 2000 -o parts
```

Writes parts named `big_part01.pdf`, `big_part02.pdf` and so on, each at or under the limit. Parts are written only if every page fits. If one page is over the limit on its own, nothing is written, and the message says which page.

### Remove backgrounds

```
python -m pdftoolkit removebg input.pdf output.pdf --fill none --pages 1
```

- `--fill none` (the default) makes the background transparent.
- `--fill "#FFFFFF"` composites the image onto a colour instead.
- `--pages 1` or `--pages 1,3` limits which pages are processed.
- `--model-file` uses a local model file.

By default, the tool processes opaque raster images that cover less than 90% of the page they are drawn on. Images that already have transparency are never processed. Vector backgrounds (filled shapes that cover most of a page, such as Canva backgrounds) are never processed. They are listed in the report.

The original pixels are kept, and the mask is added as transparency, so the image stays where it is on the page.

### Label pages with Gemma

```
python -m pdftoolkit classify input.pdf --report labels.json
```

Gemma labels each page as `banner_background`, `subject_photo`, `logo`, `text_page` or `keep_as_is`. This command changes nothing. It only writes the labels.

### Remove backgrounds on the pages Gemma picks

```
python -m pdftoolkit removebg input.pdf output.pdf --classify
```

Background removal runs only on pages labelled `subject_photo` or `logo`. An unclear answer from Gemma is recorded as `keep_as_is`, and that page is left alone.

### Remove backgrounds, then fit to a size limit

```
python -m pdftoolkit pipeline input.pdf output.pdf --remove-bg --max-mb 2000
```

Runs background removal and then the size fit. If background removal reports an error, nothing is written.

## Example results

These are from a real Canva standee export (BIBB Standee_3x6, 515.9 MB as exported):

| Command | Result |
|---|---|
| Print copy (`editing`) | 515.9 MB → **39.0 MB**. Editing data removed; the four 300 dpi images are unchanged. |
| `fit --max-mb 2000` | **284.9 MB** at 300 dpi, quality 92. Editing data kept. The first setting tried already fits. |
| `compress --max-dpi 150` | 515.9 MB → about 251.7 MB. Two large images reduced from 10,800 × 21,600 px to 5,400 × 10,800 px. |

Check the output on screen before you send or print it.

## Reports

Most commands write a JSON report next to their output, named after the output file with `.report.json` added. It lists, for each image, its size before and after, its DPI before and after, and what was done to it. Reports can be opened in any text editor.

## Known limitations

- **Vector backgrounds are not removed.** Canva background shapes are left alone and listed in the report.
- **Very large files need memory and disk space.** A 500 MB PDF can use several GB of RAM while it is processed. Compression runs write temporary copies while they search for a size, so keep several GB of free disk space.
- **Background removal depends on the subject.** Check each result on screen before you print.
- **Gemma labels are per page.** A page with a background photo and a subject is one label, so the subject may not be processed on that page.
- **Some image types are not compressed.** Inline images, images inside patterns and spot-colour images are reported and left unchanged.
- **CMYK files need a visual check.** Compare colours against the original before you rely on them for print.
- **Gemma is optional.** The other commands work without it.
- **Uploads take disk space.** The web page copies each uploaded file into a temporary folder, so a 500 MB upload needs about 500 MB of free space while the page is open. Use one heavy job at a time.
- **The print copy cannot be reopened as a layered design.** Keep the original file.

## Project files

- `app.py` the web page
- `pdftoolkit/` the code
- `tests/` the tests, run with `python -m pytest -q`
- `NOTES.md` every decision made and why
- `PROGRESS.md` the phase checklist and test results
- `README.md` this file

## IMPORTANT
The AI models PDFme uses, including Gemma via Ollama and the background-removal model, are downloaded separately. They are not covered by this project’s license and follow their own terms of use.
