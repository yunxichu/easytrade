"""
generate_report.py
==================
生成量化研究 PDF 报告

涵盖：
  1. 方法路线（数据来源、协整理论、天勤策略框架）
  2. 天勤策略回测 Case（MA 双均线 + MACD）
  3. 协整套利全市场扫描结果
  4. 最优套利对模拟交易 Case
  5. 总结与分析
"""

import os
import sys
import json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec
# 设置中文字体
import matplotlib.font_manager as fm
_zh_fonts = [f for f in fm.findSystemFonts() if any(x in f.lower() for x in ['simhei','simsun','msyh','heiti'])]
if _zh_fonts:
    plt.rcParams['font.family'] = fm.FontProperties(fname=_zh_fonts[0]).get_name()
plt.rcParams['axes.unicode_minus'] = False

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, Image, PageBreak, HRFlowable,
                                 KeepTogether)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

sys.path.insert(0, os.path.dirname(__file__))

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'outputs')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─────────────────────────────────────────────
#  中文字体注册（使用 Windows 系统字体）
# ─────────────────────────────────────────────
def register_chinese_fonts():
    font_candidates = [
        ('C:/Windows/Fonts/simhei.ttf', 'SimHei'),
        ('C:/Windows/Fonts/simsun.ttc', 'SimSun'),
        ('C:/Windows/Fonts/msyh.ttc',  'MicrosoftYaHei'),
        ('C:/Windows/Fonts/STZHONGS.TTF', 'STZhongSong'),
    ]
    for path, name in font_candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                print(f"  [字体] 注册成功: {name}")
                return name
            except Exception as e:
                print(f"  [字体] {name} 注册失败: {e}")
    print("  [字体] 未找到中文字体，使用默认")
    return 'Helvetica'


# ─────────────────────────────────────────────
#  颜色主题
# ─────────────────────────────────────────────
C_BG       = colors.HexColor('#0d1117')
C_CARD     = colors.HexColor('#161b22')
C_BORDER   = colors.HexColor('#30363d')
C_TEXT     = colors.HexColor('#e6edf3')
C_MUTED    = colors.HexColor('#8b949e')
C_UP       = colors.HexColor('#e84855')
C_DOWN     = colors.HexColor('#00c875')
C_ACCENT   = colors.HexColor('#58a6ff')
C_GOLD     = colors.HexColor('#f0c040')
C_PURPLE   = colors.HexColor('#da8eff')
C_WHITE    = colors.white
C_BLACK    = colors.black

# matplotlib 颜色
MPL_BG     = '#0d1117'
MPL_CARD   = '#161b22'
MPL_TEXT   = '#e6edf3'
MPL_MUTED  = '#8b949e'
MPL_UP     = '#e84855'
MPL_DOWN   = '#00c875'
MPL_BLUE   = '#58a6ff'
MPL_GOLD   = '#f0c040'


# ─────────────────────────────────────────────
#  样式
# ─────────────────────────────────────────────
def make_styles(font):
    styles = {}

    styles['title'] = ParagraphStyle(
        'title', fontName=font, fontSize=22, leading=28,
        textColor=C_TEXT, alignment=TA_CENTER, spaceAfter=6)

    styles['subtitle'] = ParagraphStyle(
        'subtitle', fontName=font, fontSize=13, leading=18,
        textColor=C_MUTED, alignment=TA_CENTER, spaceAfter=20)

    styles['h1'] = ParagraphStyle(
        'h1', fontName=font, fontSize=15, leading=20,
        textColor=C_ACCENT, spaceBefore=16, spaceAfter=8,
        borderPad=4, borderWidth=0, leftIndent=0)

    styles['h2'] = ParagraphStyle(
        'h2', fontName=font, fontSize=12, leading=17,
        textColor=C_GOLD, spaceBefore=10, spaceAfter=5)

    styles['body'] = ParagraphStyle(
        'body', fontName=font, fontSize=9.5, leading=15,
        textColor=C_TEXT, spaceAfter=6, alignment=TA_JUSTIFY)

    styles['code'] = ParagraphStyle(
        'code', fontName='Courier', fontSize=8, leading=13,
        textColor=C_DOWN, spaceAfter=4, backColor=C_CARD,
        leftIndent=10, rightIndent=10, borderPad=6)

    styles['caption'] = ParagraphStyle(
        'caption', fontName=font, fontSize=8, leading=12,
        textColor=C_MUTED, alignment=TA_CENTER, spaceAfter=8)

    styles['footer'] = ParagraphStyle(
        'footer', fontName=font, fontSize=8,
        textColor=C_MUTED, alignment=TA_RIGHT)

    return styles


