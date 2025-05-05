import gradio as gr
import requests
import time
import websocket

def reboot_manager():
    try:
        # 发送重启请求，改为 GET 方法
        reboot_url = "http://127.0.0.1:8188/api/manager/reboot"
        response = requests.get(reboot_url)  # 改为 GET 请求
        if response.status_code == 200:
            # 等待 WebSocket 确认重启
            ws_url = "ws://127.0.0.1:8188/ws?clientId=110c8a9cbffc4e4da35ef7d2503fcccf"
            def on_message(ws, message):
                ws.close()
                return f"重启成功: {message}"

            ws = websocket.WebSocketApp(ws_url, on_message=on_message)
            ws.run_forever()
            return "重启请求已发送，等待确认..."
        else:
            return f"重启请求失败，状态码: {response.status_code}"
    except Exception as e:
        return f"发生错误: {str(e)}"

def interrupt_task():
    try:
        # 发送清理当前任务请求
        interrupt_url = "http://127.0.0.1:8188/api/interrupt"
        response = requests.get(interrupt_url)
        if response.status_code == 200:
            return "清理当前任务请求已发送成功。"
        else:
            return f"清理当前任务请求失败，状态码: {response.status_code}"
    except Exception as e:
        return f"发生错误: {str(e)}"

# Gradio 界面
def gradio_interface():
    with gr.Blocks() as demo:
        gr.Markdown("# ComfyUI 管理器重启工具")
        reboot_button = gr.Button("重启管理器")
        output = gr.Textbox(label="输出")

        interrupt_button = gr.Button("清理当前任务")
        interrupt_output = gr.Textbox(label="清理输出")

        reboot_button.click(fn=reboot_manager, inputs=[], outputs=[output])
        interrupt_button.click(fn=interrupt_task, inputs=[], outputs=[interrupt_output])

    return demo

if __name__ == "__main__":
    app = gradio_interface()
    app.launch()