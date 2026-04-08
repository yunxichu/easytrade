/**
 * 量化全流程模块 - 前端控制器
 * 对应后端 API: /api/quant/*
 */

// ==================== 全局状态 ====================
const QuantState = {
    currentStep: 'data',
    data: null,
    factors: null,
    model: null,
    optimization: null,
    signals: null
};

// ==================== 步骤导航 ====================
function goToStep(stepName) {
    // 更新侧边栏状态
    document.querySelectorAll('.step-item').forEach(item => {
        item.classList.remove('active');
        if (item.dataset.step === stepName) {
            item.classList.add('active');
        }
    });

    // 更新内容区
    document.querySelectorAll('.quant-section').forEach(section => {
        section.classList.remove('active');
    });
    document.getElementById(`step-${stepName}`).classList.add('active');

    QuantState.currentStep = stepName;
}

// 点击侧边栏步骤
document.querySelectorAll('.step-item').forEach(item => {
    item.addEventListener('click', () => {
        goToStep(item.dataset.step);
    });
});

// ==================== Step 1: 数据接入 ====================
function setSymbols(symbols) {
    document.getElementById('symbols-input').value = symbols;
}

async function fetchData() {
    const source = document.getElementById('data-source').value;
    const dataType = document.getElementById('data-type').value;
    const startDate = document.getElementById('start-date').value;
    const endDate = document.getElementById('end-date').value;
    const freq = document.getElementById('data-freq').value;
    const symbols = document.getElementById('symbols-input').value.split(',').map(s => s.trim());

    showLoading('data-preview-area', '正在获取数据...');

    try {
        const response = await fetch('/api/quant/data/fetch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source,
                data_type: dataType,
                start_date: startDate,
                end_date: endDate,
                freq,
                symbols
            })
        });

        const result = await response.json();
        QuantState.data = result;

        renderDataPreview(result);
    } catch (error) {
        showError('data-preview-area', '数据获取失败: ' + error.message);
    }
}

async function previewData() {
    // 简化的预览功能
    const previewArea = document.getElementById('data-preview-area');
    previewArea.innerHTML = `
        <div class="data-preview">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>日期</th>
                        <th>标的</th>
                        <th>开盘价</th>
                        <th>最高价</th>
                        <th>最低价</th>
                        <th>收盘价</th>
                        <th>成交量</th>
                    </tr>
                </thead>
                <tbody>
                    <tr><td colspan="7" style="text-align:center;color:#888">点击「获取数据」加载真实数据</td></tr>
                </tbody>
            </table>
        </div>
    `;
}

function renderDataPreview(data) {
    const previewArea = document.getElementById('data-preview-area');
    
    if (!data || !data.data) {
        previewArea.innerHTML = '<div class="empty-state"><p>暂无数据</p></div>';
        return;
    }

    // 构建预览表格
    let html = `
        <div class="data-summary">
            <div class="summary-item">
                <span class="summary-label">数据条数</span>
                <span class="summary-value">${data.shape ? data.shape[0] : '--'}</span>
            </div>
            <div class="summary-item">
                <span class="summary-label">标的数量</span>
                <span class="summary-value">${data.symbols ? data.symbols.length : '--'}</span>
            </div>
            <div class="summary-item">
                <span class="summary-label">数据源</span>
                <span class="summary-value">${data.source || '--'}</span>
            </div>
        </div>
        <div class="data-preview">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>字段</th>
                        <th>类型</th>
                        <th>非空数</th>
                        <th>均值</th>
                        <th>标准差</th>
                    </tr>
                </thead>
                <tbody>
                    ${(data.columns || []).map(col => `
                        <tr>
                            <td>${col}</td>
                            <td>float64</td>
                            <td>${data.shape ? data.shape[0] : '--'}</td>
                            <td>--</td>
                            <td>--</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
    
    previewArea.innerHTML = html;
}

