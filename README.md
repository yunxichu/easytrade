# 外盘商品走势分析与预测系统

> **仓库地址**：https://github.com/yunxichu/easytrade  
> **技术栈**：Flask + AKShare/yfinance + Plotly.js + 原生 JS

## 项目简介

本项目是一个**完整的量化金融 Web 应用系统**，覆盖外盘商品走势分析、A股市场信息、截面多空交易策略、量化研究全流程四大模块。后端采用 Flask（Python 3.12），前端使用 Plotly.js 实现专业金融图表，整体采用深色专业金融风格。

## 功能模块总览

| 路由 | 模块名称 | 核心功能 |
|------|---------|---------|
| `/` | 外盘商品走势 | K线图、均线、价格预测（线性回归）、期限结构、回测 |
| `/stock` | A股市场信息 | 大盘指数、行业板块、市场宽度、个股K线 |
| `/cross-section` | 截面多空策略 | 多因子截面策略、IC分析、月度热力、净值曲线 |
| `/quant` | 量化研究向导 | 五步骤全流程：数据→因子→模型→优化→信号 |

## 功能特性

### 模块一：外盘商品走势与预测（主页）
1. **数据获取**：AKShare → Yahoo Finance → GBM合成数据（三层降级体系）
2. **走势展示**：交互式K线图、价格走势图（含20日/60日均线）、K线/折线切换
3. **合约信息**：最新价、涨跌幅（红涨绿跌）、开盘/最高/最低/前收、成交量/持仓量
4. **价格预测**：线性回归预测未来30天，含置信区间带
5. **期限结构**：升水/贴水判断，跨期套利策略建议
6. **全市场概览**：迷你SVG走势图、TOP5涨跌排行、品种相关性热力矩阵
7. **波动率分析**：HV20/HV60历史波动率对比
8. **市场情绪**：RSI + 动量综合情绪评分

### 模块二：A股市场信息（/stock）
- 大盘三大指数实时行情（上证/深证/创业板）
- 市场宽度（涨跌家数、涨停/跌停统计）
- 行业板块涨跌排名（条形图）
- A股全市场行情列表（搜索/排序）
- 个股K线弹窗查询

### 模块三：截面多空交易策略（/cross-section）

基于学术文献（Jegadeesh & Titman 1993, Moskowitz et al. 2012）实现的专业截面多空策略：

- **标的宇宙**：12个主要外盘商品（黄金、原油、铜、白银、天然气、铝、锌、镍、大豆、玉米、小麦、棉花）
- **多因子模型**：MOM_1M / MOM_3M / VOL_INV / RSI_REV / MA_DEV
- **截面标准化**：Z-score 跨品种标准化（避免未来泄漏）
- **回测引擎**：支持日/周换仓，含交易成本+滑点，输出 IC、ICIR、夏普、最大回撤
- **可视化**：净值曲线（多/空/组合）、月度热力表、因子IC序列、因子得分热力矩阵

### 模块四：量化研究向导（/quant）
五步骤向导式界面：数据接入 → 因子计算 → 模型训练 → 组合优化 → 信号输出

### 支持的外盘品种

| 品种 | 代码 | 交易所 |
|------|------|--------|
| 黄金 | GC=F | COMEX |
| 原油 | CL=F | NYMEX |
| 白银 | SI=F | COMEX |
| 铜 | HG=F | COMEX |
| 天然气 | NG=F | NYMEX |

## 技术架构

### 后端（Flask + Python 3.12）
- **框架**：Flask + Blueprint 模块化路由
- **数据获取**：AKShare → yfinance → GBM合成（三层降级）
- **数据处理**：pandas, numpy
- **预测/分析**：scikit-learn, statsmodels, scipy
- **API设计**：RESTful API，支持 CORS

### 前端
- **图表库**：Plotly.js（K线/折线/热力/面积图）
- **样式**：原生CSS3，深色金融主题，CSS变量（涨红 `#e84855` / 跌绿 `#00c875`）
- **交互**：原生JavaScript (ES6+)，Fetch API

