"""Qlib 量化实验平台 - FastAPI 后端入口。

启动方式（在 ui-project/backend 目录下）:
    D:\\workspace_buddy\\conda_envs\\my_temp\\python.exe -m uvicorn main:app --port 8000
"""

import asyncio
import json
import subprocess
import threading
import uuid
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

import adapter
import fetcher
import runner
import store

app = FastAPI(title="Qlib 量化实验平台", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 数据下载任务状态（简单内存态）
_download_lock = threading.Lock()
_download_running = False


@app.get("/api/models", summary="模型模板列表")
def api_models() -> list[dict]:
    return adapter.list_model_templates()


@app.post("/api/experiments", summary="创建并启动实验")
def api_create_experiment(payload: dict) -> dict:
    model_id = payload.get("model_id", "")
    params = payload.get("params") or {}
    templates = {m["id"]: m for m in adapter.list_model_templates()}
    if model_id not in templates:
        raise HTTPException(status_code=400, detail=f"未知模型: {model_id}")

    # 用模板 schema 的默认值补齐未填参数
    schema = templates[model_id]["params_schema"] or {}
    merged: dict = {}
    for key, spec in schema.items():
        merged[key] = params.get(key, spec.get("default"))
    for required in ("start_date", "end_date"):
        if not merged.get(required):
            raise HTTPException(status_code=400, detail=f"缺少必填参数: {required}")

    # 校验参数取值
    try:
        merged["start_date"] = str(merged["start_date"])
        merged["end_date"] = str(merged["end_date"])
        dates = adapter.split_date_range(merged["start_date"], merged["end_date"])
        merged.update(dates)
        merged["market"] = str(merged.get("market") or "csi300")
        merged["account"] = int(merged.get("account") or 100000000)
        merged["topk"] = int(merged.get("topk") or 50)
        merged["n_drop"] = int(merged.get("n_drop") or 5)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"参数不合法: {exc}") from exc

    # 渲染模板
    template_path = adapter.TEMPLATES_DIR / f"{model_id}.yaml"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_path.name}")
    try:
        rendered = adapter.render_config(template_path, merged)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=500, detail=f"模板渲染失败: {exc}") from exc

    # 写入实验工作目录
    exp_id = uuid.uuid4().hex[:12]
    workdir = adapter.ensure_workspace(exp_id)
    config_path = workdir / "config.yaml"
    config_path.write_text(rendered, encoding="utf-8")

    # 提交后台执行
    try:
        runner.start_experiment(exp_id, model_id, str(config_path))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"exp_id": exp_id, "model_id": model_id, "status": "pending"}


@app.get("/api/experiments", summary="实验列表")
def api_experiments() -> list[dict]:
    return runner.all_tasks()


@app.get("/api/experiments/{exp_id}/logs", summary="拉取已累计的日志")
def api_logs(exp_id: str) -> dict:
    task = runner.get_task(exp_id)
    if task is None:
        raise HTTPException(status_code=404, detail="实验不存在")
    return {"exp_id": exp_id, "status": task.status, "logs": "\n".join(task.log_lines)}


@app.get("/api/experiments/{exp_id}/report", summary="实验报告（MLflow 指标）")
def api_report(exp_id: str) -> dict:
    task = runner.get_task(exp_id)
    if task is None:
        raise HTTPException(status_code=404, detail="实验不存在")
    result = adapter.read_mlflow_metrics(adapter.WORKSPACE_DIR / exp_id / "mlruns")
    return {
        "exp_id": exp_id,
        "model_id": task.model_id,
        "status": task.status,
        **result,
    }


@app.websocket("/ws/logs/{exp_id}")
async def ws_logs(websocket: WebSocket, exp_id: str) -> None:
    """实时日志推送：连接即补发历史日志，随后增量推送。"""
    await websocket.accept()
    task = runner.get_task(exp_id)
    if task is None:
        await websocket.send_text(json.dumps({"error": "实验不存在"}))
        await websocket.close()
        return

    loop = asyncio.get_running_loop()
    sent_count = 0

    def on_log(line: str) -> None:
        # 从 runner 的采集线程切换到事件循环线程发送
        asyncio.run_coroutine_threadsafe(websocket.send_text(line), loop)

    # 补发历史
    for line in list(task.log_lines):
        await websocket.send_text(line)
        sent_count += 1
    task.subscribe(on_log)
    try:
        while True:
            # 客户端端只用来保活/接收关闭信号
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        task.unsubscribe(on_log)


