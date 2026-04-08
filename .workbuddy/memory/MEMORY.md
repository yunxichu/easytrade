# 项目长期记忆

## 项目：外盘商品走势分析与预测系统
- **后端**：Flask (Python 3.12) + AKShare，运行于 `http://localhost:5000`
- **入口**：`backend/app.py`，启动命令：`python backend/app.py`
- **前端**：Jinja2 模板 + 原生 JS + Plotly.js
- **配色惯例**：涨红（#e84855）跌绿（#00c875），A股惯例，使用 CSS 变量 `--up-color`/`--down-color`
- **主题**：深色专业金融风格，参考 OpenVlab 监控台

## API 列表
- `GET /api/commodities` — 商品列表
- `GET /api/commodity/<key>/info` — 最新行情
- `GET /api/commodity/<key>/data/<period>` — 历史K线
- `GET /api/commodity/<key>/analyze/<period>` — 综合分析（含预测）
- `GET /api/commodity/<key>/predict/<period>` — 价格预测
- `GET /api/term-structure/<key>` — 期限结构
- `GET /api/strategy/backtest/<key>/<period>` — 双均线回测
- `GET /api/market/overview` — 全市场概览（新增2026-04-02）
- `GET /api/commodity/<key>/volatility/<period>` — 历史波动率序列（新增2026-04-02）
- `GET /api/market/sentiment` — 市场情绪（新增2026-04-02）
- `GET /api/stock/market/overview` — A股大盘指数（新增2026-04-08）
- `GET /api/stock/list` — A股行情列表（新增2026-04-08）
- `GET /api/stock/sectors` — 行业板块涨跌（新增2026-04-08）
- `GET /api/stock/kline/<code>` — 个股K线（新增2026-04-08）
- `GET /api/stock/breadth` — 市场宽度（新增2026-04-08）
- `GET /api/cross-section/backtest` — 截面多空回测（新增2026-04-08）
- `GET /api/cross-section/portfolio` — 最新持仓（新增2026-04-08）
- `GET /api/cross-section/factors` — 因子截面得分（新增2026-04-08）
- `GET /api/cross-section/prices/<asset>` — 单品种价格（新增2026-04-08）

## 新增前端功能（2026-04-02）
- 全市场概览大表（迷你SVG走势图、流量占比、排序）
- TOP5 涨/跌排行
- 波动率分析（HV20/HV60）
- 市场情绪评分（RSI + 动量综合）
- 品种相关性热力矩阵（皮尔逊系数）
- K线/折线图切换
- 预测置信区间带

## research/ 量化研究目录（新增2026-04-02）
- **data_fetcher.py**：Yahoo Finance → AKShare → GBM合成数据三层体系
- **strategy_tqsdk.py**：天勤量化兼容回测框架（MA5/MA20 + MACD）
- **cointegration_arbitrage.py**：Engle-Granger 协整套利全市场扫描 + z-score 模拟交易
- **generate_report.py**：ReportLab PDF 报告生成（SimHei 中文字体）
- **outputs/**：结果图表 + JSON + CSV + PDF 报告

## 数据说明
- Yahoo Finance（yfinance）：国内网络受速率限制，需代理（HTTPS_PROXY=http://127.0.0.1:7890）
- AKShare：当前环境也受限，返回"Expected object or value"
- GBM合成数据：基于真实历史参数的几何布朗运动，统计性质合理，保证代码可运行

## 量化全流程模块（/quant）
- **前端**：quant.html + quant.js，5步骤向导式界面
- **后端**：quant_api.py Blueprint，预设6个API接口
- **流程**：数据接入 → 因子计算 → 模型训练 → 组合优化 → 信号输出

## 作业2：股票市场信息模块（2026-04-08）
- **后端**：stock_api.py Blueprint，AKShare实时数据 + 随机延迟反爬 + 5分钟缓存 + 模拟数据降级
- **前端**：stock.html，大盘指数/市场宽度/行业板块/行情列表/K线弹窗
- **路由**：/stock

## Project：截面多空交易系统（2026-04-08）
- **后端**：cross_section_api.py Blueprint
  - 品种全域：12个外盘品种（黄金、原油、铜等）
  - 多因子：MOM_1M/MOM_3M/VOL_INV/RSI_REV/MA_DEV，截面Z-score标准化
  - 回测引擎：日/周换仓、成本+滑点、IC分析、月度热力
- **前端**：cross_section.html，深色金融风格
  - 控制面板（换仓/分位参数）、净值曲线、月度热力表、IC序列、因子热力矩阵、持仓表
- **路由**：/cross-section

## 依赖
- requirements.txt 已添加：statsmodels, scipy, reportlab

