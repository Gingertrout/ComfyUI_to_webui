import gradio as gr
import websockets
import asyncio
import json
import threading
from typing import Dict

# ComfyUI WebSocket 地址
COMFYUI_WS_URL = "ws://localhost:8188/ws"

class ComfyUIProgressMonitor:
    def __init__(self):
        self.websocket = None
        self.progress = 0
        self.current_node = "等待任务开始..."
        self.is_running = False

    async def connect_websocket(self):
        """连接 WebSocket 并监听进度"""
        try:
            async with websockets.connect(COMFYUI_WS_URL) as websocket:
                self.websocket = websocket
                while self.is_running:
                    message = await websocket.recv()
                    data = json.loads(message)
                    if data["type"] == "progress":
                        self.progress = data["data"]["value"]
                    elif data["type"] == "execution_status":
                        node_name = data["data"]["status"]["exec_info"].get("current_node", "未知节点")
                        self.current_node = f"当前节点: {node_name}"
        except Exception as e:
            print(f"WebSocket 错误: {e}")

    def start(self):
        """启动 WebSocket 监听线程"""
        if not self.is_running:
            self.is_running = True
            self.thread = threading.Thread(
                target=lambda: asyncio.run(self.connect_websocket()),
                daemon=True
            )
            self.thread.start()
            return "监控已启动！"
        return "监控已在运行中..."

    def stop(self):
        """停止监控"""
        if self.is_running:
            self.is_running = False
            if self.thread.is_alive():
                self.thread.join()
            return "监控已停止！"
        return "监控未启动"

    def get_progress(self) -> Dict[str, int]:
        """返回当前进度和节点信息"""
        return {
            "progress": self.progress,
            "current_node": self.current_node
        }

# 创建监控实例
monitor = ComfyUIProgressMonitor()

# 定时更新进度函数
def update_progress():
    status = monitor.get_progress()
    return status["progress"], status["current_node"]

# Gradio 界面
with gr.Blocks(title="ComfyUI 血条式进度监控", theme="soft") as demo:
    gr.Markdown("## 🎮 ComfyUI 推理进度 (血条模式)")

    with gr.Row():
        start_btn = gr.Button("▶️ 启动监控", variant="primary")
        stop_btn = gr.Button("⏹️ 停止监控", variant="stop")
        status_text = gr.Textbox(label="监控状态", interactive=False)

    with gr.Row():
        # 血条式进度条（使用 Slider 模拟）
        progress_bar = gr.Slider(
            minimum=0,
            maximum=100,
            value=0,
            label="推理进度",
            interactive=False,
            elem_classes="hp-bar"
        )

    with gr.Row():
        node_display = gr.Textbox(label="任务状态", interactive=False)

    # 自定义CSS让进度条更像血条
    demo.css = """
    .hp-bar .gr-slider-max {
        background: linear-gradient(to right, #ff0000, #00ff00);
    }
    .hp-bar .gr-slider-value {
        background-color: #ff5722;
    }
    """

    # 按钮事件
    start_btn.click(
        fn=monitor.start,
        outputs=status_text
    )

    stop_btn.click(
        fn=monitor.stop,
        outputs=status_text
    )

    # --- 添加日志轮询 Timer ---
    # 每 0.5 秒调用 update_progress，并将结果输出到 progress_bar 和 node_display
    timer = gr.Timer(0.5, active=True)  # 每 0.5 秒触发一次
    timer.tick(update_progress, inputs=None, outputs=[progress_bar, node_display])

# 启动 Gradio
if __name__ == "__main__":
    demo.launch()