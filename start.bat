@echo off
echo ========================================
echo 外盘商品走势分析与预测系统
echo ========================================
echo.

echo [1/3] 检查Python环境...
python --version
if errorlevel 1 (
    echo 错误：未找到Python，请先安装Python
    pause
    exit /b 1
)

echo.
echo [2/3] 安装依赖包...
pip install -r requirements.txt

echo.
echo [3/3] 启动Web应用...
echo.
echo ========================================
echo 应用启动成功！
echo 请在浏览器中访问: http://localhost:5000
echo 按 Ctrl+C 停止应用
echo ========================================
echo.

cd backend
python app.py
