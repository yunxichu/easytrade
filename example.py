from main import CommodityAnalyzer

def main():
    print("="*60)
    print("外盘商品走势分析 - 快速示例")
    print("="*60)

    analyzer = CommodityAnalyzer()

    print("\n正在分析黄金（COMEX黄金）...")
    analyzer.analyze_commodity('黄金', period='1y')

    print("\n" + "="*60)
    print("正在分析原油（WTI原油）...")
    print("="*60)
    analyzer.analyze_commodity('原油', period='1y')

    print("\n" + "="*60)
    print("示例运行完成！")
    print("生成的文件：")
    print("- 黄金_走势.png")
    print("- 黄金_K线.html")
    print("- 黄金_预测.html")
    print("- 原油_走势.png")
    print("- 原油_K线.html")
    print("- 原油_预测.html")
    print("="*60)

if __name__ == "__main__":
    main()
