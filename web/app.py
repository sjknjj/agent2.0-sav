"""FastAPI Web 服务：浏览器端触发公司速览与研报生成。

启动方式：
    pip install fastapi uvicorn
    python main.py serve
    # 打开 http://localhost:8000
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.agent.orchestrator import ResearchOrchestrator
from src.common.config import load_settings
from src.export.exporter import export_assistant, export_report
from src.services.research_assistant import ResearchAssistant

app = FastAPI(title="研报辅助 Agent", version="1.1")

_PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>研报辅助 Agent</title>
<style>
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
background:#f5f6f8;color:#1f2329;max-width:720px;margin:40px auto;padding:0 20px;}
h1{font-size:24px;}
.card{background:#fff;border-radius:12px;padding:24px;margin:16px 0;
box-shadow:0 1px 4px rgba(0,0,0,.06);}
input,textarea,button{font-size:15px;padding:10px 14px;border-radius:8px;border:1px solid #d0d5dd;}
input,textarea{flex:1;}
textarea{min-height:40px;resize:vertical;}
button{background:#0f4c81;color:#fff;border:none;cursor:pointer;margin-left:8px;}
button:hover{background:#0d3d6b;}
button:disabled{background:#999;}
.row{display:flex;gap:8px;margin:12px 0;}
.result{white-space:pre-wrap;margin-top:16px;line-height:1.8;font-size:14px;}
.tip{color:#6b7280;font-size:13px;}
h3{margin:0 0 12px;}
.spinner{display:inline-block;width:16px;height:16px;border:2px solid #ccc;
border-top-color:#0f4c81;border-radius:50%;animation:spin .8s linear infinite;
vertical-align:middle;margin-right:6px;}
@keyframes spin{to{transform:rotate(360deg);}}
</style></head><body>
<h1>研报辅助 Agent</h1>

<div class="card">
  <h3>公司投研速览</h3>
  <div class="row">
    <input id="symbol" placeholder="A 股代码，如 600519" value="600519">
    <button onclick="brief()">生成速览</button>
  </div>
  <div class="tip">AKShare 实时数据 + 大模型分析 + 数字交叉校验反幻觉</div>
  <div id="brief_result" class="result"></div>
</div>

<div class="card">
  <h3>深度研报生成</h3>
  <div class="row">
    <input id="topic" placeholder="研究主题，如 低空经济产业链分析">
    <button onclick="genReport()">生成研报</button>
  </div>
  <label class="tip"><input type="checkbox" id="deep"> 递归深挖检索（多轮补检，更慢但更全）</label>
  <div id="report_result" class="result"></div>
</div>

<script>
async function brief(){
  const sym=document.getElementById('symbol').value.trim();
  const el=document.getElementById('brief_result');
  el.innerHTML='<span class="spinner"></span>生成中…';
  try{
    const r=await fetch('/api/brief?symbol='+encodeURIComponent(sym));
    const d=await r.json();
    if(d.error){el.textContent='错误：'+d.error;return;}
    el.textContent=d.text;
  }catch(e){el.textContent='请求失败：'+e;}
}
async function genReport(){
  const topic=document.getElementById('topic').value.trim();
  if(!topic){alert('请输入研究主题');return;}
  const deep=document.getElementById('deep').checked;
  const el=document.getElementById('report_result');
  el.innerHTML='<span class="spinner"></span>正在规划→检索→分析→撰写→审校，请稍候…';
  try{
    const r=await fetch('/api/report?topic='+encodeURIComponent(topic)+'&deep='+deep);
    const d=await r.json();
    if(d.error){el.textContent='错误：'+d.error;return;}
    el.textContent=d.text;
  }catch(e){el.textContent='请求失败：'+e;}
}
</script></body></html>"""


class BriefResponse(BaseModel):
    text: str
    verification: dict = {}
    output_file: str = ""


class ReportResponse(BaseModel):
    text: str
    sections: int = 0
    references: int = 0
    output_file: str = ""


@app.get("/", response_class=HTMLResponse)
def index():
    return _PAGE


@app.get("/api/brief", response_model=BriefResponse)
def api_brief(symbol: str):
    settings = load_settings()
    ra = ResearchAssistant(settings)
    try:
        result = ra.company_brief(symbol, prefer_live=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))
    files = export_assistant(
        f"{symbol} 投研速览", result.text, settings.output_dir,
        formats=("md", "html"),
        verification=result.verification,
        fact_pack=result.fact_pack,
    )
    return BriefResponse(
        text=result.text,
        verification=result.verification or {},
        output_file=str(files[0]) if files else "",
    )


@app.get("/api/report", response_model=ReportResponse)
def api_report(topic: str, deep: bool = False):
    settings = load_settings()
    orchestrator = ResearchOrchestrator(settings)
    try:
        report = orchestrator.run(topic, deep=deep)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))
    files = export_report(report, settings.output_dir, ("md", "html"))
    # 拼成可读文本
    parts = [f"# {report.topic}", "", report.abstract, ""]
    for s in report.sections:
        parts.append(f"## {s.heading}\n{s.content}\n")
    return ReportResponse(
        text="\n".join(parts),
        sections=len(report.sections),
        references=len(report.references),
        output_file=str(files[0]) if files else "",
    )


def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
