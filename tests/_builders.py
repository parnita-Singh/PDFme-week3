"""Small helpers that build test PDFs with exactly the features under test."""

from __future__ import annotations

import io
from pathlib import Path

import pikepdf
from PIL import Image, ImageDraw
from pikepdf import Dictionary, Name, Pdf, Stream


def jpeg_bytes(img: Image.Image, quality: int = 95) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def gradient_image(width: int, height: int) -> Image.Image:
    """A smooth RGB test image with some detail, so resampling is visible."""
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for x in range(width):
        draw.line([(x, 0), (x, height)], fill=(x * 255 // max(1, width - 1), 80, 200 - x % 200))
    draw.ellipse([width // 4, height // 4, 3 * width // 4, 3 * height // 4], fill=(230, 60, 40))
    return img


def image_xobject(pdf: Pdf, data: bytes, width: int, height: int, **entries) -> Stream:
    stream = Stream(pdf, data)
    stream[Name.Type] = Name.XObject
    stream[Name.Subtype] = Name.Image
    stream[Name.Width] = width
    stream[Name.Height] = height
    stream[Name.BitsPerComponent] = entries.pop("bpc", 8)
    stream[Name.ColorSpace] = entries.pop("colorspace", Name.DeviceRGB)
    if "filter" in entries:
        stream[Name.Filter] = entries.pop("filter")
    elif data[:2] == b"\xff\xd8":  # JPEG data: mark it so it is decoded as JPEG
        stream[Name.Filter] = Name.DCTDecode
    for key, value in entries.items():
        stream[Name("/" + key)] = value
    return stream


def form_xobject(pdf: Pdf, content: bytes, xobjects: dict, matrix=None) -> Stream:
    form = Stream(pdf, content)
    form[Name.Type] = Name.XObject
    form[Name.Subtype] = Name.Form
    form[Name.BBox] = pikepdf.Array([0, 0, 1, 1])
    if matrix is not None:
        form[Name.Matrix] = pikepdf.Array(matrix)
    form[Name.Resources] = Dictionary(XObject=Dictionary(xobjects))
    return form


def add_page(
    pdf: Pdf,
    content: bytes,
    xobjects: dict | None = None,
    patterns: dict | None = None,
    size: tuple[float, float] = (612, 792),
) -> pikepdf.Page:
    page = pdf.add_blank_page(page_size=size)
    resources = Dictionary()
    if xobjects:
        resources[Name.XObject] = Dictionary(xobjects)
    if patterns:
        resources[Name.Pattern] = Dictionary(patterns)
    page[Name.Resources] = resources
    page[Name.Contents] = Stream(pdf, content)
    return page


def save(pdf: Pdf, path: Path) -> Path:
    pdf.save(path)
    pdf.close()
    return path