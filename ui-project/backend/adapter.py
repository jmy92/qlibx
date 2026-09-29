"""适配层：本文件是唯一与 Qlib 引擎交互的模块。

设计原则（防止 qlib 升级破坏 UI）：
- 后端其他代码绝不 import qlib，只通过本文件暴露的接口工作
- 只依赖 qlib 的对外契约：yaml 配置格式、qrun 命令、MLflow 结果目录
- qlib 升级时只需修改本文件
"""

import json
import os
import shutil
from pathlib import Path
from typing import Any

import yaml

BACKEND_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BACKEND_DIR / "templates"
WORKSPACE_DIR = BACKEND_DIR / "workspace"

# 行情数据目录：跟随项目存放（不占 C 盘）
PROJECT_DATA_DIR = BACKEND_DIR.parent / "data"
DATA_DIR_PLACEHOLDER = "{{DATA_DIR}}"

# 用户指定的后端 Python 虚拟环境（qrun 所在位置）
CONDA_ENV_DIR = Path(r"D:\workspace_buddy\conda_envs\my_temp")
QRUN_EXE = CONDA_ENV_DIR / "Scripts" / "qrun.exe"
PYTHON_EXE = CONDA_ENV_DIR / "python.exe"

# qlib 输出指标名 -> 前端展示用的中文结构
_METRIC_ALIASES: dict[str, str] = {
    "IC": "ic",
    "ICIR": "icir",
    "Rank IC": "rank_ic",
    "Rank ICIR": "rank_icir",
    "Annualized Return": "annualized_return",
    "Information Ratio": "information_ratio",
    "Max Drawdown": "max_drawdown",
}


def list_model_templates() -> list[dict[str, Any]]:
    """扫描 templates 目录，返回全部模型模板的元数据列表。"""
    models: list[dict[str, Any]] = []
    for path in sorted(TEMPLATES_DIR.glob("*.yaml")):
        meta = parse_template_meta(path)
        models.append(
            {
                "id": path.stem,
                "name": meta.get("name", path.stem),
                "group": meta.get("group", "其他"),
                "description": meta.get("description", ""),
                "requires_gpu": bool(meta.get("requires_gpu", False)),
                "params_schema": meta.get("params_schema", {}),
            }
        )
    return models


def parse_template_meta(path: Path) -> dict[str, Any]:
    """解析 yaml 模板顶部的 '# meta: {...}' JSON 注释行。

    解析失败时返回空字典，不影响模板列表展示。
    """
    try:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            stripped = line.strip()
            if stripped.startswith("# meta:"):
                return json.loads(stripped[len("# meta:"):].strip())
            if stripped.startswith("# ===") or stripped.startswith("# 模板说明"):
                continue
            if stripped and not stripped.startswith("#"):
                break  # 已进入正式 yaml 内容
    except Exception:
        pass
    return {}


def render_config(template_path: Path, params: dict[str, Any]) -> str:
    """把占位符替换为用户参数，返回渲染后的 yaml 文本。

    占位符：{{START_DATE}} {{TRAIN_END}} {{TEST_START}} {{END_DATE}}
            {{FIT_START}} {{FIT_END}} {{MARKET}} {{ACCOUNT}} {{TOPK}} {{N_DROP}}
    """
    text = template_path.read_text(encoding="utf-8-sig")
    mapping = {
        "{{START_DATE}}": str(params["start_date"]),
        "{{TRAIN_END}}": str(params["train_end"]),
        "{{TEST_START}}": str(params["test_start"]),
        "{{END_DATE}}": str(params["end_date"]),
        "{{FIT_START}}": str(params["start_date"]),
        "{{FIT_END}}": str(params["train_end"]),
        "{{MARKET}}": str(params["market"]),
        "{{ACCOUNT}}": str(int(params["account"])),
        "{{TOPK}}": str(int(params["topk"])),
        "{{N_DROP}}": str(int(params["n_drop"])),
        # 行情数据父目录：用正斜杠，避免 qrun 子进程解析 Windows 盘符路径时
        # 出现反斜杠转义问题（qlib 要求 provider_uri 为字符串路径）
        "{{DATA_DIR}}": str(PROJECT_DATA_DIR).replace("\\", "/"),
    }
    for key, value in mapping.items():
        text = text.replace(key, value)
    # 合法性校验：渲染结果必须是可解析的 yaml
    yaml.safe_load(text)
    return text