## 快速开始

### 方式一：使用启动脚本（推荐，Windows）
```bash
# 双击运行，自动安装依赖并启动
start.bat
```

### 方式二：手动启动
```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动后端
python backend/app.py

# 3. 浏览器访问
# http://localhost:5000
```

## 项目结构

```
外盘商品走势分析与预测系统/
├── backend/
│   ├── app.py                  # Flask主应用（路由注册 + 商品数据API）
│   ├── cross_section_api.py    # 截面多空策略引擎
│   ├── stock_api.py            # A股市场数据 Blueprint
│   └── quant_api.py            # 量化研究全流程 Blueprint
├── frontend/
│   ├── static/
│   │   ├── style.css           # 全局样式（深色金融主题）
│   │   └── app.js              # 主页前端逻辑
│   └── templates/
│       ├── index.html          # 主页（外盘走势 + 概览 + 情绪）
│       ├── cross_section.html  # 截面多空策略界面
│       ├── stock.html          # A股市场信息界面
│       └── quant.html          # 量化研究向导界面
├── research/
│   ├── data_fetcher.py         # 多数据源获取工具
│   ├── cointegration_arbitrage.py  # 协整套利研究
│   ├── strategy_tqsdk.py       # 天勤量化兼容回测
│   └── generate_report.py      # PDF报告生成
├── 项目报告.md                  # 完整项目报告
├── 研究报告_截面多空策略与动量因子.md  # 量化策略学术研究报告
├── requirements.txt
├── start.bat
└── README.md
```

## API 接口一览

### 商品数据（主模块）
```
GET /api/commodities                          # 商品列表
GET /api/commodity/<key>/info                 # 最新行情
GET /api/commodity/<key>/data/<period>        # 历史K线
GET /api/commodity/<key>/analyze/<period>     # 综合分析（含预测）
GET /api/commodity/<key>/predict/<period>     # 价格预测
GET /api/commodity/<key>/volatility/<period>  # 历史波动率序列
GET /api/term-structure/<key>                 # 期限结构分析
GET /api/strategy/backtest/<key>/<period>     # 双均线回测
GET /api/market/overview                      # 全市场概览
GET /api/market/sentiment                     # 市场情绪评分
```

### A股市场（/api/stock）
```
GET /api/stock/market/overview    # 大盘指数
GET /api/stock/list               # 行情列表
GET /api/stock/sectors            # 行业板块
GET /api/stock/kline/<code>       # 个股K线
GET /api/stock/breadth            # 市场宽度
```

### 截面多空（/api/cross-section）
```
GET /api/cross-section/backtest   # 策略回测（支持参数：freq/long_q/short_q/cost）
GET /api/cross-section/portfolio  # 最新持仓
GET /api/cross-section/factors    # 因子截面得分
GET /api/cross-section/prices/<asset>  # 单品种价格
```

## 研究报告

- **[项目报告.md](./项目报告.md)**：系统整体设计与实现说明
- **[研究报告_截面多空策略与动量因子.md](./研究报告_截面多空策略与动量因子.md)**：  
  学术研究报告，涵盖：
  1. 截面多空策略七步构建法（因子计算→截面Z-score→IC加权→分位数建仓）
  2. 动量策略文献综述（Jegadeesh 1993 至 ML动量 2020）
  3. 动量奔溃成因分析与应对方案（波动率缩放、残差动量、52周高点等新因子）
  4. 完整参考文献（18篇核心文献）

## 注意事项

1. 预测结果仅供参考，不构成投资建议
2. 国内网络访问 Yahoo Finance 需代理；AKShare 部分接口有速率限制
3. 策略回测使用 GBM 合成数据，统计性质合理，真实部署时可替换数据源
4. 请使用现代浏览器（Chrome/Firefox/Edge）以获得最佳体验

## 许可证

MIT License


