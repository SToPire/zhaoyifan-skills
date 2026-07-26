---
name: paper-reading
description: Read an arXiv paper and generate a structured reading report in Simplified Chinese. Use when the user provides an arXiv link or asks to read, analyze, summarize, or review an arXiv paper, especially for computer systems and AI topics. Parse the PDF with layout awareness, read the paper in正文顺序, always read the system architecture figure, and inspect other figures or tables only when the正文 explicitly cites them.
---

# paper-reading

Generate a structured reading report for a paper referenced by an `arXiv` link.

## Scope

- Accept only `arXiv` links.
- Do not accept direct PDF files.
- Write the report in Simplified Chinese.
- Preserve quoted English source text exactly when quoting.

## Required Tools

- `python3`
- `PyMuPDF`

## Deterministic Steps

Use the bundled scripts for deterministic processing:

- `scripts/resolve_arxiv.py`
  - Normalize the input link.
  - Extract the paper id.
  - Emit the `abs` URL and `pdf` URL.

- `scripts/extract_pdf_structure.py`
  - Parse PDF metadata.
  - Reconstruct text in reading order with single-column / double-column handling.
  - Extract section-like lines, captions, and in-text figure/table references.
  - Detect candidate system architecture figures from captions.

- `scripts/extract_figures.py`
  - Crop figure regions from pages using caption positions and nearby drawing regions.
  - Emit a manifest for cropped figures.

## Workflow

### 1. Normalize Input

- Run `scripts/resolve_arxiv.py` on the user input.
- Use the emitted `abs` URL and `pdf` URL for downstream steps.

### 2. Obtain Paper

- Read the arXiv abstract page.
- Download the PDF.

### 3. Parse PDF

- Run `scripts/extract_pdf_structure.py` on the PDF.
- Use the extracted reading-order text as the canonical正文顺序.
- Use captions and in-text references as the canonical figure/table index.

### 4. Read the Paper

Follow this order:

1. Abstract
2. Introduction / Motivation / Problem
3. Challenges / Problem Difficulty
4. Design / Method / System Overview
5. Evaluation
6. Conclusion

## Figure Policy

### System Architecture Figure

Always read the system architecture figure.

Detection order:

1. Match figure captions against architecture keywords:
   - `overview`
   - `architecture`
   - `system design`
   - `framework`
   - `pipeline`
2. If no caption match is found, inspect all cropped figures and identify the architecture figure visually.

### Other Figures And Tables

- Do not read every figure or table by default.
- Read a figure or table only when the正文 explicitly cites it.
- For each cited figure or table, inspect:
  - the cropped image when applicable
  - the caption
  - the local正文 context that cites it

## Evaluation Policy

- Do not organize Evaluation by figure order.
- First identify what the Evaluation section is trying to establish.
- If the section explicitly lists goals, use that list.
- Otherwise, use Evaluation subsection titles as the organizing units.
- For each goal or subsection, extract only:
  - the key conclusion
  - the key evidence
  - the cited figure(s) or table(s)
  - whether the evidence supports the claim

## Output Rules

### Minimum Sections

The report must contain:

- 问题背景
- 面临挑战
- 解决方案
- Evaluation

### Optional Sections

Add when present in the paper:

- 对待解决问题的定量分析
- 相关工作
- 局限性 / 未来工作

### Structured Lists

Preserve list structure when the paper enumerates:

- multiple background problems
- multiple challenges
- multiple observations or insights
- multiple design points
- multiple evaluation goals
- multiple related-work categories

Use unordered lists for these items.

## Quotation Fidelity

- If a conclusion, observation, challenge, contribution, design goal, or evaluation claim has explicit source wording in the paper, quote the source wording directly.
- Do not paraphrase when direct wording exists.
- Do not weaken or strengthen the author’s wording.
- Integrate quotes naturally into the report body. Do not introduce quotes with labels such as `原文:` or similar wrappers.
- Do not add Chinese translations for quoted English text unless the user explicitly asks for translation.
- When synthesis is required because the paper does not provide a directly quotable sentence, write the synthesized analysis directly and naturally. Do not add disclaimer labels such as `归纳总结，不是原文表述`.

## Figure Interpretation

- Figures support正文 claims.
- Do not replace正文 claims with figure-only summaries.
- When interpreting a cited figure, answer:
  - what claim the figure is used to support
  - what quantitative evidence is most important
  - whether the figure supports the local正文 statement

## Reading Limitations

Add a short final section named `阅读局限性` containing:

- figures or tables not read because they were never cited in正文
- whether system architecture figure detection used the visual fallback path

## Output Language

- Write the report in Simplified Chinese.
- Keep quoted source text in English.
- Do not add Chinese translations for quoted English text by default.

## Report Style

- Write like a human technical reader, not like a template engine.
- Do not use meta labels such as `原文:`, `翻译:`, `归纳总结，不是原文表述`, or similar scaffolding.
- Present direct quotes inline or as standalone block quotes only when they materially support the point being made.
- The assistant's own analysis should be stated directly and confidently, while remaining faithful to the paper.
- Avoid patronizing contrastive scaffolding such as `不是……，而是……`, `不是 X，而是 Y`, or similar negation-first rhetorical habits. State the point directly.
