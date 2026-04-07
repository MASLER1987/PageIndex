"""
FastAPI web server for PageIndex – exposes document indexing and retrieval as a REST API.

Environment variables:
  OPENAI_API_KEY   – Required. LLM API key (or any LiteLLM-supported provider key).
  PAGEINDEX_MODEL  – Optional. Override the default LLM model.
  PAGEINDEX_WORKSPACE – Optional. Directory for persisted indexes (default: /tmp/pageindex_workspace).
  PORT             – Optional. Server port (default: 8000, Railway sets this automatically).
"""

import os
import json
import shutil
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse

from pageindex import PageIndexClient

load_dotenv()

app = FastAPI(
    title="PageIndex API",
    description="Vectorless, reasoning-based RAG – document indexing and retrieval service.",
    version="1.0.0",
)

WORKSPACE = os.getenv("PAGEINDEX_WORKSPACE", "/tmp/pageindex_workspace")
MODEL = os.getenv("PAGEINDEX_MODEL", None)

# Shared client instance – holds in-memory document index backed by workspace on disk.
client = PageIndexClient(model=MODEL, workspace=WORKSPACE)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── Index a document ──────────────────────────────────────────────────────────

@app.post("/index")
async def index_document(file: UploadFile = File(...)):
    """Upload a PDF or Markdown file and index it. Returns a document_id."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".pdf", ".md", ".markdown"):
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}. Use .pdf or .md")

    # Write upload to a temp file so PageIndex can process it.
    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, file.filename or f"upload{ext}")
    try:
        with open(tmp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        doc_id = client.index(file_path=tmp_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {"doc_id": doc_id}


# ── List documents ────────────────────────────────────────────────────────────

@app.get("/documents")
def list_documents():
    """List all indexed documents with basic metadata."""
    docs = []
    for doc_id, doc in client.documents.items():
        docs.append({
            "doc_id": doc_id,
            "doc_name": doc.get("doc_name", ""),
            "type": doc.get("type", ""),
        })
    return docs


# ── Document metadata ────────────────────────────────────────────────────────

@app.get("/documents/{doc_id}")
def get_document(doc_id: str):
    """Return document metadata."""
    result = json.loads(client.get_document(doc_id))
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Document structure ────────────────────────────────────────────────────────

@app.get("/documents/{doc_id}/structure")
def get_document_structure(doc_id: str):
    """Return the hierarchical tree structure for a document."""
    result = json.loads(client.get_document_structure(doc_id))
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Page content ──────────────────────────────────────────────────────────────

@app.get("/documents/{doc_id}/pages")
def get_page_content(doc_id: str, pages: str = Query(..., description="Page range, e.g. '1-5', '3,8', '12'")):
    """Return text content for the requested pages."""
    result = json.loads(client.get_page_content(doc_id, pages))
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
