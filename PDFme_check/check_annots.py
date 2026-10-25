import sys
import pikepdf

with pikepdf.open(sys.argv[1]) as pdf:
    page = pdf.pages[0]
    print("page 1 keys:", sorted(page.obj.keys()))
    print("annotations on page 1:", len(page.obj.get("/Annots", [])))
    print("catalog keys:", sorted(pdf.Root.keys()))
    o30 = pdf.get_object((30, 0))
    print("obj 30 keys:", sorted(o30.keys()) if hasattr(o30, "keys") else type(o30))
    for obj in pdf.objects:
        if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
            for k in obj.keys():
                v = obj.get(k)
                try:
                    if v.objgen[0] == 30:
                        print(f"obj {obj.objgen[0]} key {k} -> obj 30")
                except Exception:
                    pass