// ==================== Step 2: 因子计算 ====================
async function computeFactors() {
    if (!QuantState.data) {
        alert('请先完成数据接入步骤');
        return;
    }

    // 收集选中的因子
    const selectedFactors = [];
    document.querySelectorAll('.factor-item input:checked').forEach(cb => {
        selectedFactors.push(cb.parentElement.textContent.trim());
    });

    try {
        const response = await fetch('/api/quant/factor/compute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                data_id: QuantState.data.data_id,
                factors: selectedFactors,
                neutralize: document.querySelector('select').value,
                standardize: 'zscore'
            })
        });

        const result = await response.json();
        QuantState.factors = result;

        // 渲染IC分析图
        renderICChart(result.ic_analysis);
        
        alert('因子计算完成！');
    } catch (error) {
        alert('因子计算失败: ' + error.message);
    }
}

function renderICChart(icData) {
    const chartDiv = document.getElementById('factor-ic-chart');
    
    // 模拟IC数据
    const factors = ['MOM_20', 'MOM_60', 'VOL_20', 'ATR_14', 'RSI_14'];
    const icValues = [0.032, 0.045, -0.018, 0.012, 0.028];
    const icirValues = [0.45, 0.62, -0.25, 0.18, 0.38];

    const trace1 = {
        x: factors,
        y: icValues,
        type: 'bar',
        name: 'IC均值',
        marker: { color: '#58a6ff' }
    };

    const trace2 = {
        x: factors,
        y: icirValues,
        type: 'scatter',
        mode: 'lines+markers',
        name: 'ICIR',
        yaxis: 'y2',
        line: { color: '#3fb950', width: 2 },
        marker: { size: 8 }
    };

    const layout = {
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: { color: '#c9d1d9' },
        xaxis: { 
            title: '因子',
            gridcolor: '#30363d'
        },
        yaxis: { 
            title: 'IC均值',
            gridcolor: '#30363d',
            zerolinecolor: '#30363d'
        },
        yaxis2: {
            title: 'ICIR',
            overlaying: 'y',
            side: 'right',
            showgrid: false
        },
        legend: { x: 0.02, y: 0.98 },
        margin: { t: 30, r: 60 }
    };

    Plotly.newPlot('factor-ic-chart', [trace1, trace2], layout, {responsive: true});
}

// ==================== Step 3: 模型训练 ====================
// 模型选择卡片
document.querySelectorAll('.model-card').forEach(card => {
    card.addEventListener('click', () => {
        document.querySelectorAll('.model-card').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');
    });
});

async function trainModel() {
    if (!QuantState.factors) {
        alert('请先完成因子计算步骤');
        return;
    }

    const selectedModel = document.querySelector('.model-card.selected').dataset.model;

    try {
        const response = await fetch('/api/quant/model/train', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                factor_id: QuantState.factors.factor_id,
                model_type: selectedModel,
                params: {
                    learning_rate: 0.01,
                    max_depth: 6,
                    n_estimators: 100
                },
                target: 'return_1d',
                train_test_split: 0.8
            })
        });

        const result = await response.json();
        QuantState.model = result;

        // 更新性能指标
        updateModelMetrics(result.metrics);
        renderPerformanceChart(result);

        alert('模型训练完成！');
    } catch (error) {
        alert('模型训练失败: ' + error.message);
    }
}

function updateModelMetrics(metrics) {
    if (!metrics) return;
    
    const metricBoxes = document.querySelectorAll('.metric-box .metric-value');
    metricBoxes[0].textContent = metrics.ic_mean ? metrics.ic_mean.toFixed(3) : '--';
    metricBoxes[1].textContent = metrics.icir ? metrics.icir.toFixed(3) : '--';
    metricBoxes[2].textContent = metrics.rank_ic ? metrics.rank_ic.toFixed(3) : '--';
    metricBoxes[3].textContent = metrics.annual_return ? (metrics.annual_return * 100).toFixed(1) + '%' : '--';
    metricBoxes[4].textContent = metrics.max_drawdown ? (metrics.max_drawdown * 100).toFixed(1) + '%' : '--';
    metricBoxes[5].textContent = metrics.sharpe ? metrics.sharpe.toFixed(2) : '--';
}

