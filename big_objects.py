import sys
import pikepdf

path = sys.argv[1]
rows = []
with pikepdf.open(path) as pdf:
    for obj in pdf.objects:
        if isinstance(obj, pikepdf.Stream):
            size = len(obj.read_raw_bytes())
            rows.append((
                size,
                obj.objgen[0],
                str(obj.get("/Type", "-")),
                str(obj.get("/Subtype", "-")),
                str(obj.get("/Filter", "-")),
                str(obj.get("/Width", "-")),
                str(obj.get("/Height", "-")),
            ))

total = sum(r[0] for r in rows)
print(f"streams: {len(rows)}   total stream bytes: {total / 1e6:.1f} MB")
rows.sort(reverse=True)
for size, num, typ, sub, filt, w, h in rows[:20]:
    print(f"{size / 1e6:9.2f} MB  obj {num:>5}  {typ:<10} {sub:<12} {w} x {h}  filter {filt}")