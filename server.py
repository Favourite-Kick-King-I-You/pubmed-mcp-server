import sys
print(">>> LOADING server.py", file=sys.stderr)


import os
from typing import List, Dict, Any
import httpx

from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

# === MCP SDK ===
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
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    with httpx.Client(timeout=20, headers=UA) as client:
        r = client.get(EUTILS + "esearch.fcgi", params=params); r.raise_for_status()
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        sparams = {"db": "pubmed", "id": ",".join(ids), "retmode": "json"}
        if NCBI_API_KEY:
            sparams["api_key"] = NCBI_API_KEY
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

# --- ASGI app for MCP (Streamable HTTP) ---
# SDKのHTTPトランスポート（バージョンにより関数名が異なる可能性があるためフォールバック）
get_mcp_http_app = (
    getattr(mcp, "asgi_app", None)
    or getattr(mcp, "http_app", None)
    or getattr(mcp, "streamable_http_app", None)
)

assert get_mcp_http_app, "Your MCP SDK does not expose any ASGI app factory"
mcp_http_app = get_mcp_http_app()

# 明示ディスパッチ: /mcp と /mcp/... を強制的に mcp_http_app へ転送
async def mcp_dispatch(scope, receive, send):
    if scope["type"] != "http":
        return await mcp_http_app(scope, receive, send)
    path = scope.get("path", "")
    if path == "/mcp" or path.startswith("/mcp/"):
        # /mcp ベースを剥がして内部に渡す（/ → ルートに）
        inner = dict(scope)
        inner_path = path[len("/mcp"):] or "/"
        inner["path"] = inner_path
        return await mcp_http_app(inner, receive, send)
    # それ以外は 404
    return await PlainTextResponse("Not Found", 404)(scope, receive, send)

# ヘルスとルート
async def health(_):
    return PlainTextResponse("ok", 200)

async def root(_):
    return JSONResponse({"service": "pubmed-mcp-server", "status": "ok"})

app = Starlette()
app.add_route("/", root)
app.add_route("/healthz", health)
app.mount("/mcp", mcp_http_app)