def split_date_range(start: str, end: str) -> dict[str, str]:
    """把总日期区间按 70%/15%/15% 切分为训练/验证/回测三段。

    返回 train_end（训练段结束）与 test_start（回测段开始）。
    """
    from datetime import date, timedelta

    start_d = date.fromisoformat(str(start))
    end_d = date.fromisoformat(str(end))
    total_days = (end_d - start_d).days
    if total_days <= 0:
        raise ValueError("结束日期必须晚于开始日期")
    train_end = start_d + timedelta(days=int(total_days * 0.70))
    test_start = start_d + timedelta(days=int(total_days * 0.85))
    return {"train_end": train_end.isoformat(), "test_start": test_start.isoformat()}


def build_qrun_command(config_path: Path) -> list[str]:
    """构建 qrun 命令。环境内未找到时抛出带中文提示的异常。"""
    if QRUN_EXE.exists():
        return [str(QRUN_EXE), str(config_path)]
    # 退路：用虚拟环境 python -m 方式调用 qlib.cli.run
    if PYTHON_EXE.exists():
        return [str(PYTHON_EXE), "-m", "qlib.cli.run", str(config_path)]
    raise RuntimeError(
        f"未在 {CONDA_ENV_DIR} 中找到 qrun 或 qlib 安装，"
        "请先在该虚拟环境中执行: pip install pyqlib==0.9.7"
    )


def read_mlflow_metrics(mlruns_dir: Path) -> dict[str, Any]:
    """从实验专属的 mlruns 目录读取最新 run 的指标，映射为中文友好结构。

    qlib 的记录器（SignalRecord/SigAnaRecord/PortAnaRecord）会把指标写入
    MLflow；这里只读取，不与 qlib 内部 API 耦合。读不到时返回空结构。
    """
    if not mlruns_dir.exists():
        return {"metrics": {}, "raw": {}}
    try:
        import mlflow
        from mlflow.tracking import MlflowClient

        mlflow.set_tracking_uri(mlruns_dir.as_uri())
        client = MlflowClient(tracking_uri=mlruns_dir.as_uri())
        exp = client.get_experiment_by_name("workflow")
        if exp is None:
            # 找不到指定名字就取第一个实验
            exps = client.search_experiments()
            if not exps:
                return {"metrics": {}, "raw": {}}
            exp = exps[0]
        runs = client.search_runs([exp.experiment_id], order_by=["attributes.start_time DESC"])
        if not runs:
            return {"metrics": {}, "raw": {}}
        raw = runs[0].data.metrics
        metrics: dict[str, Any] = {}
        for qlib_name, key in _METRIC_ALIASES.items():
            for raw_key, value in raw.items():
                if raw_key.lower().strip() == qlib_name.lower():
                    metrics[key] = value
                    break
        return {"metrics": metrics, "raw": raw}
    except Exception as exc:  # noqa: BLE001 - 指标读取失败不应拖垮报告接口
        return {"metrics": {}, "raw": {}, "error": str(exc)}


def data_status() -> bool:
    """检查 qlib A 股日频数据是否已就绪。"""
    cal = PROJECT_DATA_DIR / "cn_data" / "calendars" / "day.txt"
    return cal.exists()


def get_data_script() -> Path:
    """返回官方数据下载脚本路径。"""
    return BACKEND_DIR.parent.parent / "scripts" / "get_data.py"


def ensure_workspace(exp_id: str) -> Path:
    """创建并返回实验专属工作目录。"""
    d = WORKSPACE_DIR / exp_id
    d.mkdir(parents=True, exist_ok=True)
    return d
