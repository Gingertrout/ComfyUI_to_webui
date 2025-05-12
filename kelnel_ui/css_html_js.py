import os
import re

HACKER_CSS = """
.log-display-container {
    background-color: black !important;
    color: #00ff00 !important;
}
.log-display-container h4 {
    color: #00ff00 !important;
}
.log-display-container textarea {
    background-color: black !important;
    color: #00ff00 !important;
    /* border-color: #00ff00 !important; */
}

/* 调整 Gradio Tab 间距 */
.tabs > .tab-nav { /* Tab 按钮所在的导航栏 */
    margin-bottom: 0px !important; /* 移除导航栏下方的外边距 */
    border-bottom: none !important; /* 移除导航栏下方的边框 (如果存在) */
}

.tabitem { /* Tab 内容区域 */
    padding-top: 0px !important; /* 大幅减少内容区域的上内边距，留一点点空隙 */
    margin-top: 0px !important; /* 确保内容区域没有上外边距 */
}
"""

def get_sponsor_html():
    # 假设 js/icon.js 相对于当前文件 (css_html_js.py) 的路径
    # 如果 css_html_js.py 和 gradio_workflow.py 在同一目录，
    # 并且 js 文件夹也在该目录下，则此相对路径有效。
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    js_icon_path = os.path.join(current_script_dir, 'js', 'icon.js')
    base64_data = None
    default_sponsor_info = """
<div style='text-align: center;'>
    <h3>感谢您的支持！</h3>
    <p>无法加载赞助码图像。</p>
</div>
"""
    try:
        with open(js_icon_path, 'r', encoding='utf-8') as f:
            js_content = f.read()
            match = re.search(r'loadImage\("(data:image/[^;]+;base64,[^"]+)"\)', js_content)
            if match:
                base64_data = match.group(1)
            else:
                print(f"警告: 在 {js_icon_path} 中未找到符合格式的 Base64 数据。")

    except FileNotFoundError:
        print(f"错误: 未找到赞助码图像文件: {js_icon_path}")
    except Exception as e:
        print(f"读取或解析赞助码图像文件时出错 ({js_icon_path}): {e}")

    if base64_data:
        sponsor_info = f"""
<div style='text-align: center;'>
    <h3>感谢您的支持！</h3>
    <p>请使用以下方式赞助：</p>
    <img src='{base64_data}' alt='赞助码' width='512' height='512'>
</div>
"""
    else:
        sponsor_info = default_sponsor_info
    return sponsor_info

# 可以在这里添加 JS 代码的变量或函数，如果需要的话
# 例如:
# MY_JS_CODE = """
# console.log("Hello from JS!");
# """
