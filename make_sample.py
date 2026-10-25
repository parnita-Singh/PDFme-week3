"""Build samples/test_banner.pdf: full-page ~353 dpi background + ~288 dpi foreground."""

from __future__ import annotations

import io
import os
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw
from pikepdf import Dictionary, Name, ObjectStreamMode, Pdf, Stream

PAGE_W = 612.0  # US Letter points
PAGE_H = 792.0
BG_W, BG_H = 3000, 3900  # 3000 / (612/72) ≈ 352.94 dpi
FG_W, FG_H = 576, 576  # 576 / (144/72) = 288 dpi
FG_PLACED = 144.0


def make_background() -> Image.Image:
    img = Image.new("RGB", (BG_W, BG_H))
    draw = ImageDraw.Draw(img)
    for y in range(BG_H):
        t = y / max(BG_H - 1, 1)
        draw.line([(0, y), (BG_W, y)], fill=(int(20 + 80 * t), int(40 + 20 * t), int(160 + 70 * t)))
    for i in range(0, BG_W, 80):
        draw.rectangle([i, 0, i + 30, BG_H], fill=(int(180 * (i / BG_W)), 30, 90))
    draw.rectangle([80, 80, BG_W - 80, BG_H - 80], outline=(255, 220, 40), width=12)
    # High-frequency noise so JPEG-at-full-res is large and 150 dpi output shrinks.
    noise = Image.frombytes("RGB", img.size, os.urandom(img.width * img.height * 3))
    noise = noise.point(lambda x: x // 5)
    return ImageChops.add(img, noise)


def make_foreground() -> Image.Image:
    img = Image.new("RGB", (FG_W, FG_H), (240, 80, 40))
    draw = ImageDraw.Draw(img)
    draw.ellipse([48, 48, FG_W - 48, FG_H - 48], fill=(20, 200, 90), outline=(255, 255, 255), width=8)
    draw.rectangle([FG_W // 2 - 40, 80, FG_W // 2 + 40, FG_H - 80], fill=(30, 30, 30))
    return img


def _image_stream(pdf: Pdf, image: Image.Image, quality: int = 95) -> Stream:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=quality)
    jpeg = buf.getvalue()
    stream = Stream(pdf, jpeg)
    stream.write(jpeg, filter=Name.DCTDecode)
    stream[Name.Type] = Name.XObject
    stream[Name.Subtype] = Name.Image
    stream[Name.Width] = image.width
    stream[Name.Height] = image.height
    stream[Name.ColorSpace] = Name.DeviceRGB
    stream[Name.BitsPerComponent] = 8
    stream[Name.Filter] = Name.DCTDecode
    if "/DecodeParms" in stream:
        del stream["/DecodeParms"]
    return stream


def build_sample(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    bg = make_background()
    fg = make_foreground()

    pdf = Pdf.new()
    pdf.add_blank_page(page_size=(PAGE_W, PAGE_H))
    page = pdf.pages[0]
    im0 = _image_stream(pdf, bg)
    im1 = _image_stream(pdf, fg)
    xobjects = Dictionary()
    xobjects[Name.Im0] = im0
    xobjects[Name.Im1] = im1
    resources = page.get("/Resources") or Dictionary()
    resources[Name.XObject] = xobjects
    page[Name.Resources] = resources

    fx = (PAGE_W - FG_PLACED) / 2.0
    fy = (PAGE_H - FG_PLACED) / 2.0
    content = (
        f"q {PAGE_W:.4f} 0 0 {PAGE_H:.4f} 0 0 cm /Im0 Do Q\n"
        f"q {FG_PLACED:.4f} 0 0 {FG_PLACED:.4f} {fx:.4f} {fy:.4f} cm /Im1 Do Q\n"
    )
    page[Name.Contents] = Stream(pdf, content.encode("ascii"))
    pdf.save(path, compress_streams=True, object_stream_mode=ObjectStreamMode.generate)
    pdf.close()
    return path


def main() -> None:
    out = Path(__file__).resolve().parent / "samples" / "test_banner.pdf"
    build_sample(out)
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
