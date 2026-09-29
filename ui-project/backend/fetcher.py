"""字段注册表与 baostock 行情拉取器。

设计要点：
- 字段注册表是唯一需要维护的字段清单，新增字段只需加一行
- 拉取按需进行：只拉用户指定的股票、日期、字段
- 全程不依赖 qlib，输出标准 DataFrame，由 store.py 负责落盘
"""

import time
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------------------
# 字段注册表：存储字段名 -> baostock 列名 + 中文说明
# 振幅 baostock 没有现成列，由 preclose/high/low 计算
# ---------------------------------------------------------------------------
FIELDS_REGISTRY: dict[str, dict[str, Any]] = {
    "open": {"bs": "open", "label": "开盘价", "type": "price"},
    "high": {"bs": "high", "label": "最高价", "type": "price"},
    "low": {"bs": "low", "label": "最低价", "type": "price"},
    "close": {"bs": "close", "label": "收盘价", "type": "price"},
    "preclose": {"bs": "preclose", "label": "昨收价", "type": "price"},
    "volume": {"bs": "volume", "label": "成交量(股)", "type": "raw"},
    "amount": {"bs": "amount", "label": "成交额(元)", "type": "raw"},
    "turn": {"bs": "turn", "label": "换手率(%)", "type": "raw"},
    "pct_chg": {"bs": "pctChg", "label": "涨跌幅(%)", "type": "raw"},
    "change_amt": {"bs": None, "label": "涨跌额", "type": "derived"},  # close - preclose
    "amplitude": {"bs": None, "label": "振幅(%)", "type": "derived"},  # (high-low)/preclose*100
}

# 必拉字段：派生字段与价格字段的前置依赖，无论如何都会拉取
_BASE_BS_COLS = {"date", "open", "high", "low", "close", "preclose"}

LogFn = Callable[[str], None]


@dataclass
class FetchJob:
    """一次按需拉取任务的描述与进度。"""

    job_id: str
    stocks: list[str]  # qlib 风格代码，如 ["SH600000", "SZ000001"]
    start_date: str  # YYYY-MM-DD
    end_date: str
    fields: list[str]  # FIELDS_REGISTRY 的键子集
    status: str = "pending"  # pending / running / done / failed
    total: int = 0
    finished: int = 0
    ok_stocks: list[str] = field(default_factory=list)
    failed_stocks: list[str] = field(default_factory=list)
    log_lines: list[str] = field(default_factory=list)
    _subscribers: list[LogFn] = field(default_factory=list)

    def log(self, line: str) -> None:
        self.log_lines.append(line)
        for cb in list(self._subscribers):
            try:
                cb(line)
            except Exception:
                pass

    def subscribe(self, cb: LogFn) -> None:
        self._subscribers.append(cb)

    def unsubscribe(self, cb: LogFn) -> None:
        if cb in self._subscribers:
            self._subscribers.remove(cb)

    def snapshot(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "total": self.total,
            "finished": self.finished,
            "ok": len(self.ok_stocks),
            "failed": self.failed_stocks,
            "log_count": len(self.log_lines),
        }


def qlib_code_to_bs(qlib_code: str) -> str:
    """qlib 代码（SH600000）转 baostock 代码（sh.600000）。"""
    code = qlib_code.strip().lower()
    if "." in code:
        return code
    if len(code) == 8 and code[:2] in ("sh", "sz"):
        return f"{code[:2]}.{code[2:]}"
    raise ValueError(f"无法识别的股票代码: {qlib_code}（应为 sh600000 / SZ000001 格式）")


def bs_code_to_qlib(bs_code: str) -> str:
    """baostock 代码（sh.600000）转 qlib 代码（SH600000）。"""
    prefix, num = bs_code.split(".")
    return prefix.upper() + num


def _query_stock_list(keyword: str) -> list[dict[str, str]]:
    """查询股票列表（代码-名称对照），支持代码与名称模糊搜索。

    结果缓存：进程内一次会话即可。
    """
    import baostock as bs

    rows: list[dict[str, str]] = []
    rs = bs.query_all_stock(day="")  # 空日期取最近交易日全部证券
    while rs.error_code == "0" and rs.next():
        code, trade_date, code_name = rs.get_row_data()
        # 只保留 A 股现货（排除指数 sh.000 / sz.399 开头指数段）
        if code.startswith(("sh.000", "sz.399")):
            continue
        rows.append({"code": bs_code_to_qlib(code), "bs_code": code, "name": code_name})
    return rows


def search_stocks(keyword: str, limit: int = 30) -> list[dict[str, str]]:
    """按关键字搜索股票（代码或名称），返回 [{code, name}]。"""
    keyword = keyword.strip().lower()
    if not keyword:
        return []
    try:
        import baostock as bs

        lg = bs.login()
        if lg.error_code != "0":
            return []
        try:
            all_stocks = _query_stock_list(keyword)
        finally:
            bs.logout()
    except Exception:
        return []

    matched = []
    for item in all_stocks:
        if keyword in item["code"].lower() or keyword in item["name"].lower():
            matched.append({"code": item["code"], "name": item["name"]})
            if len(matched) >= limit:
                break
    return matched


