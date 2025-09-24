# server.py
import os
from typing import List, Dict, Any
import httpx

from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route

# === MCP SDK ===
from mcp.server.fastmcp import FastMCP

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
NCBI_API_KEY = os.getenv("NCBI_API_KEY")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "your_email@example.com")

UA = {"User-Agent": f"pubmed-mcp/1.0 (+{CONTACT_EMAIL})"}

mcp = FastMCP("PubMed MCP")

@mcp.tool()
def search_pubmed(q: str, n: int = 5) -> List[Dict[str, Any]]:
    """
    PubMed を検索して上位 n 件を返す。
    Args:
      q: クエリ
      n: 1-50
    """
    n = max(1, min(50, int(n)))
    params = {"db": "pubmed", "term": q, "retmode": "json", "retmax": n}
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    with httpx.Client(timeout=20, headers=UA) as client:
        r = client.get(EUTILS + "esearch.fcgi", params=params)
        r.raise_for_status()
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []

        sparams = {"db": "pubmed", "id": ",".join(ids), "retmode": "json"}
        if NCBI_API_KEY:
            sparams["api_key"] = NCBI_API_KEY
        s = client.get(EUTILS + "esummary.fcgi", params=sparams)
        s.raise_for_status()
        sj = s.json().get("result", {})

    out = []
    for pmid in ids:
        itm = sj.get(pmid, {}) or {}
        out.append({
            "pmid": pmid,
            "title": itm.get("title"),
            "journal": itm.get("fulljournalname"),
            "pubdate": itm.get("pubdate"),
            "authors": [a.get("name") for a in (itm.get("authors") or [])][:10],
            "link": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        })
    return out

# === HTTP transport (MCP) を公開 ===
mcp_app = mcp.streamable_http_app()

# Koyeb ヘルスチェック用
async def health(_):
    return PlainTextResponse("ok", 200)

async def root(_):
    return JSONResponse({"service": "pubmed-mcp-server", "status": "ok"})

app = Starlette(routes=[
    Route("/", root),
    Route("/healthz", health),
    Mount("/mcp/", app=mcp_app),  # ← ChatGPTのコネクタはここに接続します
    Mount("/sse/", app=mcp_app),  
])
