import os
from typing import Any
import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from mcp.server.fastmcp import FastMCP

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
NCBI_API_KEY = os.getenv("NCBI_API_KEY")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "your_email@example.com")
UA = {"User-Agent": f"pubmed-mcp/1.0 (+{CONTACT_EMAIL})"}

mcp = FastMCP("PubMed MCP")

@mcp.tool()
def search_pubmed(q: str, n: int = 5) -> list[dict[str, Any]]:
    n = max(1, min(50, int(n)))
    params = {"db": "pubmed", "term": q, "retmode": "json", "retmax": n}
    if NCBI_API_KEY: params["api_key"] = NCBI_API_KEY
    with httpx.Client(timeout=20, headers=UA) as client:
        r = client.get(EUTILS + "esearch.fcgi", params=params); r.raise_for_status()
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if not ids: return []
        sparams = {"db": "pubmed", "id": ",".join(ids), "retmode": "json"}
        if NCBI_API_KEY: sparams["api_key"] = NCBI_API_KEY
        s = client.get(EUTILS + "esummary.fcgi", params=sparams); s.raise_for_status()
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
            "link": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })
    return out

# ---- ASGI app (v1.8.1 は sse_app を使う) ----
mcp_app = mcp.sse_app()

async def root(_):    return JSONResponse({"service":"pubmed-mcp-server","status":"ok"})
async def health(_):  return PlainTextResponse("ok", 200)

app = Starlette(routes=[
    Route("/", root),
    Route("/healthz", health),
])

# ここがポイント：ルート("/")に MCP をマウントする
# こうすると最終エンドポイントは「/sse」になる（＝UIの例と一致）
app.mount("/", mcp_app)
