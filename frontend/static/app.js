const API_BASE = '/api';

document.addEventListener('DOMContentLoaded', () => {
    loadCommodities();
    
    document.getElementById('analyzeBtn').addEventListener('click', analyzeCommodity);
});

async function loadCommodities() {
    try {
        const response = await fetch(`${API_BASE}/commodities`);
        const commodities = await response.json();
        
        const select = document.getElementById('commoditySelect');
        commodities.forEach(commodity => {
            const option = document.createElement('option');
            option.value = commodity.key;
            option.textContent = `${commodity.key} (${commodity.name})`;
            select.appendChild(option);
        });
    } catch (error) {
        showError('加载商品列表失败');
        console.error(error);
    }
}

async function analyzeCommodity() {
    const commodityKey = document.getElementById('commoditySelect').value;
    const period = document.getElementById('periodSelect').value;
    
    if (!commodityKey) {
        showError('请选择商品');
        return;
    }
    
    showLoading(true);
    hideError();
    hideResults();
    
    try {
        const response = await fetch(`${API_BASE}/commodity/${commodityKey}/analyze/${period}`);
        const data = await response.json();
        
        if (data.error) {
            showError(data.error);
            return;
        }
        
        displayCommodityInfo(data.info);
        plotCandlestickChart(data.historicalData, data.name);
        plotPriceChart(data.historicalData, data.name);
        plotPredictionChart(data.historicalData, data.predictions, data.name);
        
        showResults();
    } catch (error) {
        showError('分析失败，请稍后重试');
        console.error(error);
    } finally {
        showLoading(false);
    }
}

function displayCommodityInfo(info) {
    if (!info) return;
    
    const container = document.getElementById('commodityInfo');
    container.innerHTML = '';
    
    const infoItems = [
        { label: '名称', value: info.name },
        { label: '最新价', value: info.currentPrice, format: 'price' },
        { label: '涨跌额', value: info.change, format: 'change' },
        { label: '涨跌幅', value: info.changePercent, format: 'percent' },
        { label: '开盘价', value: info.open, format: 'price' },
        { label: '最高价', value: info.high, format: 'price' },
        { label: '最低价', value: info.low, format: 'price' },
        { label: '前收盘价', value: info.previousClose, format: 'price' },
        { label: '成交量', value: info.volume, format: 'volume' },
        { label: '持仓量', value: info.openInterest }
    ];
    
    infoItems.forEach(item => {
        const card = document.createElement('div');
        card.className = 'info-card';
        
        const label = document.createElement('div');
        label.className = 'info-card-label';
        label.textContent = item.label;
        
        const value = document.createElement('div');
        value.className = 'info-card-value';
        value.textContent = formatValue(item.value, item.format);
        
        if (item.format === 'change' || item.format === 'percent') {
            const numValue = parseFloat(item.value);
            if (numValue > 0) {
                value.classList.add('positive');
                value.textContent = '+' + value.textContent;
            } else if (numValue < 0) {
                value.classList.add('negative');
            }
        }
        
        card.appendChild(label);
        card.appendChild(value);
        container.appendChild(card);
    });
}

function formatValue(value, format) {
    if (value === null || value === undefined || value === 'N/A') {
        return 'N/A';
    }
    
    switch (format) {
        case 'price':
            return parseFloat(value).toFixed(2);
        case 'change':
            return parseFloat(value).toFixed(2);
        case 'percent':
            return (parseFloat(value) * 100).toFixed(2) + '%';
        case 'volume':
            return formatNumber(value);
        default:
            return value;
    }
}

function formatNumber(num) {
    if (num >= 1000000) {
        return (num / 1000000).toFixed(2) + 'M';
    } else if (num >= 1000) {
        return (num / 1000).toFixed(2) + 'K';
    }
    return num.toString();
}

