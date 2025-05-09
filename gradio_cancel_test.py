import requests # 用于发送 HTTP 请求

# ComfyUI 服务器的默认地址
# DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188" # 保留注释或移除，因为它在当前函数中未直接使用

def cancel_comfyui_task_action(comfyui_url_base):
    """向 ComfyUI 发送中断请求"""
    interrupt_url = f"{comfyui_url_base}/interrupt"
    status_message = ""
    try:
        # 使用 print 记录日志，因为此模块可能没有配置 log_message
        print(f"Attempting to send interrupt request to: {interrupt_url}")
        response = requests.post(interrupt_url, timeout=5) # 设置超时
        if response.status_code == 200:
            status_message = f"成功发送中断请求到 {interrupt_url}。"
            print(status_message)
        else:
            status_message = f"发送中断请求失败。服务器返回状态码: {response.status_code}。响应: {response.text}"
            print(status_message)
    except requests.exceptions.ConnectionError:
        status_message = f"连接 ComfyUI 服务器 ({comfyui_url_base}) 失败。请确保 ComfyUI 正在运行并且地址正确。"
        print(status_message)
    except requests.exceptions.Timeout:
        status_message = f"发送中断请求到 {interrupt_url} 超时。"
        print(status_message)
    except Exception as e:
        status_message = f"发送中断请求时发生错误: {str(e)}"
        print(status_message)
    return status_message

# 原 Gradio 界面和 if __name__ == "__main__": 部分已被移除，
# 因为 gradio_workflow.py 只导入和使用 cancel_comfyui_task_action 函数。
# 如果需要独立测试此文件，可以将之前的 Gradio Blocks 代码恢复。
