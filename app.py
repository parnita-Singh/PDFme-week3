"""PDFme web page. Runs only on this computer.

Start it with:  python app.py
Then open the address it prints (http://127.0.0.1:7860). Nothing is published.
"""

from __future__ import annotations

from pathlib import Path

import gradio as gr

from pdftoolkit.ui_actions import (
    INSPECT_HEADERS,
    LABEL_HEADERS,
    compress_file,
    inspect_file,
    labels_file,
    merge_files,
    pipeline_file,
    print_copy_file,
    remove_background_file,
    split_file,
)

OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
HOST = "127.0.0.1"  # this computer only
PORT = 7860

NOTE = (
    "**PDFme runs on this computer only.** Your files are not uploaded anywhere. "
    "Results are saved in the `outputs` folder next to `app.py`."
)


def build_app() -> gr.Blocks:
    with gr.Blocks(title="PDFme") as demo:
        gr.Markdown("# PDFme\nLocal PDF tools for large print designs.\n\n" + NOTE)

        with gr.Tab("Inspect"):
            f_inspect = gr.File(label="PDF", file_types=[".pdf"], type="filepath")
            b_inspect = gr.Button("Inspect images", variant="primary")
            t_inspect = gr.Dataframe(headers=INSPECT_HEADERS, label="Images", interactive=False)
            m_inspect = gr.Markdown()
            b_inspect.click(
                lambda p: inspect_file(p) if p else ([], "Choose a PDF."),
                inputs=f_inspect, outputs=[t_inspect, m_inspect],
            )

        with gr.Tab("Compress"):
            f_comp = gr.File(label="PDF", file_types=[".pdf"], type="filepath")
            mode = gr.Radio(["Fit to size", "Fixed resolution"], value="Fit to size", label="Mode")
            target = gr.Number(value=2000, label="Size limit (MB), for Fit to size")
            dpi = gr.Slider(60, 300, value=150, step=10, label="Maximum dpi, for Fixed resolution")
            quality = gr.Slider(60, 95, value=90, step=1, label="JPEG quality")
            b_comp = gr.Button("Compress", variant="primary")
            out_comp = gr.File(label="Result")
            m_comp = gr.Markdown()
            b_comp.click(
                lambda p, md, t, d, q: _compress(p, md, t, d, q),
                inputs=[f_comp, mode, target, dpi, quality], outputs=[out_comp, m_comp],
            )

        with gr.Tab("Print copy"):
            f_print = gr.File(label="PDF", file_types=[".pdf"], type="filepath")
            b_print = gr.Button("Make print copy", variant="primary")
            gr.Markdown("Removes the Photoshop/Illustrator editing data. The print looks the same. "
                        "Your original file is not changed.")
            out_print = gr.File(label="Result")
            m_print = gr.Markdown()
            b_print.click(lambda p: _single(print_copy_file, p) if p else (None, "Choose a PDF."),
                          inputs=f_print, outputs=[out_print, m_print])

        with gr.Tab("Merge and split"):
            f_merge = gr.File(label="PDFs to merge, in order", file_types=[".pdf"],
                              type="filepath", file_count="multiple")
            b_merge = gr.Button("Merge", variant="primary")
            out_merge = gr.File(label="Merged PDF")
            m_merge = gr.Markdown()
            b_merge.click(lambda ps: merge_files(ps or [], OUTPUT_DIR),
                          inputs=f_merge, outputs=[out_merge, m_merge])
            gr.Markdown("---")
            f_split = gr.File(label="PDF to split", file_types=[".pdf"], type="filepath")
            split_mb = gr.Number(value=2000, label="Maximum part size (MB)")
            b_split = gr.Button("Split", variant="primary")
            out_split = gr.File(label="Parts", file_count="multiple")
            m_split = gr.Markdown()
            b_split.click(lambda p, mb: _split(p, mb),
                          inputs=[f_split, split_mb], outputs=[out_split, m_split])

        with gr.Tab("Remove background"):
            f_bg = gr.File(label="PDF", file_types=[".pdf"], type="filepath")
            fill = gr.Textbox(value="none", label="Background",
                              info="'none' for transparent, or a colour like #FFFFFF")
            pages = gr.Textbox(value="", label="Pages", info="Blank for all pages. Examples: 1 or 1,3 or 2-4")
            use_gemma = gr.Checkbox(value=False, label="Let Gemma choose the pages (needs Ollama running)")
            gemma_bg = gr.Textbox(value="gemma3:4b", label="Gemma model")
            model_file = gr.Textbox(value="", label="Model file (optional, for computers without internet)")
            b_bg = gr.Button("Remove background", variant="primary")
            out_bg = gr.File(label="Result")
            m_bg = gr.Markdown()
            b_bg.click(
                lambda p, fi, pg, g, gm, mf: _bg(p, fi, pg, g, gm, mf),
                inputs=[f_bg, fill, pages, use_gemma, gemma_bg, model_file],
                outputs=[out_bg, m_bg],
            )

        with gr.Tab("Page labels"):
            f_lab = gr.File(label="PDF", file_types=[".pdf"], type="filepath")
            gemma_lab = gr.Textbox(value="gemma3:4b", label="Gemma model")
            b_lab = gr.Button("Label pages", variant="primary")
            t_lab = gr.Dataframe(headers=LABEL_HEADERS, label="Labels", interactive=False)
            m_lab = gr.Markdown()
            out_lab = gr.File(label="Labels report")
            b_lab.click(lambda p, gm: _labels(p, gm), inputs=[f_lab, gemma_lab],
                        outputs=[t_lab, m_lab, out_lab])

        with gr.Tab("Pipeline"):
            f_pipe = gr.File(label="PDF", file_types=[".pdf"], type="filepath")
            pipe_bg = gr.Checkbox(value=True, label="Remove backgrounds first")
            pipe_fill = gr.Textbox(value="none", label="Background",
                                   info="'none' for transparent, or a colour like #FFFFFF")
            pipe_mb = gr.Number(value=2000, label="Size limit (MB)")
            pipe_model = gr.Textbox(value="", label="Model file (optional)")
            b_pipe = gr.Button("Run pipeline", variant="primary")
            out_pipe = gr.File(label="Result")
            m_pipe = gr.Markdown()
            b_pipe.click(lambda p, rb, fi, mb, mf: _pipeline(p, rb, fi, mb, mf),
                         inputs=[f_pipe, pipe_bg, pipe_fill, pipe_mb, pipe_model],
                         outputs=[out_pipe, m_pipe])
    return demo


