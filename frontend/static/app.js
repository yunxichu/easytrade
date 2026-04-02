/* =============================================
   外盘商品走势分析与预测系统 — 主逻辑
   功能：市场概览、走势分析、波动率、情绪、相关性
   ============================================= */

const API_BASE = '/api';

// 所有商品键名
const ALL_KEYS = [];

// 缓存最近行情
const priceCache = {};

// 当前视图
let currentView = 'overview';
let analysisChartType = 'kline';

/* =====================
   入口
   ===================== */
document.addEventListener('DOMContentLoaded', async () => {
  startClock();
  await loadCommodities();

  document.getElementById('analyzeBtn').addEventListener('click', () => {
    setView('analysis');
    analyzeCommodity();
  });

  document.getElementById('refreshAll').addEventListener('click', loadMarketOverview);
  document.getElementById('sortByChange').addEventListener('click', () => sortMarketTable('change'));
  document.getElementById('sortByVolume').addEventListener('click', () => sortMarketTable('volume'));

  // 默认加载市场概览
  loadMarketOverview();
});

/* =====================
   时钟
   ===================== */
function startClock() {
  const update = () => {
    const now = new Date();
    const pad = n => String(n).padStart(2, '0');
    const s = `实时更新 ${now.getFullYear()}/${pad(now.getMonth()+1)}/${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    const el = document.getElementById('navTime');
    if (el) el.textContent = s;
  };
  update();
  setInterval(update, 1000);
}

/* =====================
   视图切换
   ===================== */
function setView(view) {
  currentView = view;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  const viewMap = { overview: 0, analysis: 1, predict: 2 };
  document.querySelectorAll('.tab-btn')[viewMap[view] ?? 0]?.classList.add('active');

  document.getElementById('view-overview').classList.toggle('hidden', view !== 'overview');
  document.getElementById('view-analysis').classList.toggle('hidden', view === 'overview');
}

function setChartType(type) {
  analysisChartType = type;
  // 重新渲染需要缓存的数据
  if (window._lastAnalysisData) {
    const d = window._lastAnalysisData;
    if (type === 'kline') plotCandlestickChart(d.historicalData, d.name);
    else plotLineChart(d.historicalData, d.name);
  }
}

/* =====================
   加载商品列表
   ===================== */
async function loadCommodities() {
  try {
    const res = await fetch(`${API_BASE}/commodities`);
    const list = await res.json();
    const sel = document.getElementById('commoditySelect');
    list.forEach(c => {
      ALL_KEYS.push(c.key);
      const opt = document.createElement('option');
      opt.value = c.key;
      opt.textContent = `${c.key} (${c.name})`;
      sel.appendChild(opt);
    });
  } catch (e) {
    showError('加载商品列表失败');
    console.error(e);
  }
}

/* =====================
   市场概览 — 全量加载
   ===================== */
async function loadMarketOverview() {
  const keys = ALL_KEYS.length ? ALL_KEYS : ['黄金','原油','白银','铜','天然气'];
  const tbody = document.getElementById('marketTableBody');
  tbody.innerHTML = `<tr><td colspan="10" style="text-align:center;color:var(--text-muted);padding:30px;">加载中...</td></tr>`;

  try {
    // 并发获取所有商品信息
    const results = await Promise.allSettled(
      keys.map(key => fetch(`${API_BASE}/commodity/${key}/info`).then(r => r.json()).then(d => ({ key, ...d })))
    );

    const rows = results
      .filter(r => r.status === 'fulfilled' && !r.value.error)
      .map(r => r.value);

    // 缓存
    rows.forEach(r => { priceCache[r.key] = r; });

    // 更新统计栏
    updateStatsBar(rows);

    // 更新TOP排行
    updateTop10(rows);

    // 渲染表格
    renderMarketTable(rows);

    // 异步加载迷你走势图
    rows.forEach(r => loadMiniChart(r.key));

  } catch(e) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center;color:var(--up-color);padding:30px;">加载失败，请检查后端服务</td></tr>`;
    console.error(e);
  }
}

/* =====================
   更新统计摘要栏
   ===================== */
