import gradio as gr
import requests
import time
import json
import threading

# 假设 ComfyUI 服务器运行在本地指定端口
COMFYUI_URL = "http://127.0.0.1:8188/internal/logs/raw"

# 用于存储上次获取的日志数量，避免重复显示
last_log_count = 0
all_logs_text = ""

# 添加全局变量控制 Timer 的激活状态
is_timer_active = True

# 修改 fetch_and_format_logs 函数，确保每次都从服务器获取最新日志
# 并强制刷新 log_display 的内容

def fetch_and_format_logs():
    global last_log_count
    global all_logs_text

    try:
        response = requests.get(COMFYUI_URL, timeout=5)  # 设置超时
        response.raise_for_status()  # 如果请求失败则抛出异常
        data = response.json()
        log_entries = data.get("entries", [])

        # 强制刷新所有日志内容，移除多余空行
        formatted_logs = "\n".join([entry.get('m', '') for entry in log_entries])
        all_logs_text = formatted_logs
        last_log_count = len(log_entries)  # 更新日志计数

        return all_logs_text

    except requests.exceptions.RequestException as e:
        error_message = f"无法连接到 ComfyUI 服务器: {e}"
        return all_logs_text + "\n" + error_message if all_logs_text else error_message
    except json.JSONDecodeError:
        error_message = "无法解析服务器响应 (非 JSON)"
        return all_logs_text + "\n" + error_message if all_logs_text else error_message
    except Exception as e:
        error_message = f"发生未知错误: {e}"
        return all_logs_text + "\n" + error_message if all_logs_text else error_message


# 确保 Timer 的 tick 方法绑定了 fetch_and_format_logs 函数，并正确更新 log_display
# 修复可能的 Timer 未激活问题
with gr.Blocks() as demo:
    gr.Markdown("## ComfyUI 实时日志查看器")
    log_display = gr.Textbox(
        label="日志输出",
        lines=20,
        max_lines=20,
        autoscroll=True,
        interactive=False,
        show_copy_button=True,
    )

    # Timer 每 1 毫秒触发一次 fetch_and_format_logs
    timer = gr.Timer(0.001, active=True)  # 设置为 1 毫秒
    timer.tick(fetch_and_format_logs, inputs=None, outputs=log_display)

    # 添加启动和停止按钮，确保 Timer 的状态可以被控制
    with gr.Row():
        start_button = gr.Button("开始/恢复轮询")
        stop_button = gr.Button("停止轮询")

    # 修改按钮点击事件以控制 is_timer_active 的值
    start_button.click(lambda: (set_timer_active(True), start_millisecond_timer()), None, None)
    stop_button.click(lambda: set_timer_active(False), None, None)

def set_timer_active(active):
    global is_timer_active
    is_timer_active = active

def start_millisecond_timer():
    def update_logs():
        global is_timer_active
        while is_timer_active:
            fetch_and_format_logs()
            time.sleep(0.001)  # 设置为 1 毫秒

    thread = threading.Thread(target=update_logs, daemon=True)
    thread.start()

if __name__ == "__main__":
    demo.launch(server_port=7862)