@app.post("/api/data/download", summary="一键下载 qlib A 股数据")
def api_download_data() -> dict:
    global _download_running
    script = adapter.get_data_script()
    if not script.exists():
        raise HTTPException(status_code=404, detail=f"下载脚本不存在: {script}")
    with _download_lock:
        if _download_running:
            raise HTTPException(status_code=409, detail="数据下载已在进行中")
        _download_running = True

    def _work() -> None:
        global _download_running
        try:
            subprocess.run(
                [str(adapter.PYTHON_EXE), str(script)],
                cwd=str(script.parent),
                timeout=3600,
            )
        finally:
            with _download_lock:
                _download_running = False

    threading.Thread(target=_work, daemon=True).start()
    return {"message": "数据下载已启动，请稍后通过状态接口查询进度"}


@app.get("/api/data/status", summary="数据就绪状态")
def api_data_status() -> dict:
    return {"ready": adapter.data_status(), "downloading": _download_running}


# ---------------------------------------------------------------------------
# 数据管理：按需拉取（baostock -> qlib 格式落盘）
# ---------------------------------------------------------------------------
_fetch_jobs: dict[str, fetcher.FetchJob] = {}
_fetch_lock = threading.Lock()
FIELD_LABELS = [{"key": k, "label": v["label"]} for k, v in fetcher.FIELDS_REGISTRY.items()]


@app.get("/api/data/fields", summary="可拉取字段清单")
def api_data_fields() -> dict:
    return {"fields": FIELD_LABELS}


@app.get("/api/data/search", summary="股票代码/名称搜索")
def api_data_search(q: str) -> dict:
    results = fetcher.search_stocks(q)
    return {"results": results}


@app.get("/api/data/overview", summary="已存数据概览")
def api_data_overview() -> dict:
    return store.overview()


@app.post("/api/data/fetch", summary="创建按需拉取任务")
def api_data_fetch(payload: dict) -> dict:
    stocks = payload.get("stocks") or []
    start = str(payload.get("start_date") or "")
    end = str(payload.get("end_date") or "")
    fields = payload.get("fields") or list(fetcher.FIELDS_REGISTRY)
    if not stocks:
        raise HTTPException(status_code=400, detail="请至少选择一只股票")
    if not start or not end:
        raise HTTPException(status_code=400, detail="请指定日期区间")
    try:
        from datetime import date as _date

        if _date.fromisoformat(start) >= _date.fromisoformat(end):
            raise HTTPException(status_code=400, detail="开始日期必须早于结束日期")
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")

    norm_stocks = []
    for s in stocks:
        code = s.strip().upper()
        if "." not in code.lower() and len(code) == 8 and code[:2].upper() in ("SH", "SZ"):
            norm_stocks.append(code)
        else:
            raise HTTPException(status_code=400, detail=f"股票代码格式不合法: {s}（示例 sh600000）")

    job_id = uuid.uuid4().hex[:12]
    job = fetcher.FetchJob(
        job_id=job_id, stocks=norm_stocks, start_date=start, end_date=end, fields=fields
    )
    job._on_stock = store.merge_stock_df  # type: ignore[attr-defined]
    with _fetch_lock:
        _fetch_jobs[job_id] = job
    threading.Thread(target=_run_fetch, args=(job,), daemon=True).start()
    return {"job_id": job_id, "total": len(norm_stocks)}


def _run_fetch(job: fetcher.FetchJob) -> None:
    """后台线程：先补交易日历，再执行拉取与合并。"""
    try:
        store.update_calendar_from_bs(job.start_date, job.end_date)
        job.log("[store] 交易日历已同步")
    except Exception as exc:  # noqa: BLE001 - 日历失败不阻塞（用本地已有日历）
        job.log(f"[store] 交易日历同步失败（将使用本地日历）: {exc}")
    try:
        fetcher.fetch_stocks(job)
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.log(f"[fetch] 任务失败: {exc}")


@app.get("/api/data/fetch/{job_id}", summary="拉取任务进度")
def api_fetch_status(job_id: str) -> dict:
    job = _fetch_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job.snapshot()


@app.get("/api/data/fetch/{job_id}/logs", summary="拉取任务已累计日志")
def api_fetch_logs(job_id: str) -> dict:
    job = _fetch_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"job_id": job_id, "status": job.status, "logs": "\n".join(job.log_lines)}


@app.websocket("/ws/data/{job_id}")
async def ws_data_logs(websocket: WebSocket, job_id: str) -> None:
    """实时推送拉取任务日志。"""
    await websocket.accept()
    job = _fetch_jobs.get(job_id)
    if job is None:
        await websocket.send_text(json.dumps({"error": "任务不存在"}))
        await websocket.close()
        return
    loop = asyncio.get_running_loop()

    def on_log(line: str) -> None:
        asyncio.run_coroutine_threadsafe(websocket.send_text(line), loop)

    for line in list(job.log_lines):
        await websocket.send_text(line)
    job.subscribe(on_log)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        job.unsubscribe(on_log)


if __name__ == "__main__":
    import uvicorn

    print("=" * 50)
    print("  Qlib 量化实验平台 后端已启动: http://localhost:8000")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8000)