function renderPerformanceChart(modelData) {
    // 模拟累计收益曲线
    const dates = [];
    const returns = [];
    let cumReturn = 1;
    
    for (let i = 0; i < 252; i++) {
        const date = new Date('2025-04-01');
        date.setDate(date.getDate() + i);
        dates.push(date.toISOString().split('T')[0]);
        
        const dailyReturn = (Math.random() - 0.45) * 0.02;
        cumReturn *= (1 + dailyReturn);
        returns.push((cumReturn - 1) * 100);
    }

    const trace = {
        x: dates,
        y: returns,
        type: 'scatter',
        mode: 'lines',
        fill: 'tozeroy',
        line: { color: '#58a6ff', width: 2 },
        fillcolor: 'rgba(88, 166, 255, 0.1)'
    };

    const layout = {
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: { color: '#c9d1d9' },
        xaxis: { 
            title: '日期',
            gridcolor: '#30363d'
        },
        yaxis: { 
            title: '累计收益 (%)',
            gridcolor: '#30363d',
            zerolinecolor: '#30363d'
        },
        margin: { t: 20, r: 20 }
    };

    Plotly.newPlot('model-performance-chart', [trace], layout, {responsive: true});
}

// ==================== Step 4: 组合优化 ====================
// 约束条件滑块
document.querySelectorAll('.constraint-slider').forEach(slider => {
    slider.addEventListener('input', (e) => {
        e.target.nextElementSibling.textContent = e.target.value + '%';
    });
});

async function runOptimization() {
    if (!QuantState.model) {
        alert('请先完成模型训练步骤');
        return;
    }

    const objective = document.querySelector('input[name="objective"]:checked').value;

    try {
        const response = await fetch('/api/quant/optimize/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                model_id: QuantState.model.model_id,
                objective: objective,
                constraints: {
                    max_weight: 0.2,
                    min_weight: 0,
                    max_turnover: 0.5,
                    target_volatility: 0.15
                },
                risk_model: 'sample'
            })
        });

        const result = await response.json();
        QuantState.optimization = result;

        renderEfficientFrontier(result.frontier);
        alert('组合优化完成！');
    } catch (error) {
        alert('优化失败: ' + error.message);
    }
}

function renderEfficientFrontier(frontierData) {
    // 模拟有效前沿数据
    const volatilities = [];
    const returns = [];
    
    for (let i = 0; i <= 20; i++) {
        const vol = 0.05 + i * 0.01;
        const ret = 0.02 + i * 0.008 + Math.random() * 0.005;
        volatilities.push(vol * 100);
        returns.push(ret * 100);
    }

    const trace = {
        x: volatilities,
        y: returns,
        type: 'scatter',
        mode: 'lines+markers',
        line: { color: '#58a6ff', width: 2 },
        marker: { size: 6, color: '#58a6ff' },
        name: '有效前沿'
    };

    // 当前组合点
    const currentTrace = {
        x: [15],
        y: [12],
        type: 'scatter',
        mode: 'markers',
        marker: { size: 15, color: '#3fb950', symbol: 'star' },
        name: '当前组合'
    };

    const layout = {
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: { color: '#c9d1d9' },
        xaxis: { 
            title: '波动率 (%)',
            gridcolor: '#30363d'
        },
        yaxis: { 
            title: '预期收益 (%)',
            gridcolor: '#30363d'
        },
        legend: { x: 0.02, y: 0.98 },
        margin: { t: 30, r: 20 }
    };

    Plotly.newPlot('efficient-frontier-chart', [trace, currentTrace], layout, {responsive: true});
}

// ==================== Step 5: 信号输出 ====================
async function generateSignals() {
    if (!QuantState.optimization) {
        alert('请先完成组合优化步骤');
        return;
    }

    try {
        const response = await fetch('/api/quant/signal/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                optimization_id: QuantState.optimization.optimization_id,
                execution_date: new Date().toISOString().split('T')[0],
                initial_capital: 1000000
            })
        });

        const result = await response.json();
        QuantState.signals = result;

        renderPositionTable(result.positions);
        updateSignalStats(result.stats);
        renderBacktestChart(result.backtest);

        alert('信号生成完成！');
    } catch (error) {
        alert('信号生成失败: ' + error.message);
    }
}

