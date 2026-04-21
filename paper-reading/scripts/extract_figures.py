#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

import fitz


def iter_caption_blocks(page):
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text, *_ = block
        normalized = " ".join(text.split())
        if normalized.startswith("Figure "):
            yield {
                "text": normalized,
                "bbox": [x0, y0, x1, y1],
            }


def nearby_drawing_rects(page):
    rects = []
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.x0 >= rect.x1 or rect.y0 >= rect.y1:
            continue
        if rect.y0 < 0 or rect.y1 > page.rect.height:
            continue
        rects.append(rect)
    return rects


def column_bounds(page, caption_bbox):
    width = page.rect.width
    mid = width / 2
    x0, _, x1, _ = caption_bbox
    if x1 < mid + 20:
        return 40, mid - 12
    if x0 > mid - 20:
        return mid + 12, width - 40
    return 40, width - 40


def choose_crop_rect(page, caption):
    drawings = nearby_drawing_rects(page)
    x_min, x_max = column_bounds(page, caption["bbox"])
    _, cy0, _, _ = caption["bbox"]

    candidates = []
    for rect in drawings:
        overlap = max(0, min(rect.x1, x_max) - max(rect.x0, x_min))
        if overlap < 0.45 * (rect.x1 - rect.x0):
            continue
        gap = cy0 - rect.y1
        area = (rect.x1 - rect.x0) * (rect.y1 - rect.y0)
        if 0 <= gap <= 25 and area >= 5000:
            candidates.append((gap, -area, rect))

    if not candidates:
        return None
    _, _, rect = sorted(candidates, key=lambda item: (item[0], item[1]))[0]
    return fitz.Rect(
        max(0, rect.x0 - 6),
        max(0, rect.y0 - 6),
        min(page.rect.width, rect.x1 + 6),
        min(page.rect.height, rect.y1 + 6),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--scale", type=float, default=2.5)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(args.pdf)
    manifest = []

    for page_index, page in enumerate(doc):
        for caption in iter_caption_blocks(page):
            match = re.match(r"Figure\s+(\d+):", caption["text"])
            if not match:
                continue
            figure_no = int(match.group(1))
            clip = choose_crop_rect(page, caption)
            if clip is None:
                continue
            pix = page.get_pixmap(clip=clip, matrix=fitz.Matrix(args.scale, args.scale), alpha=False)
            filename = f"figure_{figure_no:02d}.png"
            path = args.output_dir / filename
            pix.save(path)
            manifest.append(
                {
                    "figure": figure_no,
                    "page": page_index + 1,
                    "caption": caption["text"],
                    "path": str(path),
                    "crop_rect": [round(v, 1) for v in (clip.x0, clip.y0, clip.x1, clip.y1)],
                }
            )

    manifest.sort(key=lambda item: item["figure"])
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
