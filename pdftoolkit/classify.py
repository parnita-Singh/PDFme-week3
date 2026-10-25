"""Label each page with a local Gemma model (through Ollama), then remove backgrounds only where it helps.

The model never changes or deletes anything itself. It only labels pages.
Background removal runs on the pages labelled subject_photo or logo. Every
other page is left as it is. If the reply cannot be parsed, the page is labelled
keep_as_is, and nothing on it is changed.

If Ollama is not running, the classifier is skipped with a clear message, and
background removal uses its default rule instead.

Setup (one time, on your computer):
    1. Install Ollama from https://ollama.com/download
    2. ollama pull gemma3:4b
    3. python -m pip install ollama pypdfium2

Usage:
    python -m pdftoolkit classify input.pdf --report labels.json
    python -m pdftoolkit removebg input.pdf output.pdf --classify
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any, Iterable

from pdftoolkit.background import remove_background
from pdftoolkit.inventory import page_count
from pdftoolkit.reporting import default_report_path, write_report

LABELS = ("banner_background", "subject_photo", "logo", "text_page", "keep_as_is")
PROCESS_LABELS = ("subject_photo", "logo")
DEFAULT_GEMMA = "gemma3:4b"
RENDER_WIDTH = 1000

PROMPT = (
    "You are labelling one page of a print design, such as a banner or standee. "
    "Reply with JSON only, no other text, in exactly this form: "
    '{"label": "<one of: banner_background, subject_photo, logo, text_page, keep_as_is>", '
    '"reason": "<a short reason>"}. '
    "Use subject_photo for a photo of a person or object meant to stand out. "
    "Use logo for a brand mark. "
    "Use banner_background for a full-page background image or texture. "
    "Use text_page for a page that is mainly text. "
    "Use keep_as_is when you are not sure."
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class OllamaUnavailable(RuntimeError):
    """Ollama is not running, or the ollama package is not installed."""


# ---------------------------------------------------------------------------
# Reading the reply
# ---------------------------------------------------------------------------

def parse_label(text: str) -> dict[str, Any]:
    """Read the model's reply. Anything that is not a valid label becomes keep_as_is."""
    result: dict[str, Any] = {"label": "keep_as_is", "reason": "", "parsed": False}
    match = _JSON_RE.search(text or "")
    if match is None:
        result["reason"] = "no JSON found in the model reply"
        return result
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        result["reason"] = "the model reply is not valid JSON"
        return result
    if not isinstance(data, dict):
        result["reason"] = "the model reply is not a JSON object"
        return result
    label = data.get("label")
    if label not in LABELS:
        result["reason"] = f"label {label!r} is not one of the allowed labels"
        return result
    result.update(label=label, reason=str(data.get("reason", ""))[:300], parsed=True)
    return result


def _reply_text(reply: Any) -> str:
    if isinstance(reply, dict):
        return reply["message"]["content"]
    return reply.message.content


# ---------------------------------------------------------------------------
# Ollama and page rendering
# ---------------------------------------------------------------------------

def _make_client(host: str | None):
    try:
        import ollama
    except ImportError as exc:
        raise OllamaUnavailable(
            "the ollama package is not installed. Run: python -m pip install ollama"
        ) from exc
    return ollama.Client(host=host) if host else ollama.Client()


def _check_running(client) -> None:
    try:
        client.list()
    except Exception as exc:
        raise OllamaUnavailable(
            "Ollama is not running. Start Ollama, then run the command again. "
            f"Detail: {exc}"
        ) from exc