# Thin wrappers: they take the page's values and return (file, message) or the table values.

def _single(action, path):
    out, msg = action(path, OUTPUT_DIR)
    return out, msg


def _compress(path, mode, target, dpi, quality):
    if not path:
        return None, "Choose a PDF."
    out, msg = compress_file(path, mode, float(dpi), int(quality), float(target or 0), OUTPUT_DIR)
    return out, msg


def _split(path, max_mb):
    if not path:
        return None, "Choose a PDF."
    files, msg = split_file(path, float(max_mb or 0), OUTPUT_DIR)
    return files or None, msg


def _bg(path, fill, pages, use_gemma, gemma_model, model_file):
    if not path:
        return None, "Choose a PDF."
    out, msg = remove_background_file(path, fill or "none", pages or "", bool(use_gemma),
                                      model_file or None, gemma_model or "gemma3:4b", OUTPUT_DIR)
    return out, msg


def _labels(path, gemma_model):
    if not path:
        return [], "Choose a PDF.", None
    return labels_file(path, gemma_model or "gemma3:4b", OUTPUT_DIR)


def _pipeline(path, remove_bg, fill, max_mb, model_file):
    if not path:
        return None, "Choose a PDF."
    return pipeline_file(path, bool(remove_bg), fill or "none", float(max_mb or 0), model_file or None,
                         OUTPUT_DIR)


if __name__ == "__main__":
    build_app().launch(server_name=HOST, server_port=PORT, inbrowser=True)