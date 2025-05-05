import requests
import gradio as gr

# 尝试两种可能的 API 路径
COMFYUI_API = "http://127.0.0.1:8188/settings/Comfy.NodeBadge.NodeIdBadgeMode"
# COMFYUI_API = "http://127.0.0.1:8188/api/settings/Comfy.NodeBadge.NodeIdBadgeMode"

def update_node_badge_mode(mode):
    """发送 POST 请求更新 NodeIdBadgeMode"""
    try:
        # 直接尝试 JSON 格式
        response = requests.post(
            COMFYUI_API,
            json=mode,  # 使用 json 参数自动设置 Content-Type 为 application/json
        )
        
        if response.status_code == 200:
            return f"✅ 成功更新: {mode}"
        else:
            return f"❌ 失败 (HTTP {response.status_code}): {response.text}"
    except Exception as e:
        return f"❌ 请求出错: {str(e)}"

# Gradio UI
with gr.Blocks() as demo:
    gr.Markdown("## 🎛️ ComfyUI 节点徽章控制")
    mode_radio = gr.Radio(
        choices=["Show all", "Hover", "None"],
        value="Show all",
        label="选择徽章模式"
    )
    output_text = gr.Textbox(label="结果")
    mode_radio.change(update_node_badge_mode, inputs=mode_radio, outputs=output_text)

demo.launch(server_port=7863)