def render_page_png(input_pdf: str | Path, page_number: int, width: int = RENDER_WIDTH) -> bytes:
    """Render one page to a PNG about `width` pixels wide."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(input_pdf))
    try:
        page = doc[page_number - 1]
        scale = width / page.get_width()
        image = page.render(scale=scale).to_pil().convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Classifying
# ---------------------------------------------------------------------------

def classify_pdf(
    input_pdf: str | Path,
    model: str = DEFAULT_GEMMA,
    host: str | None = None,
    client: Any = None,
    pages: Iterable[int] | None = None,
) -> list[dict[str, Any]]:
    """Return one row per page: label, reason, and whether the reply could be read.

    client can be any object with list() and chat(); the tests pass a fake one.
    Raises OllamaUnavailable if Ollama cannot be reached.
    """
    if client is None:
        client = _make_client(host)
    _check_running(client)

    wanted = None if pages is None else {int(p) for p in pages}
    rows: list[dict[str, Any]] = []
    for number in range(1, page_count(input_pdf) + 1):
        if wanted is not None and number not in wanted:
            continue
        try:
            png = render_page_png(input_pdf, number)
            reply = client.chat(
                model=model,
                messages=[{"role": "user", "content": PROMPT, "images": [png]}],
                format="json",
                options={"temperature": 0},
            )
            text = _reply_text(reply)
        except Exception as exc:  # recorded, never hidden; the page is left alone
            rows.append({
                "page": number, "label": "keep_as_is", "reason": f"Gemma call failed: {exc}",
                "parsed": False, "raw": "",
            })
            continue
        parsed = parse_label(text)
        rows.append({"page": number, **parsed, "raw": text[:200]})
    return rows


def classify_and_remove(
    input_pdf: str | Path,
    output_pdf: str | Path,
    fill: str | None = None,
    model: str = DEFAULT_GEMMA,
    host: str | None = None,
    client: Any = None,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Label pages with Gemma, then remove backgrounds on the pages that need it."""
    input_pdf = Path(input_pdf)
    output_pdf = Path(output_pdf)
    if output_pdf.resolve() == input_pdf.resolve():
        raise ValueError("Refusing to overwrite the input file; choose a different output path.")
    if report_path is None:
        report_path = default_report_path(output_pdf)

    warnings: list[str] = []
    try:
        labels = classify_pdf(input_pdf, model=model, host=host, client=client)
        classification = {"status": "done", "model": model, "pages": labels}
        selected_pages = sorted({r["page"] for r in labels if r["label"] in PROCESS_LABELS})
        unreadable = [r["page"] for r in labels if not r["parsed"]]
        if unreadable:
            warnings.append(f"pages left as keep_as_is because the reply could not be used: {unreadable}")
        failed = [r for r in labels if r["reason"].startswith("Gemma call failed")]
        if labels and len(failed) == len(labels):
            warnings.append(
                f"every Gemma call failed. Check that the model is installed: ollama pull {model}"
            )
    except OllamaUnavailable as exc:
        labels = []
        classification = {"status": "skipped", "model": model, "reason": str(exc), "pages": []}
        selected_pages = None  # fall back to the default rule
        warnings.append(f"classifier skipped: {exc}")

    bg = remove_background(
        input_pdf,
        output_pdf,
        fill=fill,
        pages=selected_pages,
        report_path=report_path,
    )
    if selected_pages is None:
        selection = "default rule: opaque raster images covering under 90% of the page"
    else:
        selection = f"Gemma labels: processed only pages {selected_pages}"

    ok = bg["ok"]
    message = (
        f"{bg['message']} Selection: {selection}."
        + (f" Classifier skipped: {classification['reason']}" if classification["status"] == "skipped" else "")
    )
    report: dict[str, Any] = {
        "operation": "classify_removebg",
        "ok": ok,
        "input": str(input_pdf),
        "output": str(output_pdf) if ok else None,
        "classification": classification,
        "selection": selection,
        "background": bg,
        "warnings": warnings + bg.get("warnings", []),
        "message": message,
    }
    write_report(report, report_path)
    report["report_path"] = str(report_path)
    return report


def classify_to_report(
    input_pdf: str | Path,
    report_path: str | Path,
    model: str = DEFAULT_GEMMA,
    host: str | None = None,
    client: Any = None,
) -> dict[str, Any]:
    """Only label the pages. Nothing is changed, and the labels are written to a report."""
    try:
        rows = classify_pdf(input_pdf, model=model, host=host, client=client)
        status, reason = "done", ""
    except OllamaUnavailable as exc:
        rows, status, reason = [], "skipped", str(exc)
    report: dict[str, Any] = {
        "operation": "classify",
        "ok": status == "done",
        "input": str(input_pdf),
        "model": model,
        "status": status,
        "reason": reason,
        "pages": rows,
        "message": (
            "Labels: " + ", ".join(f"page {r['page']} = {r['label']}" for r in rows)
            if status == "done" else f"Classifier skipped: {reason}"
        ),
    }
    write_report(report, report_path)
    report["report_path"] = str(report_path)
    return report