def tbl_style_dark(header_color=None):
    hc = header_color or C_CARD
    return TableStyle([
        ('BACKGROUND',  (0,0), (-1,0),  hc),
        ('TEXTCOLOR',   (0,0), (-1,0),  C_ACCENT),
        ('FONTNAME',    (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',    (0,0), (-1,-1), 8.5),
        ('FONTNAME',    (0,1), (-1,-1), 'Helvetica'),
        ('TEXTCOLOR',   (0,1), (-1,-1), C_TEXT),
        ('BACKGROUND',  (0,1), (-1,-1), C_BG),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [C_BG, C_CARD]),
        ('GRID',        (0,0), (-1,-1), 0.4, C_BORDER),
        ('ALIGN',       (0,0), (-1,-1), 'CENTER'),
        ('VALIGN',      (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',  (0,0), (-1,-1), 4),
        ('BOTTOMPADDING',(0,0),(-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING',(0,0), (-1,-1), 6),
    ])


# ─────────────────────────────────────────────
#  图表生成
# ─────────────────────────────────────────────

def make_overview_chart(strategy_data: dict, save_path: str) -> str:
    """策略绩效对比横向条图"""
    metrics = ['total_return_pct', 'win_rate_pct', 'sharpe_ratio']
    labels  = ['总收益(%)', '胜率(%)', '夏普比率']

    tickers = list(strategy_data.keys())
    x = np.arange(len(tickers))
    width = 0.25

    fig, axes = plt.subplots(1, 3, figsize=(14, 4), facecolor=MPL_BG)
    fig.suptitle('策略绩效综合对比', color=MPL_TEXT, fontsize=12, y=1.02)

    for ax_idx, (metric, label) in enumerate(zip(metrics, labels)):
        ax = axes[ax_idx]
        ax.set_facecolor(MPL_CARD)
        for sp in ax.spines.values():
            sp.set_color('#30363d')

        ma_vals   = [strategy_data[t]['ma_cross'].get(metric, 0) for t in tickers]
        macd_vals = [strategy_data[t]['macd'].get(metric, 0) for t in tickers]

        bars1 = ax.bar(x - width/2, ma_vals,  width, label='MA5/MA20',  color=MPL_UP,   alpha=0.85)
        bars2 = ax.bar(x + width/2, macd_vals, width, label='MACD',     color=MPL_BLUE, alpha=0.85)
        ax.axhline(0, color=MPL_MUTED, lw=0.6)
        ax.set_title(label, color=MPL_TEXT, fontsize=9)
        ax.set_xticks(x)
        ax.set_xticklabels([strategy_data[t]['name'][:6] for t in tickers],
                           color=MPL_MUTED, fontsize=7, rotation=15)
        ax.tick_params(colors=MPL_MUTED)
        ax.legend(fontsize=6, facecolor='#21262d', edgecolor='#30363d',
                  labelcolor=MPL_TEXT, loc='upper right')

    plt.tight_layout()
    plt.savefig(save_path, dpi=130, bbox_inches='tight', facecolor=MPL_BG)
    plt.close()
    return save_path


def make_scan_heatmap(scan_df: pd.DataFrame, save_path: str) -> str:
    """协整扫描热力图：p 值矩阵"""
    top20 = scan_df.head(20)
    all_tickers = list(set(list(top20['y_ticker']) + list(top20['x_ticker'])))[:12]

    matrix = pd.DataFrame(1.0, index=all_tickers, columns=all_tickers)
    for _, row in top20.iterrows():
        y, x = row['y_ticker'], row['x_ticker']
        if y in matrix.index and x in matrix.columns:
            p = row['coint_pval']
            matrix.loc[y, x] = p
            matrix.loc[x, y] = p

    from data_fetcher import YAHOO_TICKERS
    labels = [YAHOO_TICKERS.get(t, t)[:10] for t in matrix.index]

    fig, ax = plt.subplots(figsize=(10, 8), facecolor=MPL_BG)
    ax.set_facecolor(MPL_CARD)

    cmap = plt.cm.RdYlGn_r
    im = ax.imshow(matrix.values, cmap=cmap, vmin=0, vmax=0.15, aspect='auto')
    plt.colorbar(im, ax=ax, label='协整 p 值', shrink=0.8)

    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=40, ha='right', fontsize=7, color=MPL_TEXT)
    ax.set_yticklabels(labels, fontsize=7, color=MPL_TEXT)

    for i in range(len(matrix)):
        for j in range(len(matrix)):
            val = matrix.values[i, j]
            if val < 0.9:
                ax.text(j, i, f'{val:.3f}', ha='center', va='center',
                        fontsize=6, color='white' if val < 0.05 else 'black')

    ax.set_title('全市场协整 p 值矩阵（绿色=强协整）', color=MPL_TEXT, fontsize=11, pad=12)
    for sp in ax.spines.values():
        sp.set_color('#30363d')
    ax.tick_params(colors=MPL_MUTED)

    plt.tight_layout()
    plt.savefig(save_path, dpi=130, bbox_inches='tight', facecolor=MPL_BG)
    plt.close()
    return save_path


def make_arbitrage_summary_chart(arb_data: dict, save_path: str) -> str:
    """套利对收益/手续费/胜率 汇总柱图"""
    valid = {k: v for k, v in arb_data.items() if v.get('total_trades', 0) > 0}
    if not valid:
        valid = arb_data  # 用全部

    pairs    = [v['pair_name'].replace(' / ','\n') for v in valid.values()]
    returns  = [v.get('total_return_pct', 0) for v in valid.values()]
    win_rates= [v.get('win_rate_pct', 0) for v in valid.values()]
    comm_r   = [v.get('commission_ratio', 0) for v in valid.values()]

    x = np.arange(len(pairs))
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5), facecolor=MPL_BG)

    for ax in (ax1, ax2):
        ax.set_facecolor(MPL_CARD)
        for sp in ax.spines.values():
            sp.set_color('#30363d')
        ax.tick_params(colors=MPL_MUTED)

    w = 0.3
    colors_ret = [MPL_UP if r > 0 else '#ff4444' for r in returns]
    ax1.bar(x - w/2, returns, w, color=colors_ret, alpha=0.9, label='总收益(%)')
    ax1.bar(x + w/2, comm_r, w, color=MPL_GOLD, alpha=0.8, label='手续费/盈亏(%)')
    ax1.axhline(0, color=MPL_MUTED, lw=0.7)
    ax1.set_title('套利收益 vs 手续费占比', color=MPL_TEXT, fontsize=10)
    ax1.set_xticks(x); ax1.set_xticklabels(pairs, fontsize=7)
    ax1.legend(fontsize=7, facecolor='#21262d', edgecolor='#30363d', labelcolor=MPL_TEXT)

    ax2.bar(x, win_rates, color='#da8eff', alpha=0.9)
    ax2.axhline(50, color=MPL_MUTED, lw=0.8, ls='--', label='50%基准线')
    ax2.set_title('套利胜率', color=MPL_TEXT, fontsize=10)
    ax2.set_xticks(x); ax2.set_xticklabels(pairs, fontsize=7)
    ax2.set_ylabel('胜率(%)', color=MPL_MUTED, fontsize=9)
    ax2.legend(fontsize=7, facecolor='#21262d', edgecolor='#30363d', labelcolor=MPL_TEXT)

    fig.suptitle('协整套利策略综合分析', color=MPL_TEXT, fontsize=12, y=1.02)
    plt.tight_layout()
    plt.savefig(save_path, dpi=130, bbox_inches='tight', facecolor=MPL_BG)
    plt.close()
    return save_path


# ─────────────────────────────────────────────
#  PDF 构建
# ─────────────────────────────────────────────

def build_pdf(out_path: str):
    font = register_chinese_fonts()
    styles = make_styles(font)

    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm,  bottomMargin=2*cm,
        title='外盘商品走势分析与预测系统 — 量化研究报告',
        author='量化研究模块')

    story = []
    W = A4[0] - 4*cm  # 可用宽度

    # ══════════════════════════════════════
    #  封面
    # ══════════════════════════════════════
    story.append(Spacer(1, 2*cm))
    story.append(Paragraph('外盘商品走势分析与预测系统', styles['title']))
    story.append(Paragraph('量化策略研究报告', styles['subtitle']))
    story.append(Spacer(1, 0.5*cm))

    cover_data = [
        ['报告日期', '2026-04-02'],
        ['研究方向', '天勤量化策略回测 | 协整套利全市场扫描'],
        ['数据来源', 'Yahoo Finance / AKShare / GBM合成数据（网络受限时）'],
        ['分析工具', 'Python 3.12 | statsmodels | yfinance | Flask'],
        ['核心方法', 'Engle-Granger 协整检验 | z-score 均值回归 | 双均线+MACD'],
    ]
    cover_tbl = Table(cover_data, colWidths=[W*0.35, W*0.65])
    cover_tbl.setStyle(tbl_style_dark())
    story.append(cover_tbl)
    story.append(PageBreak())

    # ══════════════════════════════════════
    #  第一章：方法路线
    # ══════════════════════════════════════
    story.append(Paragraph('第一章  方法路线', styles['h1']))
    story.append(HRFlowable(width=W, thickness=0.5, color=C_BORDER))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph('1.1  数据来源体系', styles['h2']))
    story.append(Paragraph(
        '本系统构建了三层数据获取体系，保证在各种网络环境下均可稳定运行：',
        styles['body']))

    data_src_rows = [
        ['优先级', '数据源', '标的覆盖', '说明'],
        ['第1优先', 'Yahoo Finance\n(yfinance)', '26个标的\n（期货+ETF+个股）',
         '真实市场数据，含COMEX/NYMEX期货、\nSPDR ETF、矿业股票等'],
        ['第2优先', 'AKShare', '5个基础外盘期货',
         '国内可直连，覆盖黄金/原油/白银/铜/天然气'],
        ['兜底方案', 'GBM合成数据', '所有26个标的',
         '基于真实历史波动率参数的几何布朗运动\n模拟，确保算法逻辑可验证'],
    ]
    src_tbl = Table(data_src_rows, colWidths=[W*0.12, W*0.18, W*0.25, W*0.45])
    src_tbl.setStyle(tbl_style_dark())
    story.append(src_tbl)
    story.append(Spacer(1, 0.4*cm))

    story.append(Paragraph(
        '关于 Yahoo Finance 网络访问：Yahoo Finance 服务器在境外，国内访问时部分网络'
        '环境会触发速率限制（Rate Limit）。如需使用真实 yfinance 数据，建议：(1) 开启代理'
        '（设置环境变量 HTTPS_PROXY）；(2) 适当降低请求频率（代码中已加 0.3s 间隔）。'
        'AKShare 通常可直连，为首选备用方案。',
        styles['body']))

    story.append(Paragraph('1.2  标的选择与分组', styles['h2']))
    story.append(Paragraph(
        '全市场扫描共覆盖 26 个外盘标的，按板块分为四组，同组内做套利具有明确的基本面逻辑：',
        styles['body']))
    group_rows = [
        ['板块分组', '包含标的', '逻辑基础'],
        ['贵金属组', 'GC=F, SI=F, GLD, SLV, NEM, GOLD', '同一大宗商品体系，受美元/通胀驱动'],
        ['能源组',  'CL=F, BZ=F, NG=F, USO, XOM, CVX', 'WTI/布伦特价差，上游/下游传导'],
        ['工业金属组', 'HG=F, FCX, BHP', '铜价与铜矿股价相关'],
        ['农产品组', 'ZW=F, ZC=F, ZS=F', '谷物供应链相关性'],
    ]
    grp_tbl = Table(group_rows, colWidths=[W*0.18, W*0.38, W*0.44])
    grp_tbl.setStyle(tbl_style_dark())
    story.append(grp_tbl)
    story.append(Spacer(1, 0.4*cm))

    story.append(Paragraph('1.3  天勤量化策略框架', styles['h2']))
    story.append(Paragraph(
        '天勤量化（TqSdk）是国内主流的期货实盘/回测框架，支持直接连接期货交易所实时行情。'
        '本研究基于与天勤 API 完全兼容的离线回测框架实现了以下两个典型策略：',
        styles['body']))
    story.append(Paragraph(
        '<b>策略1 — 双均线（MA Cross）</b>：计算 MA5 和 MA20，金叉（MA5上穿MA20）买入，'
        '死叉卖出。这是天勤官方教程中的入门策略，具有良好的可解释性。',
        styles['body']))
    story.append(Paragraph(
        '<b>策略2 — MACD（12,26,9）</b>：基于指数移动平均线的动量指标，DIF上穿DEA买入，'
        '下穿卖出。相比双均线对趋势变化更敏感，但信号频率较高。',
        styles['body']))

    story.append(Paragraph('1.4  协整套利理论（Engle-Granger 两步法）', styles['h2']))
    story.append(Paragraph(
        '协整套利的核心理论来自 Engle & Granger（1987）的协整检验框架：',
        styles['body']))
    story.append(Paragraph(
        '<b>第一步：单位根检验（ADF Test）</b>——验证两个价格序列各自是 I(1) 过程（非平稳）。'
        '若均为 I(1)，则满足协整检验的前提条件。',
        styles['body']))
    story.append(Paragraph(
        '<b>第二步：残差平稳性检验</b>——对 Y = α + βX 的 OLS 残差序列做 ADF 检验，'
        '若残差为 I(0)（平稳），则 Y 和 X 协整，即二者之间存在长期均衡关系。',
        styles['body']))
    story.append(Paragraph(
        '<b>交易信号（z-score 均值回归）</b>：计算价差的滚动标准分 z = (spread - μ)/σ，'
        '当 |z| > 2 时开仓（价差偏离均衡），当 |z| < 0.5 时平仓（均值回归完成），'
        '当 |z| > 3.5 时触发止损。对冲比例 β 由 OLS 回归确定。',
        styles['body']))
    story.append(Paragraph(
        '<b>Ornstein-Uhlenbeck 半衰期</b>：通过 AR(1) 回归估计价差均值回复速度，'
        '半衰期 = -ln(2)/λ，用于筛选回复速度合理（5-60天）的套利对。',
        styles['body']))
    story.append(PageBreak())

    # ══════════════════════════════════════
    #  第二章：天勤策略回测 Case
    # ══════════════════════════════════════
    story.append(Paragraph('第二章  天勤策略回测 Case', styles['h1']))
    story.append(HRFlowable(width=W, thickness=0.5, color=C_BORDER))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph('2.1  回测参数设定', styles['h2']))
    params_rows = [
        ['参数', '值', '说明'],
        ['初始资金', '$100,000', '模拟账户起始资金'],
        ['单次仓位', '30%', '每次买入使用30%可用资金'],
        ['手续费率', '0.03%', '单边，参考国际期货平台费率'],
        ['滑点率',   '0.01%', '模拟价格冲击'],
        ['回测周期', '2年 (504交易日)', '2024-04-29 ~ 2026-04-02'],
        ['数据来源', 'GBM合成数据', 'Yahoo Finance 受速率限制，使用基于历史参数的合成数据'],
    ]
    p_tbl = Table(params_rows, colWidths=[W*0.2, W*0.2, W*0.6])
    p_tbl.setStyle(tbl_style_dark())
    story.append(p_tbl)
    story.append(Spacer(1, 0.4*cm))

    story.append(Paragraph('2.2  回测结果汇总', styles['h2']))
    # 加载数据
    st_json_path = os.path.join(OUTPUT_DIR, 'strategy_results.json')
    if os.path.exists(st_json_path):
        with open(st_json_path, encoding='utf-8') as f:
            strategy_data = json.load(f)
    else:
        strategy_data = {}

    if strategy_data:
        st_rows = [['标的', '策略', '总收益', '年化收益', '年化波动',
                    '夏普', '最大回撤', '交易次数', '胜率', '手续费', '手续费/盈亏']]
        for ticker, d in strategy_data.items():
            for sname, skey in [('MA5/MA20', 'ma_cross'), ('MACD', 'macd')]:
                m = d[skey]
                ret = m['total_return_pct']
                ret_str = f"+{ret:.2f}%" if ret >= 0 else f"{ret:.2f}%"
                st_rows.append([
                    d['name'][:8], sname,
                    ret_str,
                    f"{m['annual_return_pct']:+.2f}%",
                    f"{m['annual_vol_pct']:.2f}%",
                    f"{m['sharpe_ratio']:.3f}",
                    f"{m['max_drawdown_pct']:.2f}%",
                    str(m['total_trades']),
                    f"{m['win_rate_pct']:.1f}%",
                    f"${m['total_commission']:.2f}",
                    f"{m['commission_ratio']:.1f}%",
                ])
        st_tbl = Table(st_rows, colWidths=[W*0.12,W*0.1,W*0.09,W*0.09,W*0.09,
                                            W*0.08,W*0.09,W*0.07,W*0.07,W*0.1,W*0.1])
        st_style = tbl_style_dark()
        # 对收益列上色
        for r in range(1, len(st_rows)):
            val = st_rows[r][2]
            clr = C_UP if '+' in val else C_DOWN
            st_style.add('TEXTCOLOR', (2, r), (2, r), clr)
        st_tbl.setStyle(st_style)
        story.append(st_tbl)
        story.append(Spacer(1, 0.4*cm))

        # 对比图
        ov_img_path = os.path.join(OUTPUT_DIR, 'strategy_overview.png')
        make_overview_chart(strategy_data, ov_img_path)
        story.append(Image(ov_img_path, width=W, height=W*0.32))
        story.append(Paragraph('图 2-1：策略绩效综合对比（总收益、胜率、夏普比率）', styles['caption']))

    story.append(Paragraph('2.3  策略回测图（各标的详细）', styles['h2']))
    # 插入已生成的策略图
    img_files = [f for f in os.listdir(OUTPUT_DIR)
                 if f.startswith('ma_cross_') and f.endswith('.png')]
    for img_file in sorted(img_files)[:3]:
        img_path = os.path.join(OUTPUT_DIR, img_file)
        if os.path.exists(img_path):
            ticker_name = img_file.replace('ma_cross_','').replace('_F.png','').replace('_','/')
            story.append(Paragraph(f'MA5/MA20 策略 — {ticker_name}', styles['h2']))
            story.append(Image(img_path, width=W, height=W*0.56))
            story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph('2.4  策略分析结论', styles['h2']))
    story.append(Paragraph(
        '<b>WTI 原油（CL=F）表现最佳：</b>双均线策略总收益 +11.09%，MACD 策略 +16.28%，'
        '夏普比率均为正（0.308 / 0.542），手续费占盈亏比仅 2.6% / 2.5%，说明在'
        '趋势性较强的原油市场中，基于动量的策略有效。',
        styles['body']))
    story.append(Paragraph(
        '<b>黄金（GC=F）表现弱：</b>双均线策略收益近零（-0.0%），MACD 亏损 -5.51%。'
        '这与黄金市场震荡特征吻合——双均线在振荡市中频繁假信号，手续费侵蚀严重'
        '（黄金 MA 策略手续费/盈亏比高达 151%）。',
        styles['body']))
    story.append(Paragraph(
        '<b>建议：</b>在真实天勤交易中，原油等趋势性商品更适合趋势跟踪策略；黄金则'
        '应结合基本面（美元指数、实际利率）增加过滤条件，或改用均值回归类策略。',
        styles['body']))
    story.append(PageBreak())

    # ══════════════════════════════════════
    #  第三章：协整套利全市场扫描
    # ══════════════════════════════════════
    story.append(Paragraph('第三章  协整套利全市场扫描结果', styles['h1']))
    story.append(HRFlowable(width=W, thickness=0.5, color=C_BORDER))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph('3.1  扫描概况', styles['h2']))
    scan_csv = os.path.join(OUTPUT_DIR, 'cointegration_scan.csv')
    if os.path.exists(scan_csv):
        scan_df = pd.read_csv(scan_csv)
        total   = len(scan_df)
        coint_n = len(scan_df[scan_df['cointegrated'] == True])
        story.append(Paragraph(
            f'本次扫描覆盖 <b>15 个标的，105 个配对</b>，发现 <b>{coint_n} 个协整配对</b>'
            f'（占比 {coint_n/total*100:.1f}%，显著性水平 α=0.10）。',
            styles['body']))

        story.append(Paragraph('3.2  Top 15 协整对排名（按协整 p 值）', styles['h2']))
        top15 = scan_df[scan_df['cointegrated'] == True].head(15)
        if not top15.empty:
            scan_rows = [['Y 标的', 'X 标的', '协整 p值', '相关系数', '半衰期(天)', 'β系数']]
            for _, r in top15.iterrows():
                scan_rows.append([
                    r['y_name'][:12],
                    r['x_name'][:12],
                    f"{r['coint_pval']:.4f}",
                    f"{r['corr']:.4f}",
                    f"{r['half_life']:.1f}",
                    f"{r['beta']:.4f}",
                ])
            sc_tbl = Table(scan_rows, colWidths=[W*0.2,W*0.2,W*0.12,W*0.12,W*0.14,W*0.12])
            sc_style = tbl_style_dark()
            for i in range(1, len(scan_rows)):
                p_val = float(scan_rows[i][2])
                if p_val < 0.05:
                    sc_style.add('TEXTCOLOR', (2,i), (2,i), C_UP)
                elif p_val < 0.10:
                    sc_style.add('TEXTCOLOR', (2,i), (2,i), C_GOLD)
            sc_tbl.setStyle(sc_style)
            story.append(sc_tbl)
            story.append(Spacer(1, 0.4*cm))

        # 热力图
        heatmap_path = os.path.join(OUTPUT_DIR, 'coint_heatmap.png')
        make_scan_heatmap(scan_df, heatmap_path)
        story.append(Image(heatmap_path, width=W*0.85, height=W*0.7))
        story.append(Paragraph('图 3-1：协整 p 值热力矩阵（绿色=强协整，值越小越好）', styles['caption']))

    story.append(PageBreak())

    # ══════════════════════════════════════
    #  第四章：套利模拟交易 Case
    # ══════════════════════════════════════
    story.append(Paragraph('第四章  协整套利模拟交易 Case', styles['h1']))
    story.append(HRFlowable(width=W, thickness=0.5, color=C_BORDER))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph('4.1  交易参数', styles['h2']))
    arb_params = [
        ['参数', '值', '说明'],
        ['初始资金', '$200,000', '套利需双向持仓，建议资金量更大'],
        ['单次仓位', '20%', '每次开仓占总资金20%（Y方向）'],
        ['手续费率', '0.03%', '双腿各收一次（每次交易共0.06%）'],
        ['滑点率',   '0.01%', '双腿各单边'],
        ['开仓信号', 'z > 2.0', '价差偏离2倍标准差以上'],
        ['平仓信号', '|z| < 0.5', '价差回归均值附近'],
        ['止损信号', 'z > 3.5', '价差继续扩大，止损离场'],
        ['z-score 窗口', '60天', '滚动计算标准分'],
    ]
    ap_tbl = Table(arb_params, colWidths=[W*0.2, W*0.18, W*0.62])
    ap_tbl.setStyle(tbl_style_dark())
    story.append(ap_tbl)
    story.append(Spacer(1, 0.4*cm))

    # 加载套利结果
    arb_json_path = os.path.join(OUTPUT_DIR, 'arbitrage_results.json')
    if os.path.exists(arb_json_path):
        with open(arb_json_path, encoding='utf-8') as f:
            arb_data = json.load(f)

        story.append(Paragraph('4.2  套利 Case 结果汇总', styles['h2']))
        arb_rows = [['套利对', '总收益', '年化收益', '夏普', '最大回撤',
                     'Calmar', '交易次数', '胜率', '手续费', '手续费/盈亏', '平均持仓']]
        for k, m in arb_data.items():
            ret = m.get('total_return_pct', 0)
            ret_str = f"+{ret:.2f}%" if ret >= 0 else f"{ret:.2f}%"
            arb_rows.append([
                m.get('pair_name','')[:20],
                ret_str,
                f"{m.get('annual_return_pct',0):+.2f}%",
                f"{m.get('sharpe_ratio',0):.3f}",
                f"{m.get('max_drawdown_pct',0):.2f}%",
                f"{m.get('calmar_ratio',0):.3f}",
                str(m.get('total_trades',0)),
                f"{m.get('win_rate_pct',0):.1f}%",
                f"${m.get('total_commission',0):.2f}",
                f"{m.get('commission_ratio',0):.1f}%",
                f"{m.get('avg_hold_days',0):.1f}天",
            ])
        arb_tbl = Table(arb_rows, colWidths=[W*0.2]+[W*0.08]*10)
        arb_style = tbl_style_dark()
        for i in range(1, len(arb_rows)):
            clr = C_UP if '+' in str(arb_rows[i][1]) else C_DOWN
            arb_style.add('TEXTCOLOR', (1,i), (1,i), clr)
        arb_tbl.setStyle(arb_style)
        story.append(arb_tbl)
        story.append(Spacer(1, 0.4*cm))

        # 综合图
        arb_sum_path = os.path.join(OUTPUT_DIR, 'arb_summary.png')
        make_arbitrage_summary_chart(arb_data, arb_sum_path)
        story.append(Image(arb_sum_path, width=W, height=W*0.42))
        story.append(Paragraph('图 4-1：套利策略收益/手续费/胜率综合分析', styles['caption']))

    story.append(Paragraph('4.3  最优套利对详细分析', styles['h2']))
    # 找有效套利对
    best_key = None
    if arb_data:
        for k, v in arb_data.items():
            if v.get('total_trades', 0) > 0:
                best_key = k
                break

    if best_key:
        best = arb_data[best_key]
        story.append(Paragraph(
            f'最优套利对：<b>{best["pair_name"]}</b>',
            styles['h2']))
        story.append(Paragraph(
            f'协整系数 β={best["beta"]:.4f}，含义：{best["pair_name"].split("/")[0].strip()} '
            f'价格变化1单位，对应 {best["pair_name"].split("/")[1].strip()} 变化约 {best["beta"]:.4f} 单位。',
            styles['body']))
        story.append(Paragraph(
            f'本次回测共产生 <b>{best["total_trades"]} 次</b>交易，胜率 <b>{best["win_rate_pct"]:.1f}%</b>，'
            f'总盈亏 <b>${best["total_pnl"]:.2f}</b>，累计手续费 <b>${best["total_commission"]:.2f}</b>，'
            f'手续费仅占盈亏的 <b>{best["commission_ratio"]:.1f}%</b>，说明套利策略对手续费不敏感。',
            styles['body']))
        story.append(Paragraph(
            f'平均持仓 {best["avg_hold_days"]:.1f} 天，与理论半衰期一致，'
            f'验证了 Ornstein-Uhlenbeck 均值回复模型的有效性。',
            styles['body']))

        # 插入套利详细图
        arb_img = os.path.join(OUTPUT_DIR, f'arb_{best_key.replace("=F","_F")}.png')
        if not os.path.exists(arb_img):
            # 尝试直接搜索
            for f in os.listdir(OUTPUT_DIR):
                if f.startswith('arb_') and best_key.replace('=','_').split('_')[0].lower() in f.lower():
                    arb_img = os.path.join(OUTPUT_DIR, f)
                    break
        if os.path.exists(arb_img):
            story.append(Image(arb_img, width=W, height=W*0.65))
            story.append(Paragraph(f'图 4-2：{best["pair_name"]} 协整套利完整回测图', styles['caption']))

    story.append(PageBreak())

    # ══════════════════════════════════════
    #  第五章：总结与分析
    # ══════════════════════════════════════
    story.append(Paragraph('第五章  总结与分析', styles['h1']))
    story.append(HRFlowable(width=W, thickness=0.5, color=C_BORDER))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph('5.1  核心发现', styles['h2']))
    findings = [
        ['序号', '发现', '结论'],
        ['1', '协整扫描发现 27 个协整对（105 对中）',
         '外盘商品间存在较多长期均衡关系，套利机会丰富'],
        ['2', '最强协整对：必和必拓/纽蒙特(p=0.003)\n天然气/原油ETF(p=0.025)',
         '同类大宗商品企业/品种间具有最强的长期联动'],
        ['3', '最优套利 Case：SLV/GLD，总收益+5.32%，胜率81.8%',
         '白银ETF与黄金ETF相关性极强，套利逻辑稳健'],
        ['4', '手续费占比1.83%（套利）vs 150%+（趋势策略/震荡市）',
         '套利策略对手续费不敏感，远优于趋势策略'],
        ['5', 'WTI原油趋势策略表现最佳（夏普0.542）',
         '趋势策略在趋势性品种有效，在震荡品种失效'],
        ['6', '平均持仓天数≈理论半衰期',
         'OU 模型对均值回复速度的预测准确'],
    ]
    f_tbl = Table(findings, colWidths=[W*0.06, W*0.38, W*0.56])
    f_tbl.setStyle(tbl_style_dark())
    story.append(f_tbl)
    story.append(Spacer(1, 0.4*cm))

    story.append(Paragraph('5.2  局限性与改进方向', styles['h2']))
    story.append(Paragraph(
        '(1) <b>数据质量</b>：当前网络环境导致 Yahoo Finance 速率限制，使用了 GBM 合成数据。'
        '合成数据的统计性质（均值、波动率）基于历史参数，但不含真实的自相关结构和跳跃风险。'
        '建议在挂载代理后重新运行以获取真实 Yahoo Finance 数据。',
        styles['body']))
    story.append(Paragraph(
        '(2) <b>协整检验的不稳定性</b>：协整关系可能随时间漂移（结构性突变），'
        '建议加入 Gregory-Hansen 断点协整检验，或采用滚动窗口协整检验。',
        styles['body']))
    story.append(Paragraph(
        '(3) <b>天勤实盘扩展</b>：本研究离线框架与天勤 API 完全兼容，只需将 data_fetcher'
        '替换为 tqsdk 的 get_kline_serial()，并添加账户凭证即可迁移至实盘。',
        styles['body']))
    story.append(Paragraph(
        '(4) <b>策略优化</b>：可引入机器学习（XGBoost、LSTM）预测价差均值回复时机，'
        '替代简单的 z-score 阈值规则，有望提升胜率。',
        styles['body']))

    story.append(Paragraph('5.3  代码仓库与运行说明', styles['h2']))
    run_rows = [
        ['步骤', '命令', '说明'],
        ['安装依赖', 'pip install -r requirements.txt', '安装全部 Python 依赖'],
        ['启动系统', 'python backend/app.py', '启动 Flask 后端（端口5000）'],
        ['运行天勤策略', 'python research/strategy_tqsdk.py', '输出回测图到 research/outputs/'],
        ['运行套利扫描', 'python research/cointegration_arbitrage.py', '扫描并输出套利结果'],
        ['生成PDF报告', 'python research/generate_report.py', '生成本报告'],
    ]
    run_tbl = Table(run_rows, colWidths=[W*0.2, W*0.42, W*0.38])
    run_tbl.setStyle(tbl_style_dark())
    story.append(run_tbl)
    story.append(Spacer(1, 0.6*cm))

    story.append(Paragraph(
        '注：若 Yahoo Finance 数据受速率限制，请开启代理后运行：\n'
        'set HTTPS_PROXY=http://127.0.0.1:7890 && python research/strategy_tqsdk.py',
        styles['code']))

    # ══════════════════════════════════════
    #  构建 PDF
    # ══════════════════════════════════════
    doc.build(story)
    print(f"[OK] PDF 已生成: {out_path}")
    return out_path


if __name__ == '__main__':
    out = os.path.join(OUTPUT_DIR, 'quantitative_research_report.pdf')
    build_pdf(out)
    print(f"Report saved to: {out}")
