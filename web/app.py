from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

BASE_DIR = Path(__file__).parent.parent
OUTPUTS_DIR = BASE_DIR / "outputs"
LATEST_JSON = OUTPUTS_DIR / "latest_run.json"
CONFIG_PATH = BASE_DIR / "config" / "workflow.example.yaml"
TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="Stockwatch Dashboard")

# Use Jinja2 directly to avoid Starlette's template cache hashing bug
_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _signal_color(signal: str | None) -> str:
    return {"bullish": "green", "bearish": "red", "neutral": "gray"}.get(signal or "", "gray")


def _consensus_color(consensus: str | None) -> str:
    return {
        "strong_buy": "green", "buy": "green",
        "hold": "yellow",
        "underperform": "red", "sell": "red",
    }.get(consensus or "", "gray")


_jinja_env.filters["signal_color"] = _signal_color
_jinja_env.filters["consensus_color"] = _consensus_color


def _render(template_name: str, **ctx: Any) -> HTMLResponse:
    tmpl = _jinja_env.get_template(template_name)
    return HTMLResponse(tmpl.render(**ctx))


def load_data() -> dict[str, Any]:
    if not LATEST_JSON.exists():
        return {}
    with LATEST_JSON.open(encoding="utf-8") as f:
        return json.load(f)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    data = load_data()
    ai_count = sum(1 for c in data.get("candidates", []) if c.get("ai"))
    return _render("index.html", request=request, data=data, ai_count=ai_count)


@app.get("/industry/{name}", response_class=HTMLResponse)
async def industry_detail(request: Request, name: str):
    data = load_data()
    industry = next((i for i in data.get("industries", []) if i["name"] == name), None)
    return _render("industry.html", request=request, industry=industry, data=data)


@app.get("/stock/{symbol}", response_class=HTMLResponse)
async def stock_detail(request: Request, symbol: str):
    data = load_data()
    candidate = next((c for c in data.get("candidates", []) if c["symbol"] == symbol), None)
    return _render("stock.html", request=request, candidate=candidate, data=data)


@app.post("/run")
async def trigger_run(request: Request):
    """Run the workflow synchronously and redirect to dashboard."""
    subprocess.run(
        [sys.executable, "-m", "stockwatch_workflow.run",
         "--config", str(CONFIG_PATH), "--mode", "daily"],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
    )
    return RedirectResponse(url="/", status_code=303)


if __name__ == "__main__":
    uvicorn.run("web.app:app", host="0.0.0.0", port=8000, reload=True, app_dir=str(BASE_DIR))