function renderPositionTable(positions) {
    const tbody = document.getElementById('position-tbody');
    
    if (!positions || positions.length === 0) {
        tbody.innerHTML = '<tr class="placeholder-row"><td colspan="7">暂无持仓建议</td></tr>';
        return;
    }

    tbody.innerHTML = positions.map(pos => {
        const action = pos.delta > 0 ? '买入' : pos.delta < 0 ? '卖出' : '持有';
        const actionClass = pos.delta > 0 ? 'action-buy' : pos.delta < 0 ? 'action-sell' : 'action-hold';
        
        return `
            <tr>
                <td><strong>${pos.symbol}</strong></td>
                <td>${(pos.current_weight * 100).toFixed(1)}%</td>
                <td>${(pos.target_weight * 100).toFixed(1)}%</td>
                <td class="${pos.delta > 0 ? 'up' : pos.delta < 0 ? 'down' : ''}">${pos.delta > 0 ? '+' : ''}${(pos.delta * 100).toFixed(1)}%</td>
                <td class="${pos.expected_return > 0 ? 'up' : 'down'}">${(pos.expected_return * 100).toFixed(2)}%</td>
                <td>${(pos.confidence * 100).toFixed(0)}%</td>
                <td><span class="action-badge ${actionClass}">${action}</span></td>
            </tr>
        `;
    }).join('');
}

function updateSignalStats(stats) {
    if (!stats) {
        document.getElementById('long-count').textContent = '--';
        document.getElementById('short-count').textContent = '--';
        document.getElementById('neutral-count').textContent = '--';
        document.getElementById('avg-confidence').textContent = '--';
        return;
    }

    document.getElementById('long-count').textContent = stats.long_count || 0;
    document.getElementById('short-count').textContent = stats.short_count || 0;
    document.getElementById('neutral-count').textContent = stats.neutral_count || 0;
    document.getElementById('avg-confidence').textContent = (stats.avg_confidence * 100).toFixed(0) + '%';
}

function renderBacktestChart(backtestData) {
    // 模拟回测曲线
    const dates = [];
    const strategyReturns = [];
    const benchmarkReturns = [];
    
    let strategyCum = 1;
    let benchmarkCum = 1;
    
    for (let i = 0; i < 252; i++) {
        const date = new Date('2025-01-01');
        date.setDate(date.getDate() + i);
        dates.push(date.toISOString().split('T')[0]);
        
        const strategyDaily = (Math.random() - 0.42) * 0.025;
        const benchmarkDaily = (Math.random() - 0.45) * 0.02;
        
        strategyCum *= (1 + strategyDaily);
        benchmarkCum *= (1 + benchmarkDaily);
        
        strategyReturns.push((strategyCum - 1) * 100);
        benchmarkReturns.push((benchmarkCum - 1) * 100);
    }

    const trace1 = {
        x: dates,
        y: strategyReturns,
        type: 'scatter',
        mode: 'lines',
        name: '策略收益',
        line: { color: '#58a6ff', width: 2 }
    };

    const trace2 = {
        x: dates,
        y: benchmarkReturns,
        type: 'scatter',
        mode: 'lines',
        name: '基准收益',
        line: { color: '#8b949e', width: 2, dash: 'dash' }
    };

    const layout = {
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: { color: '#c9d1d9' },
        xaxis: { 
            title: '日期',
            gridcolor: '#30363d'
        },
        yaxis: { 
            title: '累计收益 (%)',
            gridcolor: '#30363d'
        },
        legend: { x: 0.02, y: 0.98 },
        margin: { t: 30, r: 20 }
    };

    Plotly.newPlot('backtest-chart', [trace1, trace2], layout, {responsive: true});
}

async function exportSignals() {
    if (!QuantState.signals) {
        alert('请先生成信号');
        return;
    }

    try {
        const response = await fetch('/api/quant/signal/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                signal_id: QuantState.signals.signal_id,
                format: 'csv'
            })
        });

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `signals_${new Date().toISOString().split('T')[0]}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    } catch (error) {
        alert('导出失败: ' + error.message);
    }
}

// ==================== 工具函数 ====================
function showLoading(elementId, message) {
    document.getElementById(elementId).innerHTML = `
        <div class="loading-state">
            <div class="spinner"></div>
            <p>${message}</p>
        </div>
    `;
}

function showError(elementId, message) {
    document.getElementById(elementId).innerHTML = `
        <div class="error-state">
            <div class="error-icon">⚠️</div>
            <p>${message}</p>
        </div>
    `;
}

// ==================== 初始化 ====================
document.addEventListener('DOMContentLoaded', () => {
    // 初始化图表
    renderICChart();
    renderPerformanceChart();
    renderEfficientFrontier();
    renderBacktestChart();
});