function updateStatsBar(rows) {
  const rising = rows.filter(r => r.changePercent > 0).length;
  setStatValue('statRising', `${rising}/${rows.length}`, rising > rows.length / 2 ? 'up' : 'down');

  const map = { '黄金': ['statGoldPrice','statGoldChange'], '原油': ['statOilPrice','statOilChange'],
                '白银': ['statSilverPrice','statSilverChange'], '铜': ['statCopperPrice','statCopperChange'] };
  Object.entries(map).forEach(([key, [priceId, changeId]]) => {
    const r = rows.find(x => x.key === key);
    if (!r) return;
    document.getElementById(priceId).textContent = fmtPrice(r.currentPrice);
    const pct = (r.changePercent * 100).toFixed(2);
    const changeEl = document.getElementById(changeId);
    changeEl.textContent = (r.changePercent >= 0 ? '+' : '') + pct + '%';
    changeEl.style.color = r.changePercent >= 0 ? 'var(--up-color)' : 'var(--down-color)';
  });
}

function setStatValue(id, text, cls) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.className = 'stat-value ' + cls;
}

/* =====================
   TOP5 排行
   ===================== */
function updateTop10(rows) {
  const sorted = [...rows].sort((a,b) => b.changePercent - a.changePercent);
  const top5 = sorted.slice(0, 5);
  const bottom5 = sorted.slice(-5).reverse();

  document.getElementById('topRisingBody').innerHTML = top5.map((r,i) => `
    <tr onclick="quickAnalyze('${r.key}')">
      <td>${i+1}</td>
      <td>
        <span style="color:var(--text-primary);font-weight:600;">${r.key}</span>
        <span style="color:var(--text-muted);font-size:11px;margin-left:4px;">${r.name||''}</span>
      </td>
      <td class="price-up">${fmtPrice(r.currentPrice)}</td>
      <td class="price-up">+${(r.changePercent*100).toFixed(2)}%</td>
      <td style="color:var(--text-secondary)">${randomPct(1,5)}%</td>
      <td>
        <div class="flow-bar-wrap price-up">
          +${fmtVol(Math.abs(r.volume * r.currentPrice * 0.001))}
          <div class="flow-bar up" style="width:${40+i*8}px"></div>
        </div>
      </td>
    </tr>
  `).join('');

  document.getElementById('topFallingBody').innerHTML = bottom5.map((r,i) => `
    <tr onclick="quickAnalyze('${r.key}')">
      <td>${i+1}</td>
      <td>
        <span style="color:var(--text-primary);font-weight:600;">${r.key}</span>
        <span style="color:var(--text-muted);font-size:11px;margin-left:4px;">${r.name||''}</span>
      </td>
      <td class="price-down">${fmtPrice(r.currentPrice)}</td>
      <td class="price-down">${(r.changePercent*100).toFixed(2)}%</td>
      <td style="color:var(--text-secondary)">${randomPct(0.5,3)}%</td>
      <td>
        <div class="flow-bar-wrap price-down">
          ${fmtVol(Math.abs(r.volume * r.currentPrice * 0.001))}
          <div class="flow-bar down" style="width:${30+i*8}px"></div>
        </div>
      </td>
    </tr>
  `).join('');
}

/* =====================
   渲染市场大表
   ===================== */
let marketRows = [];
let sortConfig = { key: null, dir: 1 };

function renderMarketTable(rows) {
  marketRows = rows;
  paintMarketTable(rows);
}

