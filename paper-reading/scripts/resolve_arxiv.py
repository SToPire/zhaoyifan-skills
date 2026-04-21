#!/usr/bin/env python3
import json
import re
import sys
from urllib.parse import urlparse


ARXIV_HOSTS = {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}


def normalize_arxiv_id(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)

    if parsed.scheme and parsed.netloc:
        if parsed.netloc not in ARXIV_HOSTS:
            raise ValueError("input is not an arXiv URL")
        path = parsed.path.rstrip("/")
        m = re.match(r"^/(abs|pdf)/(.+?)(?:\.pdf)?$", path)
        if not m:
            raise ValueError("unsupported arXiv URL path")
        paper_id = m.group(2)
    else:
        paper_id = value

    paper_id = re.sub(r"v\d+$", "", paper_id)
    if not re.match(r"^[A-Za-z0-9.\-_/]+$", paper_id):
        raise ValueError("invalid arXiv id")
    return paper_id


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: resolve_arxiv.py <arxiv-url-or-id>", file=sys.stderr)
        return 2

    paper_id = normalize_arxiv_id(sys.argv[1])
    result = {
        "paper_id": paper_id,
        "abs_url": f"https://arxiv.org/abs/{paper_id}",
        "pdf_url": f"https://arxiv.org/pdf/{paper_id}.pdf",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
