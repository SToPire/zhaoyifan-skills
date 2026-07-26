#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

import fitz


ARCH_KEYWORDS = (
    "overview",
    "architecture",
    "system design",
    "framework",
    "pipeline",
)


def span_text(line):
    parts = []
    for span in line.get("spans", []):
        text = " ".join(span.get("text", "").split())
        if text:
            parts.append(text)
    return " ".join(parts).strip()


def detect_columns(blocks, page_width):
    xs = []
    for block in blocks:
        if block.get("type") != 0:
            continue
        if not block.get("lines"):
            continue
        x0, _, x1, _ = block["bbox"]
        if (x1 - x0) < page_width * 0.15:
            continue
        xs.append((x0, x1))

    if len(xs) < 4:
        return None

    mid = page_width / 2
    left = [item for item in xs if item[1] <= mid + page_width * 0.08]
    right = [item for item in xs if item[0] >= mid - page_width * 0.08]
    if len(left) < 2 or len(right) < 2:
        return None
    return mid


def sorted_text_lines(page):
    data = page.get_text("dict")
    blocks = data["blocks"]
    page_width = page.rect.width
    split_x = detect_columns(blocks, page_width)

    items = []
    for block in blocks:
        if block.get("type") != 0:
            continue
        bbox = block["bbox"]
        x0, y0, x1, y1 = bbox
        for line in block.get("lines", []):
            text = span_text(line)
            if not text:
                continue
            line_bbox = line["bbox"]
            lx0, ly0, lx1, ly1 = line_bbox
            item = {
                "text": text,
                "bbox": [round(v, 1) for v in line_bbox],
                "block_bbox": [round(v, 1) for v in bbox],
            }
            if split_x is None:
                key = (0, ly0, lx0)
            else:
                col = 0 if lx0 < split_x else 1
                key = (col, ly0, lx0)
            items.append((key, item))
    items.sort(key=lambda x: x[0])
    return [item for _, item in items], split_x is not None


def extract_captions(page):
    captions = []
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text, *_ = block
        normalized = " ".join(text.split())
        if re.match(r"^(Figure|Table)\s+\d+:", normalized):
            captions.append(
                {
                    "text": normalized,
                    "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                }
            )
    return captions


def extract_references(text):
    refs = re.findall(r"(?:Figure|Fig\.|Table)\s*\d+", text)
    dedup = []
    seen = set()
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            dedup.append(ref)
    return dedup


def candidate_architecture_figures(captions):
    candidates = []
    for caption in captions:
        lowered = caption["text"].lower()
        if lowered.startswith("figure"):
            if any(keyword in lowered for keyword in ARCH_KEYWORDS):
                candidates.append(caption["text"])
    return candidates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    doc = fitz.open(args.pdf)
    pages = []
    all_captions = []
    all_arch_candidates = []
    section_lines = []

    for i, page in enumerate(doc):
        lines, is_double_column = sorted_text_lines(page)
        text = "\n".join(item["text"] for item in lines)
        captions = extract_captions(page)
        refs = extract_references(text)
        all_captions.extend(
            [{"page": i + 1, **caption} for caption in captions]
        )
        all_arch_candidates.extend(candidate_architecture_figures(captions))

        for item in lines:
            if len(item["text"]) < 160 and re.match(r"^(\d+(\.\d+)*)?\s*[A-Z][A-Za-z0-9 /:-]+$", item["text"]):
                section_lines.append({"page": i + 1, "text": item["text"]})

        pages.append(
            {
                "page": i + 1,
                "double_column": is_double_column,
                "lines": lines,
                "captions": captions,
                "references": refs,
            }
        )

    result = {
        "metadata": doc.metadata,
        "page_count": doc.page_count,
        "pages": pages,
        "captions": all_captions,
        "section_like_lines": section_lines,
        "architecture_caption_candidates": all_arch_candidates,
    }

    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
