import sys
from pdftoolkit.inventory.py import inventory_pdf, records_as_dicts, page_count

print("pages:", page_count(sys.argv[1]))
for r in records_as_dicts(inventory_pdf(sys.argv[1])):
    print(
        f"page {r['page']}  {r['name']:<12} {r['pixel_size']}  "
        f"{r['color_space']}  dpi={r['effective_dpi']}  "
        f"inline={r['is_inline']}  note={r['note']}"
    )