def fetch_stocks(job: FetchJob) -> None:
    """执行拉取任务：逐只股票拉数据，产出 DataFrame 交给回调处理。

    每只股票处理成功后调用 on_stock(stock_code, df)（由 store 层提供）。
    """
    import baostock as bs
    import pandas as pd

    fields = list(dict.fromkeys(job.fields))  # 去重保序
    unknown = [f for f in fields if f not in FIELDS_REGISTRY]
    if unknown:
        raise ValueError(f"未知字段: {unknown}，可用字段: {list(FIELDS_REGISTRY)}")

    need_derived = any(FIELDS_REGISTRY[f]["type"] == "derived" for f in fields)
    bs_cols = ["date", "code"]
    for f in fields:
        col = FIELDS_REGISTRY[f]["bs"]
        if col:
            bs_cols.append(col)
    if need_derived:
        # 派生字段依赖 close/preclose/high/low，已在 _BASE_BS_COLS 覆盖
        for col in sorted(_BASE_BS_COLS - set(bs_cols)):
            bs_cols.append(col)
    bs_cols = list(dict.fromkeys(bs_cols))

    job.status = "running"
    job.total = len(job.stocks)
    job.log(f"[fetch] 任务开始: {len(job.stocks)} 只股票, {job.start_date} ~ {job.end_date}")
    job.log(f"[fetch] 拉取字段: {fields}")

    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")
    job.log("[fetch] baostock 登录成功")

    try:
        for idx, qlib_code in enumerate(job.stocks):
            bs_code = qlib_code_to_bs(qlib_code)
            df = _fetch_one(bs, bs_code, bs_cols, job.start_date, job.end_date, job.log)
            if df is None:
                job.failed_stocks.append(qlib_code)
                job.finished = idx + 1
                continue
            try:
                on_stock = job._on_stock  # type: ignore[attr-defined]
                on_stock(qlib_code, df)
                job.ok_stocks.append(qlib_code)
                job.log(f"[fetch] {qlib_code} 完成，{len(df)} 个交易日")
            except Exception as exc:  # noqa: BLE001 - 单只失败不阻塞任务
                job.failed_stocks.append(qlib_code)
                job.log(f"[fetch] {qlib_code} 落盘失败: {exc}")
            job.finished = idx + 1
            time.sleep(0.2)  # 轻微限速，避免触发风控
    finally:
        bs.logout()
        job.status = "done" if not job.failed_stocks else "done"
        job.log(
            f"[fetch] 任务结束: 成功 {len(job.ok_stocks)} / {job.total}"
            + (f"，失败 {job.failed_stocks}" if job.failed_stocks else "")
        )


def _fetch_one(
    bs: Any,
    bs_code: str,
    bs_cols: list[str],
    start: str,
    end: str,
    log: LogFn,
    retries: int = 3,
):
    """拉取单只股票，返回带派生字段的 DataFrame；失败返回 None。"""
    import pandas as pd

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            rs = bs.query_history_k_data_plus(
                bs_code, ",".join(bs_cols), start_date=start, end_date=end,
                frequency="d", adjustflag="3",  # 3=不复权
            )
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())
            if rs.error_code != "0":
                raise RuntimeError(f"baostock 查询错误 {rs.error_code}: {rs.error_msg}")
            if not rows:
                log(f"[fetch] {bs_code} 区间内无数据（可能停牌或未上市）")
                return None
            df = pd.DataFrame(rows, columns=bs_cols)
            return _normalize(df)
        except Exception as exc:  # noqa: BLE001 - 重试机制
            last_err = exc
            log(f"[fetch] {bs_code} 第 {attempt} 次尝试失败: {exc}")
            time.sleep(1.5 * attempt)
    log(f"[fetch] {bs_code} 放弃: {last_err}")
    return None


def _normalize(df):
    """列名转换 + 类型转换 + 派生字段计算。"""
    import pandas as pd

    rename = {v["bs"]: k for k, v in FIELDS_REGISTRY.items() if v["bs"]}
    df = df.rename(columns=rename)
    # 空串转 NaN 再转 float
    for col in df.columns:
        if col in ("date", "code"):
            continue
        df[col] = pd.to_numeric(df[col].replace("", pd.NA), errors="coerce")
    # 派生字段：只要依赖存在就计算（无论用户是否显式选择）
    if {"close", "preclose"}.issubset(df.columns):
        df["change_amt"] = df["close"] - df["preclose"]
    if {"high", "low", "preclose"}.issubset(df.columns) and (df["preclose"] != 0).any():
        df["amplitude"] = (df["high"] - df["low"]) / df["preclose"] * 100
    # 日期作为索引，供 store 合并与日历对齐使用
    df["date"] = df["date"].astype(str)
    return df.set_index("date")
