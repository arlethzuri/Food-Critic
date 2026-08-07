#!/usr/bin/env python3
"""
RAG corpus ingestion for Variant 2: downloads the two regulatory sources
listed in data/RAG/sources.txt, extracts text, chunks it, embeds with a
local HuggingFace model, and persists a Chroma vector store that
app/rag/retriever.py queries at runtime.

Sources:
  - R392-100 Food Service Sanitation Rule (PDF: FDA Food Code 2013 + Utah
    amendments, ~250 pages, numbered sections e.g. "1-101.10")
  - Salt Lake County Health Dept food-inspection process page (HTML:
    scoring, risk levels, critical/non-critical violation definitions)

adminrules.utah.gov's own hosting of R392-100 is intentionally skipped:
it's a JS-rendered SPA (not fetchable without a headless browser) and its
content is the same rule as the PDF above.

Re-running this script rebuilds the index from scratch each time (cheap:
one PDF + one page, everything embeds locally, no API costs).

Dependencies: pip install -r app/requirements.txt
Usage: python3 app/rag/ingest.py
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = ROOT / "data" / "RAG" / "raw"
PERSIST_DIR = ROOT / "data" / "RAG" / "chroma"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

PDF_URL = "https://site.utah.gov/webermorgan/wp-content/uploads/sites/60/2023/05/R392-100-Food-Service-Sanitation-Rule.pdf"
PDF_SOURCE_NAME = "R392-100 Food Service Sanitation Rule (Utah Admin Code / FDA Food Code 2013)"

COUNTY_URL = "https://www.saltlakecounty.gov/health/food-protection/inspections/"
COUNTY_SOURCE_NAME = "Salt Lake County Health Dept — Food Inspection Process"

# Matches numbered section headings like "1-101.10" or "R392-100-1." at the
# start of a line, so each chunk can cite the nearest section it fell under
# (best-effort — PDF text extraction doesn't preserve font/layout cues).
HEADING_RE = re.compile(r"^\s*((?:R\d+-\d+-\d+|\d+(?:-\d+)*(?:\.\d+)?))\.?\s+([A-Z][A-Za-z ,'\-]{2,60})\s*$")

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150


def fetch_pdf() -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / "R392-100-Food-Service-Sanitation-Rule.pdf"
    if not path.exists():
        resp = requests.get(PDF_URL, timeout=60)
        resp.raise_for_status()
        path.write_bytes(resp.content)
    return path


def load_pdf_documents(path: Path) -> list[Document]:
    reader = PdfReader(str(path))
    docs = []
    last_heading = ""
    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if not text.strip():
            continue
        for line in text.splitlines():
            m = HEADING_RE.match(line)
            if m:
                last_heading = f"{m.group(1)} {m.group(2)}".strip()
        docs.append(Document(
            page_content=text,
            metadata={
                "source": PDF_SOURCE_NAME,
                "source_url": PDF_URL,
                "page": page_num,
                "nearest_heading": last_heading,
            },
        ))
    return docs


def load_county_page_documents() -> list[Document]:
    resp = requests.get(
        COUNTY_URL, timeout=30,
        headers={"User-Agent": "Mozilla/5.0 (compatible; food-health-viz research)"},
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    main = soup.find("main") or soup.find("article") or soup.body
    text = main.get_text(separator="\n", strip=True) if main else soup.get_text(separator="\n", strip=True)
    return [Document(
        page_content=text,
        metadata={"source": COUNTY_SOURCE_NAME, "source_url": COUNTY_URL, "page": 1, "nearest_heading": ""},
    )]


def build_index() -> None:
    pdf_path = fetch_pdf()
    docs = load_pdf_documents(pdf_path) + load_county_page_documents()
    print(f"Loaded {len(docs)} source documents (pages + web page).")

    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    chunks = splitter.split_documents(docs)
    print(f"Split into {len(chunks)} chunks.")

    print(f"Loading embedding model {EMBEDDING_MODEL} (first run downloads it, ~80MB)...")
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

    if PERSIST_DIR.exists():
        shutil.rmtree(PERSIST_DIR)
    PERSIST_DIR.mkdir(parents=True, exist_ok=True)

    print("Embedding and indexing (this is the slow step)...")
    Chroma.from_documents(chunks, embeddings, persist_directory=str(PERSIST_DIR))
    print(f"Done. Indexed {len(chunks)} chunks into {PERSIST_DIR}")


if __name__ == "__main__":
    build_index()
