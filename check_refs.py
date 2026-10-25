import sys
import pikepdf

WATCH = (31, 33, 35)


def children(obj):
    if isinstance(obj, pikepdf.Array):
        return list(obj)
    if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
        return [obj.get(k) for k in obj.keys()]
    return []


with pikepdf.open(sys.argv[1]) as pdf:
    for n in WATCH:
        obj = pdf.get_object((n, 0))
        keys = sorted(obj.keys()) if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)) else []
        print(f"obj {n} keys: {keys}")

    print("references:")
    for obj in pdf.objects:
        if not isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream, pikepdf.Array)):
            continue
        for child in children(obj):
            try:
                num = child.objgen[0]
            except Exception:
                continue
            if num in WATCH:
                if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
                    kind = str(obj.get("/Type", obj.get("/Subtype", "?")))
                else:
                    kind = "array"
                print(f"  obj {num} is referenced by obj {obj.objgen[0]} ({kind})")