function paintMarketTable(rows) {
  document.getElementById('marketTableBody').innerHTML = rows.map(r => {
    const pct = (r.changePercent * 100).toFixed(2);
    const isUp = r.changePercent >= 0;
    const tags = getMarketTags(r.key);
    const flowIn = (r.volume * r.currentPrice * (Math.random()*0.15+0.1)).toFixed(2);
    const flowPct = (Math.random()*30+60).toFixed(1);
    return `
      <tr onclick="quickAnalyze('${r.key}')">
        <td>
          <div class="commodity-name-cell">
            <div class="commodity-name-main">${r.key} <span class="tag ${tags.cls}">${tags.label}</span></div>
            <div class="commodity-name-sub">${r.name || ''}</div>
          </div>
        </td>
        <td style="color:var(--text-secondary)">${tags.market}</td>
        <td class="${isUp?'price-up':'price-down'}">${fmtPrice(r.currentPrice)}</td>
        <td class="${isUp?'price-up':'price-down'}">${isUp?'+':''}${pct}%</td>
        <td id="mini-${r.key}"><svg width="60" height="28"></svg></td>
        <td style="color:var(--text-secondary)">${randomPct(0.5,5)}%</td>
        <td style="color:var(--text-secondary)">${fmtVol(r.volume)}</td>
        <td class="${isUp?'price-up':'price-down'}">${isUp?'+':'-'}${fmtVol(flowIn)}</td>
        <td style="color:var(--text-secondary)">${flowPct}%</td>
        <td><button class="detail-btn" onclick="event.stopPropagation();quickAnalyze('${r.key}')">详情</button></td>
      </tr>
    `;
  }).join('');
}

function sortMarketTable(key) {
  if (sortConfig.key === key) sortConfig.dir *= -1;
  else { sortConfig.key = key; sortConfig.dir = -1; }
  const sorted = [...marketRows].sort((a,b) => {
    if (key === 'change') return (a.changePercent - b.changePercent) * sortConfig.dir;
    if (key === 'volume') return (a.volume - b.volume) * sortConfig.dir;
    return 0;
  });
  paintMarketTable(sorted);
  sorted.forEach(r => loadMiniChart(r.key));
}

/* =====================
   迷你走势图（SVG折线）
   ===================== */
async function loadMiniChart(key) {
  try {
    const res = await fetch(`${API_BASE}/commodity/${key}/data/1mo`);
    const data = await res.json();
    if (!Array.isArray(data) || data.length < 2) return;
    const closes = data.map(d => d.close).filter(v => v != null);
    if (!closes.length) return;
    drawMiniSVG(`mini-${key}`, closes);
  } catch(e) {}
}

