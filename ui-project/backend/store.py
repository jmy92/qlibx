"""qlib 数据目录的读写与合并。

职责：
- 把 fetcher 拉到的 DataFrame 合并进 qlib 格式数据集（重写 bin 文件）
- 读取已存数据的概览信息（股票清单、覆盖区间、字段清单）
- 维护交易日历与 instruments/all.txt

qlib bin 文件格式（与官方 dump_bin.py 一致）：
    前 4 字节: float32，起始日索引（相对日历第 0 天的偏移）
    之后:      float32 数组，逐日数值
"""

import shutil
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from adapter import PROJECT_DATA_DIR

# 全量数据集目录（与官方 cn_data 并存）
DATASET_DIR = PROJECT_DATA_DIR / "cn_data_full"
CAL_DIR = DATASET_DIR / "calendars"
INS_DIR = DATASET_DIR / "instruments"
FEA_DIR = DATASET_DIR / "features"
STAGING_DIR = PROJECT_DATA_DIR / "staging"

# bin 文件名映射：存储字段名 -> qlib 特征名（qlib 内以 $field 引用，文件名为 field.day.bin）
STORAGE_FIELDS = [
    "open", "high", "low", "close", "preclose", "volume", "amount",
    "turn", "pct_chg", "change_amt", "amplitude",
]

# 读锁：合并过程对同一股票目录写 bin，读概览时避免读到半写状态
_merge_lock = threading.Lock()


def ensure_dataset() -> None:
    """确保全量数据集目录结构存在。"""
    for d in (CAL_DIR, INS_DIR, FEA_DIR):
        d.mkdir(parents=True, exist_ok=True)


def read_calendar() -> list[str]:
    """读取交易日历（升序日期字符串列表）。"""
    p = CAL_DIR / "day.txt"
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def write_calendar(dates: list[str]) -> None:
    CAL_DIR.mkdir(parents=True, exist_ok=True)
    p = CAL_DIR / "day.txt"
    tmp = p.with_suffix(".tmp")
    tmp.write_text("\n".join(sorted(set(dates))) + "\n", encoding="utf-8")
    tmp.replace(p)


def load_stock_df(qlib_code: str) -> pd.DataFrame:
    """从 bin 文件读出单只股票的全部已存数据，index 为日期。

    股票尚无数据时返回空 DataFrame。
    """
    stock_dir = FEA_DIR / qlib_code.lower()
    if not stock_dir.exists():
        return pd.DataFrame()
    cal = read_calendar()
    frames = {}
    for f in STORAGE_FIELDS:
        p = stock_dir / f"{f}.day.bin"
        if not p.exists():
            continue
        with open(p, "rb") as fp:
            start_idx = int(np.frombuffer(fp.read(4), dtype="<f")[0])
            arr = np.fromfile(fp, dtype="<f")
        end_idx = start_idx + len(arr)
        series = pd.Series(arr, index=cal[start_idx:end_idx], name=f)
        frames[f] = series
    if not frames:
        return pd.DataFrame()
    df = pd.DataFrame(frames)
    df.index.name = "date"
    return df


def merge_stock_df(qlib_code: str, new_df: pd.DataFrame) -> dict[str, Any]:
    """把新拉取的数据与已存数据合并后重写 bin 文件。

    合并规则：同日期同字段以新数据为准；日期并集排序。
    返回合并后的覆盖区间信息。
    """
    ensure_dataset()
    with _merge_lock:
        old_df = load_stock_df(qlib_code)
        if not old_df.empty and not new_df.empty:
            merged = old_df.combine_first(new_df)
        else:
            merged = new_df if not new_df.empty else old_df
        merged = merged.sort_index()
        # 日期序列必须落在日历上：先扩展日历
        cal = read_calendar()
        cal_set = set(cal)
        new_dates = [d for d in merged.index.astype(str) if d not in cal_set]
        if new_dates:
            cal = sorted(set(cal) | set(merged.index.astype(str)))
            write_calendar(cal)
            cal = read_calendar()

        stock_dir = FEA_DIR / qlib_code.lower()
        if stock_dir.exists():
            shutil.rmtree(stock_dir)  # 简单起见整目录重写（单只股票数据量小）
        stock_dir.mkdir(parents=True, exist_ok=True)

        cal_index = {d: i for i, d in enumerate(cal)}
        start_idx = min(cal_index[d] for d in merged.index.astype(str))
        for f in STORAGE_FIELDS:
            if f not in merged.columns:
                continue
            series = merged[f]
            # 起始索引之后按日历对齐：用 reindex 补齐缺失交易日为 NaN
            days = cal[start_idx : start_idx + len(series)]
            # 逐字段写 bin：以该字段自身的非 NaN 范围为准，日历对齐
            valid = series.dropna()
            if valid.empty:
                continue
            s_idx = min(cal_index[d] for d in valid.index.astype(str))
            e_idx = max(cal_index[d] for d in valid.index.astype(str))
            span = cal[s_idx : e_idx + 1]
            arr = valid.reindex(span).to_numpy(dtype="<f")
            with open(stock_dir / f"{f}.day.bin", "wb") as fp:
                fp.write(np.array([s_idx], dtype="<f").tobytes())
                fp.write(arr.tobytes())

        _append_instrument(qlib_code, merged.index.min(), merged.index.max())
        return {
            "code": qlib_code,
            "start": str(merged.index.min()),
            "end": str(merged.index.max()),
            "days": int(merged["close"].notna().sum()) if "close" in merged else len(merged),
            "fields": [c for c in STORAGE_FIELDS if c in merged.columns],
        }


def _append_instrument(qlib_code: str, start: str, end: str) -> None:
    """把股票加入 all.txt（已存在则更新区间）。"""
    ensure_dataset()
    p = INS_DIR / "all.txt"
    entries: dict[str, tuple[str, str]] = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                entries[parts[0]] = (parts[1], parts[2])
    old = entries.get(qlib_code)
    if old:
        start = min(start, old[0])
        end = max(end, old[1])
    entries[qlib_code] = (start, end)
    lines = [f"{c}\t{s}\t{e}" for c, (s, e) in sorted(entries.items())]
    tmp = p.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(p)


def overview() -> dict[str, Any]:
    """数据概览：日历区间、股票数、每只股票的覆盖区间。"""
    cal = read_calendar()
    p = INS_DIR / "all.txt"
    stocks: list[dict[str, str]] = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                stocks.append({"code": parts[0], "start": parts[1], "end": parts[2]})
    fields_avail: set[str] = set()
    if FEA_DIR.exists():
        for d in FEA_DIR.iterdir():
            if d.is_dir():
                for binf in d.glob("*.day.bin"):
                    fields_avail.add(binf.name.replace(".day.bin", ""))
    return {
        "dataset_dir": str(DATASET_DIR),
        "calendar_start": cal[0] if cal else None,
        "calendar_end": cal[-1] if cal else None,
        "trading_days": len(cal),
        "stock_count": len(stocks),
        "stocks": stocks,
        "fields": sorted(fields_avail),
        "ready": bool(cal and stocks),
    }


def update_calendar_from_bs(start: str, end: str) -> list[str]:
    """用 baostock 的交易日历补齐指定区间的交易日（数据对齐基准）。"""
    import baostock as bs

    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")
    try:
        rs = bs.query_trade_dates(start_date=start, end_date=end)
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
    finally:
        bs.logout()
    trading = [r[0] for r in rows if r[1] == "1"]
    cal = set(read_calendar()) | set(trading)
    write_calendar(sorted(cal))
    return trading
