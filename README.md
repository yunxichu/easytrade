# 外盘商品走势分析与预测系统

## 项目简介

本项目是一个完整的前后端Web应用，用于展示外盘商品（如原油、黄金等）的价格走势，并基于历史数据进行简单的价格预测。数据从Yahoo Finance实时获取。

## 功能特性

### Web应用功能
1. **现代化Web界面**
   - 响应式设计，支持桌面和移动端
   - 美观的渐变UI设计
   - 实时交互体验

2. **数据获取**
   - 支持 Yahoo Finance 数据源
   - 实时获取商品行情数据

3. **走势展示**
   - 交互式K线图
   - 价格走势线图 + 20日/60日均线
   - 实时更新数据

4. **合约信息**
   - 最新价
   - 涨跌额 / 涨跌幅（红涨绿跌显示）
   - 开盘价 / 最高价 / 最低价 / 前收盘价
   - 成交量 / 持仓量

5. **价格预测**
   - 基于线性回归的智能预测
   - 未来30天价格预测
   - 可视化预测结果

### 支持的品种

| 品种 | 代码 | 名称 |
|------|------|------|
| 黄金 | GC=F | COMEX黄金 |
| 原油 | CL=F | WTI原油 |
| 白银 | SI=F | COMEX白银 |
| 铜 | HG=F | COMEX铜 |
| 天然气 | NG=F | NYMEX天然气 |

## 技术架构

### 后端（Flask）
- **框架**: Flask
- **数据获取**: yfinance
- **数据处理**: pandas, numpy
- **预测**: scikit-learn (LinearRegression)
- **API设计**: RESTful API

### 前端
- **图表库**: Plotly.js
- **样式**: 原生CSS3（渐变设计）
- **交互**: 原生JavaScript (ES6+)

## 快速开始

### 方式一：使用启动脚本（推荐）

Windows系统直接双击运行：
```bash
start.bat
```

脚本会自动完成：
1. 检查Python环境
2. 安装依赖包
3. 启动Web应用

### 方式二：手动启动

#### 1. 安装依赖

```bash
pip install -r requirements.txt
```

#### 2. 启动后端服务

```bash
cd backend
python app.py
```

#### 3. 访问应用

在浏览器中打开：
```
http://localhost:5000
```

## 项目结构

```
外盘商品走势分析与预测系统/
├── backend/
│   └── app.py                 # Flask后端应用
├── frontend/
│   ├── static/
│   │   ├── style.css          # 前端样式
│   │   └── app.js             # 前端交互逻辑
│   └── templates/
│       └── index.html         # 主页面
├── main.py                    # 原始命令行版本
├── example.py                 # 示例代码
├── requirements.txt           # 依赖包列表
├── start.bat                  # Windows启动脚本
└── README.md                  # 项目说明
```

## API接口说明

### 获取商品列表
```
GET /api/commodities
```

### 获取商品信息
```
GET /api/commodity/<commodity_key>/info
```

### 获取历史数据
```
GET /api/commodity/<commodity_key>/data/<period>
```

### 获取价格预测
```
GET /api/commodity/<commodity_key>/predict/<period>
```

### 完整分析（一次性获取所有数据）
```
GET /api/commodity/<commodity_key>/analyze/<period>
```

参数说明：
- `commodity_key`: 商品键值（黄金、原油、白银、铜、天然气）
- `period`: 时间周期（1mo, 3mo, 6mo, 1y, 2y, 5y）

## 使用说明

1. **选择商品**：从下拉菜单中选择要分析的商品品种
2. **选择周期**：选择历史数据的时间周期
3. **开始分析**：点击"开始分析"按钮
4. **查看结果**：
   - 商品信息卡片展示实时行情
   - K线图展示价格走势
   - 价格走势图展示收盘价和均线
   - 预测图展示未来30天价格预测

## 注意事项

1. 预测结果仅供参考，不构成投资建议
2. 确保网络连接正常以获取实时数据
3. 首次运行可能需要较长时间下载数据
4. 请使用现代浏览器（Chrome、Firefox、Edge等）以获得最佳体验

## 命令行版本

项目仍保留原始命令行版本：

```bash
python main.py
```

## 许可证

MIT License

