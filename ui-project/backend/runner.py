"""任务管理器：以子进程方式执行 qrun，采集日志并通过 WebSocket 广播。

本模块不 import qlib，只负责进程管理与日志流。
"""

import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from adapter import build_qrun_command

# 线程安全锁：保护任务字典与订阅者列表
_LOCK = threading.Lock()
_TASKS: dict[str, "ExperimentTask"] = {}


@dataclass
class ExperimentTask:
    """单个实验的运行状态。"""

    exp_id: str
    model_id: str
    config_path: str
    status: str = "pending"  # pending / running / done / failed
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    log_lines: list[str] = field(default_factory=list)
    returncode: int | None = None
    # WebSocket 订阅者回调：每条新日志到达时调用
    _subscribers: list[Callable[[str], Any]] = field(default_factory=list)

    def append_log(self, line: str) -> None:
        self.log_lines.append(line)
        with _LOCK:
            subs = list(self._subscribers)
        for cb in subs:
            try:
                cb(line)
            except Exception:
                # 失效的订阅者直接摘除
                with _LOCK:
                    if cb in self._subscribers:
                        self._subscribers.remove(cb)

    def subscribe(self, callback: Callable[[str], Any]) -> None:
        with _LOCK:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[str], Any]) -> None:
        with _LOCK:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def snapshot(self) -> dict[str, Any]:
        return {
            "exp_id": self.exp_id,
            "model_id": self.model_id,
            "status": self.status,
            "created_at": self.created_at,
            "returncode": self.returncode,
            "log_count": len(self.log_lines),
        }


def get_task(exp_id: str) -> ExperimentTask | None:
    with _LOCK:
        return _TASKS.get(exp_id)


def all_tasks() -> list[dict[str, Any]]:
    with _LOCK:
        tasks = sorted(_TASKS.values(), key=lambda t: t.created_at, reverse=True)
    return [t.snapshot() for t in tasks]


def start_experiment(exp_id: str, model_id: str, config_path: str) -> ExperimentTask:
    """创建任务并启动后台线程执行 qrun。重复 exp_id 会抛错。"""
    with _LOCK:
        if exp_id in _TASKS:
            raise ValueError(f"实验 {exp_id} 已存在")
        task = ExperimentTask(exp_id=exp_id, model_id=model_id, config_path=config_path)
        _TASKS[exp_id] = task
    threading.Thread(target=_run, args=(task,), daemon=True).start()
    return task


def _run(task: ExperimentTask) -> None:
    """线程主体：启动 qrun 子进程并逐行采集 stdout。"""
    task.status = "running"
    try:
        cmd = build_qrun_command(__import__("pathlib").Path(task.config_path))
        task.append_log(f"[runner] 启动命令: {' '.join(cmd)}")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(task.config_path.rsplit("\\", 1)[0] if "\\" in task.config_path else "."),
        )
        task.returncode = proc.wait() if proc.stdout is None else None
        # 逐行读取直到进程结束
        if proc.stdout is not None:
            for line in proc.stdout:
                task.append_log(line.rstrip())
        task.returncode = proc.wait()
        if task.returncode == 0:
            task.status = "done"
            task.append_log("[runner] 实验完成，可以查看报告")
        else:
            task.status = "failed"
            task.append_log(f"[runner] 实验失败，退出码 {task.returncode}")
    except Exception as exc:  # noqa: BLE001 - 任何启动异常都转为 failed 状态
        task.status = "failed"
        task.returncode = -1
        task.append_log(f"[runner] 启动失败: {exc}")