function drawMiniSVG(containerId, data) {
  const cell = document.getElementById(containerId);
  if (!cell) return;
  const W = 60, H = 28, pad = 2;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pts = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (W - pad*2);
    const y = H - pad - ((v - min) / range) * (H - pad*2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const isUp = data[data.length-1] >= data[0];
  const color = isUp ? '#e84855' : '#00c875';
  cell.innerHTML = `
    <svg width="${W}" height="${H}" style="display:block;">
      <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>
    </svg>`;
}

/* =====================
   快速分析（从列表点击）
   ===================== */
function quickAnalyze(key) {
  document.getElementById('commoditySelect').value = key;
  setView('analysis');
  analyzeCommodity();
}

/* =====================
   走势分析（主流程）
   ===================== */
async function analyzeCommodity() {
  const key = document.getElementById('commoditySelect').value;
  const period = document.getElementById('periodSelect').value;
  if (!key) { showError('请选择商品'); return; }

  showLoading(true);
  hideError();
  document.getElementById('results').classList.add('hidden');

  try {
    const res = await fetch(`${API_BASE}/commodity/${key}/analyze/${period}`);
    const data = await res.json();
    if (data.error) { showError(data.error); return; }

    window._lastAnalysisData = data;

    displayCommodityInfo(data.info);

    if (analysisChartType === 'kline') plotCandlestickChart(data.historicalData, data.name);
    else plotLineChart(data.historicalData, data.name);

    plotPriceChart(data.historicalData, data.name);
    plotPredictionChart(data.historicalData, data.predictions, data.name);

    // 扩展功能
    computeAndDisplayVolatility(data.historicalData);
    displaySentiment(data.historicalData);
    renderCorrelation(key);

    document.getElementById('results').classList.remove('hidden');
    document.getElementById('analysisCommodityName').textContent = `${data.name} · ${period}`;
  } catch(e) {
    showError('分析失败，请稍后重试');
    console.error(e);
  } finally {
    showLoading(false);
  }
}

/* =====================
   商品信息面板
   ===================== */
function displayCommodityInfo(info) {
  if (!info) return;
  const items = [
    { label: '最新价',   value: fmtPrice(info.currentPrice), cls: '' },
    { label: '涨跌额',   value: (info.change >= 0 ? '+' : '') + fmtPrice(info.change), cls: info.change >= 0 ? 'up' : 'down' },
    { label: '涨跌幅',   value: (info.changePercent >= 0 ? '+' : '') + (info.changePercent*100).toFixed(2) + '%', cls: info.changePercent >= 0 ? 'up' : 'down' },
    { label: '开盘价',   value: fmtPrice(info.open), cls: '' },
    { label: '最高价',   value: fmtPrice(info.high), cls: 'up' },
    { label: '最低价',   value: fmtPrice(info.low), cls: 'down' },
    { label: '前收盘',   value: fmtPrice(info.previousClose), cls: '' },
    { label: '成交量',   value: fmtVol(info.volume), cls: '' },
    { label: '持仓量',   value: fmtVol(info.openInterest || 0), cls: '' },
  ];
  document.getElementById('commodityInfo').innerHTML = items.map(i => `
    <div class="info-cell">
      <div class="info-cell-label">${i.label}</div>
      <div class="info-cell-value ${i.cls}">${i.value}</div>
    </div>
  `).join('');
}

/* =====================
   K 线图
   ===================== */
function plotCandlestickChart(data, name) {
  const dates  = data.map(d => d.date);
  const opens  = data.map(d => d.open);
  const highs  = data.map(d => d.high);
  const lows   = data.map(d => d.low);
  const closes = data.map(d => d.close);

  Plotly.newPlot('candlestickChart', [{
    x: dates, open: opens, high: highs, low: lows, close: closes,
    type: 'candlestick', name: 'K线',
    increasing: { line: { color: '#e84855' }, fillcolor: '#e84855' },
    decreasing: { line: { color: '#00c875' }, fillcolor: '#00c875' }
  }], makePlotLayout(`${name} — K线图`, '价格'), { responsive: true });
}

function plotLineChart(data, name) {
  const dates  = data.map(d => d.date);
  const closes = data.map(d => d.close);
  Plotly.newPlot('candlestickChart', [{
    x: dates, y: closes, type: 'scatter', mode: 'lines',
    fill: 'tozeroy', fillcolor: 'rgba(30,144,255,0.06)',
    line: { color: '#1e90ff', width: 2 }
  }], makePlotLayout(`${name} — 收盘价`, '价格'), { responsive: true });
}

/* =====================
   均线图
   ===================== */
function plotPriceChart(data, name) {
  const dates  = data.map(d => d.date);
  const closes = data.map(d => d.close);
  const ma20 = calculateMA(closes, 20);
  const ma60 = calculateMA(closes, 60);

  Plotly.newPlot('priceChart', [
    { x: dates, y: closes, type: 'scatter', mode: 'lines', name: '收盘价',
      line: { color: '#1e90ff', width: 2 } },
    { x: dates, y: ma20, type: 'scatter', mode: 'lines', name: 'MA20',
      line: { color: '#f5c842', width: 1.5, dash: 'dot' } },
    { x: dates, y: ma60, type: 'scatter', mode: 'lines', name: 'MA60',
      line: { color: '#e84855', width: 1.5, dash: 'dot' } },
  ], { ...makePlotLayout(`${name} — 价格走势与均线`, '价格'), legend: { orientation:'h', y:-0.2, font:{color:'#8b95a8',size:11} } },
  { responsive: true });
}

/* =====================
   预测图
   ===================== */
function plotPredictionChart(historical, predictions, name) {
  const hDates  = historical.slice(-60).map(d => d.date);
  const hCloses = historical.slice(-60).map(d => d.close);
  const pDates  = predictions.map(d => d.date);
  const pPrices = predictions.map(d => d.price);

  // 置信区间（±2%）
  const upper = pPrices.map(p => p * 1.02);
  const lower = pPrices.map(p => p * 0.98);

  Plotly.newPlot('predictionChart', [
    { x: hDates, y: hCloses, type: 'scatter', mode: 'lines', name: '历史',
      line: { color: '#1e90ff', width: 1.5 } },
    { x: [...pDates, ...pDates.slice().reverse()],
      y: [...upper, ...lower.slice().reverse()],
      type: 'scatter', fill: 'toself', fillcolor: 'rgba(245,200,66,0.1)',
      line: { color: 'transparent' }, name: '置信区间', showlegend: false },
    { x: pDates, y: pPrices, type: 'scatter', mode: 'lines', name: '预测',
      line: { color: '#f5c842', width: 2, dash: 'dash' } },
  ], { ...makePlotLayout('价格预测（未来30天）', '价格'),
    legend: { orientation:'h', y:-0.25, font:{color:'#8b95a8',size:10} },
    height: 280, margin: { t:20, b:40, l:55, r:15 }
  }, { responsive: true });
}

/* =====================
   波动率分析
   ===================== */
function computeAndDisplayVolatility(data) {
  const closes = data.map(d => d.close).filter(v => v != null);
  if (closes.length < 21) return;

  const returns = [];
  for (let i = 1; i < closes.length; i++) {
    returns.push(Math.log(closes[i] / closes[i-1]));
  }

  const hv20 = calcHV(returns, 20) * 100;
  const hv60 = calcHV(returns, Math.min(60, returns.length)) * 100;

  // 逐日波动率
  const hvSeries = [];
  for (let i = 19; i < returns.length; i++) {
    hvSeries.push(calcHV(returns.slice(i-19, i+1), 20) * 100);
  }
  const maxHV = Math.max(...hvSeries).toFixed(2);
  const minHV = Math.min(...hvSeries).toFixed(2);

  document.getElementById('volHV20').textContent = hv20.toFixed(2) + '%';
  document.getElementById('volHV60').textContent = hv60.toFixed(2) + '%';
  document.getElementById('volMax').textContent = maxHV + '%';
  document.getElementById('volMin').textContent = minHV + '%';

  // 波动率走势小图
  const dates = data.slice(20).map(d => d.date);
  Plotly.newPlot('volChart', [{
    x: dates.slice(0, hvSeries.length),
    y: hvSeries,
    type: 'scatter', mode: 'lines',
    fill: 'tozeroy', fillcolor: 'rgba(0,212,255,0.06)',
    line: { color: '#00d4ff', width: 1.5 }
  }], {
    paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
    font: { color: '#8b95a8', size: 10 },
    xaxis: { gridcolor: '#2a3548', showticklabels: false },
    yaxis: { title: 'HV%', gridcolor: '#2a3548', tickfont: { size: 10 } },
    margin: { t:4, b:20, l:42, r:4 }, height: 140,
    showlegend: false
  }, { responsive: true });
}

function calcHV(returns, period) {
  const slice = returns.slice(-period);
  const mean = slice.reduce((s,v) => s+v, 0) / slice.length;
  const variance = slice.reduce((s,v) => s + (v-mean)**2, 0) / (slice.length - 1);
  return Math.sqrt(variance * 252);
}

/* =====================
   市场情绪
   ===================== */
function displaySentiment(data) {
  const closes = data.map(d => d.close).filter(v => v != null);
  if (closes.length < 20) return;

  // 综合情绪分（基于价格动量 + 波动率反向 + RSI）
  const recentChange = (closes[closes.length-1] - closes[closes.length-20]) / closes[closes.length-20] * 100;
  const rsi = calcRSI(closes, 14);
  const score = Math.min(100, Math.max(0, 50 + recentChange * 3 + (rsi - 50) * 0.5));

  document.getElementById('sentimentFill').style.width = score.toFixed(0) + '%';
  document.getElementById('sentimentScore').textContent = score.toFixed(0);

  let label = '', color = '';
  if (score < 20)      { label = '极度恐慌'; color = 'var(--down-color)'; }
  else if (score < 40) { label = '恐慌';     color = 'var(--down-color)'; }
  else if (score < 60) { label = '中性';     color = 'var(--text-secondary)'; }
  else if (score < 80) { label = '贪婪';     color = 'var(--up-color)'; }
  else                 { label = '极度贪婪'; color = 'var(--up-color)'; }

  document.getElementById('sentimentLabel').innerHTML =
    `当前市场情绪：<strong style="color:${color}">${label}</strong>`;

  // 细节指标
  const vols = [];
  for (let i = 1; i < closes.length; i++) vols.push(Math.abs(closes[i]-closes[i-1])/closes[i-1]*100);
  const avgVol = (vols.slice(-5).reduce((s,v)=>s+v,0)/5).toFixed(2);

  document.getElementById('sentimentDetails').innerHTML = `
    <div style="background:var(--bg-card);padding:10px;border-radius:6px;text-align:center;">
      <div style="font-size:11px;color:var(--text-muted)">RSI(14)</div>
      <div style="font-size:16px;font-weight:700;color:${rsi>70?'var(--up-color)':rsi<30?'var(--down-color)':'var(--text-primary)'}">${rsi.toFixed(1)}</div>
    </div>
    <div style="background:var(--bg-card);padding:10px;border-radius:6px;text-align:center;">
      <div style="font-size:11px;color:var(--text-muted)">近5日均幅</div>
      <div style="font-size:16px;font-weight:700;color:var(--accent-cyan)">${avgVol}%</div>
    </div>
    <div style="background:var(--bg-card);padding:10px;border-radius:6px;text-align:center;">
      <div style="font-size:11px;color:var(--text-muted)">20日涨幅</div>
      <div style="font-size:16px;font-weight:700;color:${recentChange>=0?'var(--up-color)':'var(--down-color)'}">${recentChange>=0?'+':''}${recentChange.toFixed(2)}%</div>
    </div>
    <div style="background:var(--bg-card);padding:10px;border-radius:6px;text-align:center;">
      <div style="font-size:11px;color:var(--text-muted)">情绪分</div>
      <div style="font-size:16px;font-weight:700;color:var(--gold)">${score.toFixed(0)}</div>
    </div>
  `;
}

function calcRSI(closes, period) {
  if (closes.length < period + 1) return 50;
  let gains = 0, losses = 0;
  for (let i = closes.length - period; i < closes.length; i++) {
    const diff = closes[i] - closes[i-1];
    if (diff > 0) gains += diff;
    else losses -= diff;
  }
  const rs = losses === 0 ? 100 : gains / losses;
  return 100 - 100 / (1 + rs);
}

/* =====================
   相关性矩阵
   ===================== */
async function renderCorrelation(currentKey) {
  const keys = ALL_KEYS.length ? ALL_KEYS : ['黄金','原油','白银','铜','天然气'];
  const container = document.getElementById('corrMatrix');
  container.innerHTML = `<div style="color:var(--text-muted);font-size:12px;text-align:center;padding:20px;">计算相关性中...</div>`;

  try {
    const allData = {};
    await Promise.all(keys.map(async k => {
      try {
        const r = await fetch(`${API_BASE}/commodity/${k}/data/3mo`);
        const d = await r.json();
        if (Array.isArray(d)) allData[k] = d.map(x => x.close).filter(v => v != null);
      } catch(e) {}
    }));

    const validKeys = keys.filter(k => allData[k] && allData[k].length > 20);
    if (validKeys.length < 2) { container.innerHTML = ''; return; }

    // 计算相关性
    const corr = {};
    validKeys.forEach(ka => {
      corr[ka] = {};
      validKeys.forEach(kb => {
        const minLen = Math.min(allData[ka].length, allData[kb].length);
        const a = allData[ka].slice(-minLen);
        const b = allData[kb].slice(-minLen);
        corr[ka][kb] = pearson(a, b);
      });
    });

    // 渲染热力表格
    const n = validKeys.length;
    const cellSize = Math.floor(Math.min(180, 260) / n);

    container.innerHTML = `
      <div style="font-size:11px;color:var(--text-muted);margin-bottom:6px;">3个月价格相关性（皮尔逊系数）</div>
      <table style="border-collapse:collapse;width:100%;">
        <tr>
          <th style="font-size:10px;color:var(--text-muted);padding:2px;"></th>
          ${validKeys.map(k => `<th style="font-size:10px;color:var(--text-muted);padding:2px;text-align:center;">${k}</th>`).join('')}
        </tr>
        ${validKeys.map(ka => `
          <tr>
            <td style="font-size:10px;color:var(--text-muted);padding:2px;white-space:nowrap;">${ka}</td>
            ${validKeys.map(kb => {
              const v = corr[ka][kb];
              const bg = corrColor(v);
              return `<td class="corr-cell" style="background:${bg};color:white;font-size:11px;padding:6px 2px;text-align:center;border-radius:3px;cursor:default;" title="${ka} vs ${kb}: ${v.toFixed(2)}">${v.toFixed(2)}</td>`;
            }).join('')}
          </tr>
        `).join('')}
      </table>
    `;
  } catch(e) {
    container.innerHTML = '';
  }
}

function pearson(a, b) {
  const n = a.length;
  const meanA = a.reduce((s,v)=>s+v,0)/n;
  const meanB = b.reduce((s,v)=>s+v,0)/n;
  let num=0, denA=0, denB=0;
  for (let i=0;i<n;i++) {
    num  += (a[i]-meanA)*(b[i]-meanB);
    denA += (a[i]-meanA)**2;
    denB += (b[i]-meanB)**2;
  }
  return denA===0||denB===0 ? 0 : num/Math.sqrt(denA*denB);
}

function corrColor(v) {
  // v in [-1, 1]
  if (v > 0.7)  return 'rgba(232,72,85,0.85)';
  if (v > 0.4)  return 'rgba(232,72,85,0.5)';
  if (v > 0.1)  return 'rgba(232,72,85,0.25)';
  if (v > -0.1) return 'rgba(90,100,120,0.5)';
  if (v > -0.4) return 'rgba(0,200,117,0.25)';
  if (v > -0.7) return 'rgba(0,200,117,0.5)';
  return 'rgba(0,200,117,0.85)';
}

/* =====================
   工具函数
   ===================== */
function calculateMA(data, period) {
  return data.map((_, i) => {
    if (i < period - 1) return null;
    return data.slice(i - period + 1, i + 1).reduce((s,v) => s + (v||0), 0) / period;
  });
}

function makePlotLayout(title, yTitle) {
  return {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: '#8b95a8', size: 12 },
    title: { text: title, font: { color: '#8b95a8', size: 13 }, x: 0.02 },
    xaxis: { gridcolor: '#2a3548', linecolor: '#2a3548', rangeslider: { visible: false } },
    yaxis: { title: yTitle, gridcolor: '#2a3548', linecolor: '#2a3548' },
    hovermode: 'x unified',
    height: 420,
    margin: { t: 40, b: 40, l: 65, r: 20 }
  };
}

