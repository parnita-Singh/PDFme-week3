import sys
import pikepdf

with pikepdf.open(sys.argv[1]) as pdf:
    page = pdf.pages[0]
    contents = page.obj.get("/Contents")
    print("page 1 content stream:", getattr(contents, "objgen", "array"))

    ops = list(pikepdf.parse_content_stream(page))
    inline = [o[0] for o, op in ops if str(op) == "INLINE IMAGE"]
    print(f"inline images on page 1: {len(inline)}")
    for ii in inline:
        print(f"  {ii.width} x {ii.height}  filter {ii.obj.get('/Filter', '-')}  colour {ii.obj.get('/ColorSpace', '-')}")

    print("image objects and their soft masks:")
    for obj in pdf.objects:
        if isinstance(obj, pikepdf.Stream) and obj.get("/Subtype") == pikepdf.Name.Image:
            sm = obj.get("/SMask")
            link = sm.objgen[0] if sm is not None else "none"
            print(f"  obj {obj.objgen[0]}  {obj.get('/Width')} x {obj.get('/Height')}  SMask -> {link}")