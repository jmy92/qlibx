# Qlib 中文使用指南

> Microsoft Qlib（PyPI 包名 `pyqlib`）—— 一个开源的 AI 导向量化投资研究平台。

## 一、这是什么

**一句话：微软开源的"炒股 AI 工具箱"。**

它用数据和机器学习模型来预测股票涨跌、决定买卖，帮你免去重复造轮子，覆盖量化投资全链路：

```
数据获取 → 特征工程 → 模型训练 → 回测评估 → 组合优化 → 订单执行
```

支持三种机器学习范式：

- **监督学习**：从金融数据中挖掘复杂的非线性规律（预测涨跌）
- **市场动态建模**：用概念漂移自适应技术应对市场变化
- **强化学习**：建模连续投资决策，优化交易策略

> ⚠️ 注意：它不联网炒股、不保证赚钱，是研究和实验工具。

## 二、项目结构

```
qlib/                  # 核心库代码
├── data/              #   数据层（含 Cython 高性能引擎）
├── model/             #   模型
├── strategy/          #   策略
├── backtest/          #   回测
├── rl/                #   强化学习框架
├── workflow/          #   工作流
└── cli/               #   qrun 命令行入口

examples/benchmarks/   # 30+ 基准模型示例（LightGBM、LSTM、Transformer 等）
scripts/               # 数据采集与下载脚本
tests/                 # 测试套件
docs/                  # Sphinx 文档
```

## 三、技术栈

| 类别 | 内容 |
|---|---|
| 语言 | Python ≥ 3.8（支持至 3.12）+ Cython（性能热点编译） |
| 核心依赖 | numpy、pandas>=1.1、lightgbm、mlflow<3.13、loguru、cvxpy、pydantic-settings |
| 数据存储 | 本地文件系统（默认）/ MongoDB / Redis（任务调度锁） |
| 可选扩展 | `[rl]` tianshou + torch；`[analysis]` plotly<7；`[dev]` pytest |
| 构建工具 | setuptools + setuptools-scm、Makefile、Dockerfile、GitHub Actions |
| CLI 入口 | `qrun`（对应 `qlib.cli.run:run`） |

## 四、怎么用

### 1. 安装

```powershell
# 方式一：直接装发布版
pip install pyqlib

# 方式二：源码开发模式（推荐，会编译 Cython 扩展）
pip install numpy
pip install --upgrade cython
pip install -e .[dev]
```

### 2. 下载示例数据（首次必须）

```powershell
python scripts/get_data.py
```

数据默认放到 `~/.qlib/qlib_data/cn_data`（A 股日频数据）。

### 3. 一键跑实验（最常用）

```powershell
qrun examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml
```

这一条命令会自动完成：**数据集构建 → 模型训练 → 回测 → 评估报告**。

- 加 `--debug 1` 进入调试模式
- 想换模型？把配置文件换成 `examples/benchmarks/` 下其他模型的 yaml 即可（LSTM、GRU、Transformer、XGBoost、HIST 等 30+ 个）

### 4. 交互式分析

```powershell
pip install .[analysis]
jupyter notebook examples/workflow_by_code.ipynb
```

可得到图形化的收益/风险报告。

### 5. 自己写代码定制

```python
import qlib
qlib.init(provider_uri="~/.qlib/qlib_data/cn_data")  # 指定数据目录
# 然后定义你的因子、模型、回测策略……
```

## 五、常用术语速查

| 术语 | 意思 |
|---|---|
| `qrun` | 一键跑实验的命令行工具 |
| yaml 配置 | 实验说明书（用哪个模型、什么数据、怎么回测） |
| Alpha158 | 一套常用的 158 个选股指标（特征集） |
| Alpha360 | 另一套特征集（基于最近 60 天的价量数据） |
| 回测（Backtest） | 用历史数据模拟炒股，检验策略行不行 |
| CSI300 / CSI500 | 沪深300 / 中证500 股票池基准 |

## 六、常见问题

**Q: 安装时报版本号错误？**
版本号由 `setuptools-scm` 从 git 标签动态生成，如果目录不是完整 git 仓库，可设置环境变量绕过：
```powershell
$env:SETUPTOOLS_SCM_PRETEND_VERSION="0.9.7"
```

**Q: Windows 上编译失败？**
先确保装了 `numpy` 和 `cython`，且系统有 C++ 编译工具链（Visual Studio Build Tools）。

**Q: 跑 `qrun` 提示找不到数据？**
先执行 `python scripts/get_data.py` 下载数据，再确认 yaml 配置里 `provider_uri` 指向的数据目录正确。

## 七、更多资源

- 官方文档：https://qlib.readthedocs.io
- 论文：[Qlib: An AI-oriented Quantitative Investment Platform](https://arxiv.org/abs/2009.11189)
- 姊妹项目 [RD-Agent](https://github.com/microsoft/RD-Agent)：基于 LLM 的自动化因子挖掘与模型优化
