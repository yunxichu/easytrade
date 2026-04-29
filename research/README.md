# research/ — 量化策略研究实验目录

本目录包含完整的量化研究实验代码，独立于主应用运行。

## 目录结构

```
research/
├── data_fetcher.py          # 数据获取（Yahoo Finance / AKShare / GBM合成数据）
├── strategy_tqsdk.py        # 天勤策略回测（双均线 MA5/MA20 + MACD）
├── cointegration_arbitrage.py  # 协整套利全市场扫描 + 模拟交易
├── option_iv_rv_greeks.py   # 期货期权1分钟数据：IV/RV、希腊字母、价格归因
├── prepare_quantconnect_es_option_data.py  # 下载并转换ES期货期权分钟样本
├── prepare_historical_percentiles.py  # 准备ES=F与VIX历史分位代理
├── generate_option_homework_report.py  # 生成第八周作业DOCX/PDF/ZIP
├── generate_report.py       # 生成 PDF 研究报告
├── test_data.py             # 数据源快速测试
└── outputs/                 # 自动生成的结果输出
    ├── strategy_results.json      # 策略回测结果
    ├── arbitrage_results.json     # 套利交易结果
    ├── cointegration_scan.csv     # 全市场协整扫描结果（105对）
    ├── ma_cross_*.png             # 双均线策略回测图
    ├── macd_*.png                 # MACD 策略回测图
    ├── arb_*.png                  # 套利交易详细图
    ├── coint_heatmap.png          # 协整热力矩阵图
    ├── strategy_overview.png      # 策略综合对比图
    └── quantitative_research_report.pdf  # 完整 PDF 报告
```

## 快速运行

```bash
# 1. 安装依赖（首次）
pip install -r ../requirements.txt
pip install reportlab

# 2. 测试数据连接
python test_data.py

# 3. 运行天勤策略回测
python strategy_tqsdk.py

# 4. 运行协整套利扫描
python cointegration_arbitrage.py

# 5. 生成 PDF 报告
python generate_report.py

# 6. 运行期货期权1分钟数据分析与第八周作业包生成
python prepare_quantconnect_es_option_data.py
python option_iv_rv_greeks.py --input ../data/processed/quantconnect_es_future_option_minute.csv --output-dir outputs/es_options --rv-window 60 --percentile-window 390 --minutes-per-year 347760 --rate 0.015
python prepare_historical_percentiles.py
python generate_option_homework_report.py
```

## 数据来源说明

| 优先级 | 来源 | 说明 |
|--------|------|------|
| 第1 | Yahoo Finance (yfinance) | 真实市场数据，含期货/ETF/股票 |
| 第2 | AKShare | 国内可直连，覆盖5个基础外盘期货 |
| 兜底 | GBM 合成数据 | 网络受限时自动启用，统计参数基于历史 |

> **关于 Yahoo Finance 访问**：国内网络可能触发速率限制。
> 若需真实数据，请开启代理后运行：
> ```
> set HTTPS_PROXY=http://127.0.0.1:7890
> python strategy_tqsdk.py
> ```

## 天勤（TqSdk）实盘对接

本框架与天勤 API 完全兼容，迁移至实盘只需：

1. `pip install tqsdk`
2. 在 [天勤官网](https://www.shinnytech.com/) 注册账户
3. 替换 `strategy_tqsdk.py` 末尾的注释代码块，填入账户凭证

## 协整套利理论

基于 **Engle-Granger 两步协整检验**：
1. ADF 单位根检验（确认各自 I(1)）
2. OLS 残差 ADF 检验（确认协整）
3. z-score 均值回归交易信号
4. Ornstein-Uhlenbeck 半衰期估计

### 核心发现
- 全市场 105 对中发现 **27 个协整对**（α=0.10）
- 最优套利对：**SLV / GLD**（白银ETF vs 黄金ETF）
  - 总收益：+5.32%，胜率：81.8%，手续费占比：1.83%
  - 平均持仓：12.8 天

详见 `outputs/quantitative_research_report.pdf`。