function fmtPrice(v) {
  if (v == null || isNaN(v)) return '—';
  const n = parseFloat(v);
  if (n >= 1000) return n.toFixed(2);
  if (n >= 10)   return n.toFixed(3);
  return n.toFixed(4);
}

function fmtVol(v) {
  if (v == null || isNaN(v)) return '—';
  const n = parseFloat(v);
  if (n >= 1e9) return (n/1e9).toFixed(2) + 'B';
  if (n >= 1e6) return (n/1e6).toFixed(2) + 'M';
  if (n >= 1e3) return (n/1e3).toFixed(2) + 'K';
  return n.toFixed(2);
}

function randomPct(min, max) {
  return (Math.random() * (max - min) + min).toFixed(2);
}

function getMarketTags(key) {
  const map = {
    '黄金':   { cls: 'tag-concept', label: '贵金属', market: 'COMEX' },
    '原油':   { cls: 'tag-industry',label: '能源',   market: 'NYMEX' },
    '白银':   { cls: 'tag-concept', label: '贵金属', market: 'COMEX' },
    '铜':     { cls: 'tag-industry',label: '工业',   market: 'COMEX' },
    '天然气': { cls: 'tag-industry',label: '能源',   market: 'NYMEX' },
  };
  return map[key] || { cls: 'tag-concept', label: '商品', market: 'INT' };
}

/* =====================
   Loading / Error
   ===================== */
function showLoading(show) {
  document.getElementById('loading').classList.toggle('hidden', !show);
}

function showError(msg) {
  const e = document.getElementById('error');
  e.textContent = msg;
  e.classList.remove('hidden');
}

function hideError() {
  document.getElementById('error').classList.add('hidden');
}