function plotCandlestickChart(data, name) {
    const dates = data.map(d => d.date);
    const opens = data.map(d => d.open);
    const highs = data.map(d => d.high);
    const lows = data.map(d => d.low);
    const closes = data.map(d => d.close);
    
    const trace = {
        x: dates,
        open: opens,
        high: highs,
        low: lows,
        close: closes,
        type: 'candlestick',
        name: 'K线',
        increasing: { line: { color: '#28a745' } },
        decreasing: { line: { color: '#dc3545' } }
    };
    
    const layout = {
        title: `${name} - K线图`,
        xaxis: { title: '日期', rangeslider: { visible: false } },
        yaxis: { title: '价格' },
        hovermode: 'x unified',
        height: 500,
        margin: { t: 60, b: 40, l: 60, r: 40 }
    };
    
    Plotly.newPlot('candlestickChart', [trace], layout);
}

function plotPriceChart(data, name) {
    const dates = data.map(d => d.date);
    const closes = data.map(d => d.close);
    
    const ma20 = calculateMA(closes, 20);
    const ma60 = calculateMA(closes, 60);
    
    const traceClose = {
        x: dates,
        y: closes,
        type: 'scatter',
        mode: 'lines',
        name: '收盘价',
        line: { color: '#667eea', width: 2 }
    };
    
    const traceMA20 = {
        x: dates,
        y: ma20,
        type: 'scatter',
        mode: 'lines',
        name: '20日均线',
        line: { color: '#f18f01', width: 1.5, dash: 'dash' }
    };
    
    const traceMA60 = {
        x: dates,
        y: ma60,
        type: 'scatter',
        mode: 'lines',
        name: '60日均线',
        line: { color: '#a23b72', width: 1.5, dash: 'dash' }
    };
    
    const layout = {
        title: `${name} - 价格走势与均线`,
        xaxis: { title: '日期' },
        yaxis: { title: '价格' },
        hovermode: 'x unified',
        height: 500,
        margin: { t: 60, b: 40, l: 60, r: 40 },
        legend: { orientation: 'h', y: -0.2 }
    };
    
    Plotly.newPlot('priceChart', [traceClose, traceMA20, traceMA60], layout);
}

function calculateMA(data, period) {
    const result = [];
    for (let i = 0; i < data.length; i++) {
        if (i < period - 1) {
            result.push(null);
        } else {
            const sum = data.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0);
            result.push(sum / period);
        }
    }
    return result;
}

function plotPredictionChart(historicalData, predictions, name) {
    const historicalDates = historicalData.map(d => d.date);
    const historicalCloses = historicalData.map(d => d.close);
    
    const predictionDates = predictions.map(d => d.date);
    const predictionPrices = predictions.map(d => d.price);
    
    const traceHistorical = {
        x: historicalDates,
        y: historicalCloses,
        type: 'scatter',
        mode: 'lines',
        name: '历史价格',
        line: { color: '#667eea', width: 2 }
    };
    
    const tracePrediction = {
        x: predictionDates,
        y: predictionPrices,
        type: 'scatter',
        mode: 'lines',
        name: '预测价格',
        line: { color: '#f18f01', width: 2, dash: 'dash' }
    };
    
    const layout = {
        title: `${name} - 价格预测（未来30天）`,
        xaxis: { title: '日期' },
        yaxis: { title: '价格' },
        hovermode: 'x unified',
        height: 500,
        margin: { t: 60, b: 40, l: 60, r: 40 },
        legend: { orientation: 'h', y: -0.2 }
    };
    
    Plotly.newPlot('predictionChart', [traceHistorical, tracePrediction], layout);
}

function showLoading(show) {
    const loading = document.getElementById('loading');
    if (show) {
        loading.classList.remove('hidden');
    } else {
        loading.classList.add('hidden');
    }
}

function showError(message) {
    const error = document.getElementById('error');
    error.textContent = message;
    error.classList.remove('hidden');
}

function hideError() {
    const error = document.getElementById('error');
    error.classList.add('hidden');
}

function showResults() {
    const results = document.getElementById('results');
    results.classList.remove('hidden');
}

function hideResults() {
    const results = document.getElementById('results');
    results.classList.add('hidden');
}
