import json
import time
import random
import requests
import shutil
from collections import Counter, deque # 导入 deque
from PIL import Image, ImageSequence, ImageOps
import re
import io # 导入 io 用于更精确的文件处理
import gradio as gr
import numpy as np
import torch
import threading
from threading import Lock, Event # 导入 Lock 和 Event
from concurrent.futures import ThreadPoolExecutor
import websocket # 添加 websocket 导入
# --- 日志轮询导入 ---
import requests # requests 可能已导入，确认一下
import json # json 可能已导入，确认一下
import time # time 可能已导入，确认一下
# --- 日志轮询导入结束 ---
import folder_paths
import node_helpers
from pathlib import Path
from server import PromptServer
from server import BinaryEventTypes
import sys
import os
import webbrowser
import glob
from datetime import datetime
from math import gcd
import uuid
import fnmatch
from .hua_word_image import HuaFloatNode, HuaIntNode, HuaFloatNode2, HuaFloatNode3, HuaFloatNode4, HuaIntNode2, HuaIntNode3, HuaIntNode4 # 导入新的节点类

# --- 全局状态变量 ---
task_queue = deque()
queue_lock = Lock()
accumulated_image_results = [] # 明确用于图片
last_video_result = None # 用于存储最新的视频路径
results_lock = Lock()
processing_event = Event() # False: 空闲, True: 正在处理
executor = ThreadPoolExecutor(max_workers=1) # 单线程执行生成任务
last_used_seed = -1 # 用于递增/递减模式
seed_lock = Lock() # 用于保护 last_used_seed
# --- 全局状态变量结束 ---

# --- 日志轮询全局变量和函数 ---
COMFYUI_LOG_URL = "http://127.0.0.1:8188/internal/logs/raw"
all_logs_text = ""

def fetch_and_format_logs():
    global all_logs_text

    try:
        response = requests.get(COMFYUI_LOG_URL, timeout=5)
        response.raise_for_status()
        data = response.json()
        log_entries = data.get("entries", [])

        # 移除多余空行并合并日志内容
        formatted_logs = "\n".join(filter(None, [entry.get('m', '').strip() for entry in log_entries]))
        all_logs_text = formatted_logs

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

# --- 日志轮询全局变量和函数结束 ---

# --- ComfyUI 节点徽章设置 ---
# 尝试两种可能的 API 路径
COMFYUI_API_NODE_BADGE = "http://127.0.0.1:8188/settings/Comfy.NodeBadge.NodeIdBadgeMode"
# COMFYUI_API_NODE_BADGE = "http://127.0.0.1:8188/api/settings/Comfy.NodeBadge.NodeIdBadgeMode" # 备用路径

def update_node_badge_mode(mode):
    """发送 POST 请求更新 NodeIdBadgeMode"""
    try:
        # 直接尝试 JSON 格式
        response = requests.post(
            COMFYUI_API_NODE_BADGE,
            json=mode,  # 使用 json 参数自动设置 Content-Type 为 application/json
        )

        if response.status_code == 200:
            return f"✅ 成功更新节点徽章模式为: {mode}"
        else:
            # 尝试解析错误信息
            try:
                error_detail = response.json() # 尝试解析 JSON 错误
                error_text = error_detail.get('error', response.text)
                error_traceback = error_detail.get('traceback', '')
                return f"❌ 更新失败 (HTTP {response.status_code}): {error_text}\n{error_traceback}".strip()
            except json.JSONDecodeError: # 如果不是 JSON 错误
                return f"❌ 更新失败 (HTTP {response.status_code}): {response.text}"
    except requests.exceptions.ConnectionError:
         return f"❌ 请求出错: 无法连接到 ComfyUI 服务器 ({COMFYUI_API_NODE_BADGE})。请确保 ComfyUI 正在运行。"
    except Exception as e:
        return f"❌ 请求出错: {str(e)}"
# --- ComfyUI 节点徽章设置结束 ---

# --- 重启和中断函数 ---
def reboot_manager():
    try:
        # 发送重启请求，改为 GET 方法
        reboot_url = "http://127.0.0.1:8188/api/manager/reboot"
        response = requests.get(reboot_url)  # 改为 GET 请求
        if response.status_code == 200:
            # WebSocket 监听在 Gradio 中会阻塞，简化处理
            # ws_url = "ws://127.0.0.1:8188/ws?clientId=110c8a9cbffc4e4da35ef7d2503fcccf"
            # def on_message(ws, message):
            #     ws.close()
            #     # Gradio click 不能直接返回这个
            # ws = websocket.WebSocketApp(ws_url, on_message=on_message)
            # ws.run_forever() # 这会阻塞
            return "重启请求已发送。请稍后检查 ComfyUI 状态。" # 简化返回信息
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
# --- 重启和中断函数结束 ---


# --- 日志记录函数 ---
def log_message(message):
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]  # 精确到毫秒
    print(f"{timestamp} - {message}")

# 修改函数以通过 class_type 查找，并重命名参数
def find_key_by_class_type(prompt, class_type):
    for key, value in prompt.items():
        # 直接检查 class_type 字段
        if isinstance(value, dict) and value.get("class_type") == class_type:
            return key
    return None

def check_seed_node(json_file):
    if not json_file or not os.path.exists(os.path.join(OUTPUT_DIR, json_file)):
        print(f"JSON 文件无效或不存在: {json_file}")
        return gr.update(visible=False)
    json_path = os.path.join(OUTPUT_DIR, json_file)
    try:
        with open(json_path, "r", encoding="utf-8") as file_json:
            prompt = json.load(file_json)
        # 使用新的函数和真实类名
        seed_key = find_key_by_class_type(prompt, "Hua_gradio_Seed")
        return gr.update(visible=seed_key is not None)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"读取或解析 JSON 文件时出错 ({json_file}): {e}")
        return gr.update(visible=False)

current_dir = os.path.dirname(os.path.abspath(__file__))
print("当前hua插件文件的目录为：", current_dir)
parent_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(parent_dir)
try:
    from comfy.cli_args import args
except ImportError:
    print("无法导入 comfy.cli_args，某些功能可能受限。")
    args = None # 提供一个默认值以避免 NameError

# 尝试导入图标，如果失败则使用默认值
try:
    from .hua_icons import icons
except ImportError:
    print("无法导入 .hua_icons，将使用默认分类名称。")
    icons = {"hua_boy_one": "Gradio"} # 提供一个默认值

class GradioTextOk:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "string": ("STRING", {"multiline": True, "dynamicPrompts": True, "tooltip": "The text to be encoded."}),
            }
        }
    RETURN_TYPES = ("STRING",)
    FUNCTION = "encode"
    CATEGORY = icons.get("hua_boy_one", "Gradio") # 使用 get 提供默认值
    DESCRIPTION = "Encodes a text prompt..."
    def encode(self,string):
        return (string,)

INPUT_DIR = folder_paths.get_input_directory()
OUTPUT_DIR = folder_paths.get_output_directory()
TEMP_DIR = folder_paths.get_temp_directory()

resolution_presets = [
    "512x512|1:1", "1024x1024|1:1", "1152x896|9:7", "1216x832|19:13",
    "1344x768|7:4", "1536x640|12:5", "704x1408|1:2", "704x1344|11:21",
    "768x1344|4:7", "768x1280|3:5", "832x1216|13:19", "832x1152|13:18",
    "896x1152|7:9", "896x1088|14:17", "960x1088|15:17", "960x1024|15:16",
    "1024x960|16:15", "1088x960|17:15", "1088x896|17:14", "1152x832|18:13",
    "1280x768|5:3", "1344x704|21:11", "1408x704|2:1", "1472x704|23:11",
    "1600x640|5:2", "1664x576|26:9", "1728x576|3:1", "custom"
]

def start_queue(prompt_workflow):
    p = {"prompt": prompt_workflow}
    data = json.dumps(p).encode('utf-8')
    URL = "http://127.0.0.1:8188/prompt"
    max_retries = 5
    retry_delay = 10
    request_timeout = 60

    for attempt in range(max_retries):
        try:
            # 简化服务器检查，直接尝试 POST
            response = requests.post(URL, data=data, timeout=request_timeout)
            response.raise_for_status()
            print(f"请求成功 (尝试 {attempt + 1}/{max_retries})")
            return True # 返回成功状态
        except requests.exceptions.RequestException as e:
            error_type = type(e).__name__
            print(f"请求失败 (尝试 {attempt + 1}/{max_retries}, 错误类型: {error_type}): {str(e)}")
            if attempt < max_retries - 1:
                print(f"{retry_delay}秒后重试...")
                time.sleep(retry_delay)
            else:
                print("达到最大重试次数，放弃请求。")
                print("可能原因: 服务器未运行、网络问题、工作流问题（如种子未变）。")
                return False # 返回失败状态

def get_json_files():
    try:
        json_files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith('.json') and os.path.isfile(os.path.join(OUTPUT_DIR, f))]
        return json_files
    except FileNotFoundError:
        print(f"警告: 输出目录 {OUTPUT_DIR} 未找到。")
        return []
    except Exception as e:
        print(f"获取 JSON 文件列表时出错: {e}")
        return []

def refresh_json_files():
    new_choices = get_json_files()
    return gr.update(choices=new_choices)

def parse_resolution(resolution_str):
    if resolution_str == "custom":
        return None, None, "自定义"
    try:
        parts = resolution_str.split("|")
        if len(parts) != 2: return None, None, "无效格式"
        width, height = map(int, parts[0].split("x"))
        ratio = parts[1]
        return width, height, ratio
    except ValueError:
        return None, None, "无效格式"

def calculate_aspect_ratio(width, height):
    if width is None or height is None or width <= 0 or height <= 0:
        return "0:0"
    try:
        w, h = int(width), int(height)
        common_divisor = gcd(w, h)
        return f"{w//common_divisor}:{h//common_divisor}"
    except (ValueError, TypeError):
        return "无效输入"


def find_closest_preset(width, height):
    if width is None or height is None or width <= 0 or height <= 0:
        return "custom"
    try:
        w, h = int(width), int(height)
    except (ValueError, TypeError):
        return "custom"

    for preset in resolution_presets:
        if preset == "custom": continue
        preset_width, preset_height, _ = parse_resolution(preset)
        if preset_width == w and preset_height == h:
            return preset

    aspect = calculate_aspect_ratio(w, h)
    for preset in resolution_presets:
        if preset == "custom": continue
        _, _, preset_aspect = parse_resolution(preset)
        if preset_aspect == aspect:
            # 找到相同比例的第一个预设
            # 可以在这里添加逻辑选择最接近面积的预设，但目前保持简单
            return preset

    return "custom"

def update_from_preset(resolution_str):
    if resolution_str == "custom":
        # 返回空更新，让用户手动输入
        return "custom", gr.update(), gr.update(), "当前比例: 自定义"
    width, height, ratio = parse_resolution(resolution_str)
    if width is None: # 处理无效格式的情况
        return "custom", gr.update(), gr.update(), "当前比例: 无效格式"
    return resolution_str, width, height, f"当前比例: {ratio}"

def update_from_inputs(width, height):
    ratio = calculate_aspect_ratio(width, height)
    closest_preset = find_closest_preset(width, height)
    return closest_preset, f"当前比例: {ratio}"

def flip_resolution(width, height):
    if width is None or height is None:
        return None, None
    try:
        # 确保返回的是数字类型
        return int(height), int(width)
    except (ValueError, TypeError):
        return width, height # 如果转换失败，返回原值

# --- 模型列表获取 ---
def get_model_list(model_type):
    try:
        # 添加 "None" 选项，允许不选择
        return ["None"] + folder_paths.get_filename_list(model_type)
    except Exception as e:
        print(f"获取 {model_type} 列表时出错: {e}")
        return ["None"]

lora_list = get_model_list("loras")
checkpoint_list = get_model_list("checkpoints")
unet_list = get_model_list("unet") # 假设 UNet 模型在 'unet' 目录

def get_output_images():
    image_files = []
    supported_formats = ['*.png', '*.jpg', '*.jpeg', '*.gif', '*.webp', '*.bmp']
    if not os.path.exists(OUTPUT_DIR):
        print(f"警告: 输出目录 {OUTPUT_DIR} 不存在。")
        return []
    try:
        for fmt in supported_formats:
            pattern = os.path.join(OUTPUT_DIR, fmt)
            image_files.extend(glob.glob(pattern))
        image_files.sort(key=os.path.getmtime, reverse=True)
        print(f"在 {OUTPUT_DIR} 中找到 {len(image_files)} 张图片。")
        # 返回绝对路径
        return [os.path.abspath(f) for f in image_files]
    except Exception as e:
        print(f"扫描输出目录时出错: {e}")
        return []

# 修改 generate_image 函数以接受种子模式、固定种子值以及新的 Float/Int 值
def generate_image(inputimage1, input_video, prompt_text_positive, prompt_text_positive_2, prompt_text_positive_3, prompt_text_positive_4, prompt_text_negative, json_file, hua_width, hua_height, hua_lora, hua_checkpoint, hua_unet, hua_float_value, hua_int_value, hua_float_value_2, hua_int_value_2, hua_float_value_3, hua_int_value_3, hua_float_value_4, hua_int_value_4, seed_mode, fixed_seed): # 添加新参数
    global last_used_seed # 声明使用全局变量
    execution_id = str(uuid.uuid4())
    print(f"[{execution_id}] 开始生成任务 (种子模式: {seed_mode})...")
    output_type = None # 'image' or 'video'

    if not json_file:
        print(f"[{execution_id}] 错误: 未选择工作流 JSON 文件。")
        return None, None # 返回 (None, None) 表示失败

    json_path = os.path.join(OUTPUT_DIR, json_file)
    if not os.path.exists(json_path):
        print(f"[{execution_id}] 错误: 工作流 JSON 文件不存在: {json_path}")
        return None, None

    try:
        with open(json_path, "r", encoding="utf-8") as file_json:
            prompt = json.load(file_json)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[{execution_id}] 读取或解析 JSON 文件时出错 ({json_path}): {e}")
        return None, None

    # --- 节点查找 (使用新的函数和真实类名) ---
    image_input_key = find_key_by_class_type(prompt, "GradioInputImage")
    video_input_key = find_key_by_class_type(prompt, "VHS_LoadVideo") # 查找视频输入节点
    seed_key = find_key_by_class_type(prompt, "Hua_gradio_Seed")
    text_ok_key = find_key_by_class_type(prompt, "GradioTextOk")
    text_ok_key_2 = find_key_by_class_type(prompt, "GradioTextOk2")
    text_ok_key_3 = find_key_by_class_type(prompt, "GradioTextOk3")
    text_ok_key_4 = find_key_by_class_type(prompt, "GradioTextOk4")
    text_bad_key = find_key_by_class_type(prompt, "GradioTextBad")
    # 查找分辨率节点并打印调试信息
    fenbianlv_key = find_key_by_class_type(prompt, "Hua_gradio_resolution")
    print(f"[{execution_id}] 查找分辨率节点结果: {fenbianlv_key}")
    if fenbianlv_key:
        print(f"[{execution_id}] 分辨率节点详情: {prompt.get(fenbianlv_key, {})}")
    lora_key = find_key_by_class_type(prompt, "Hua_LoraLoaderModelOnly") # 注意这里用的是仅模型
    checkpoint_key = find_key_by_class_type(prompt, "Hua_CheckpointLoaderSimple")
    unet_key = find_key_by_class_type(prompt, "Hua_UNETLoader")
    hua_output_key = find_key_by_class_type(prompt, "Hua_Output")
    hua_video_output_key = find_key_by_class_type(prompt, "Hua_Video_Output") # 查找视频输出节点
    # --- 新增：查找 Float 和 Int 节点 (包括 2/3/4) ---
    float_node_key = find_key_by_class_type(prompt, "HuaFloatNode")
    int_node_key = find_key_by_class_type(prompt, "HuaIntNode")
    float_node_key_2 = find_key_by_class_type(prompt, "HuaFloatNode2")
    int_node_key_2 = find_key_by_class_type(prompt, "HuaIntNode2")
    float_node_key_3 = find_key_by_class_type(prompt, "HuaFloatNode3")
    int_node_key_3 = find_key_by_class_type(prompt, "HuaIntNode3")
    float_node_key_4 = find_key_by_class_type(prompt, "HuaFloatNode4")
    int_node_key_4 = find_key_by_class_type(prompt, "HuaIntNode4")

    # --- 更新 Prompt ---
    inputfilename = None # 初始化
    if image_input_key:
        if inputimage1 is not None:
            try:
                # 确保 inputimage1 是 PIL Image 对象
                if isinstance(inputimage1, np.ndarray):
                    img = Image.fromarray(inputimage1)
                elif isinstance(inputimage1, Image.Image):
                    img = inputimage1
                else:
                    print(f"[{execution_id}] 警告: 未知的输入图像类型: {type(inputimage1)}。尝试跳过图像输入。")
                    img = None

                if img:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    inputfilename = f"gradio_input_{timestamp}_{random.randint(100, 999)}.png"
                    save_path = os.path.join(INPUT_DIR, inputfilename)
                    img.save(save_path)
                    prompt[image_input_key]["inputs"]["image"] = inputfilename
                    print(f"[{execution_id}] 输入图像已保存到: {save_path}")
            except Exception as e:
                print(f"[{execution_id}] 保存输入图像时出错: {e}")
                # 不设置图像输入，让工作流使用默认值（如果存在）
                if "image" in prompt[image_input_key]["inputs"]:
                    del prompt[image_input_key]["inputs"]["image"] # 或者设置为 None，取决于节点如何处理
        else:
             # 如果没有输入图像，确保节点输入中没有残留的文件名
             if image_input_key and "image" in prompt.get(image_input_key, {}).get("inputs", {}):
                 # 尝试移除或设置为空，取决于节点期望
                 # prompt[image_input_key]["inputs"]["image"] = None
                 print(f"[{execution_id}] 无输入图像提供，清除节点 {image_input_key} 的 image 输入。")
                 # 或者如果节点必须有输入，则可能需要报错或使用默认图像
                 # return None, None # 如果图生图节点必须有输入

    # --- 处理视频输入 ---
    inputvideofilename = None
    if video_input_key:
        if input_video is not None and os.path.exists(input_video):
            try:
                # Gradio 返回的是临时文件路径，需要复制到 ComfyUI 的 input 目录
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                # 保留原始扩展名
                original_ext = os.path.splitext(input_video)[1]
                inputvideofilename = f"gradio_input_{timestamp}_{random.randint(100, 999)}{original_ext}"
                dest_path = os.path.join(INPUT_DIR, inputvideofilename)
                shutil.copy2(input_video, dest_path) # 使用 copy2 保留元数据
                prompt[video_input_key]["inputs"]["video"] = inputvideofilename
                print(f"[{execution_id}] 输入视频已复制到: {dest_path}")
            except Exception as e:
                print(f"[{execution_id}] 复制输入视频时出错: {e}")
                # 清除节点输入，让其使用默认值（如果存在）
                if "video" in prompt[video_input_key]["inputs"]:
                    del prompt[video_input_key]["inputs"]["video"]
        else:
            # 如果没有输入视频或路径无效，确保节点输入中没有残留的文件名
            if "video" in prompt.get(video_input_key, {}).get("inputs", {}):
                print(f"[{execution_id}] 无有效输入视频提供，清除节点 {video_input_key} 的 video 输入。")
                # 移除或设置为空，取决于节点期望
                 # prompt[video_input_key]["inputs"]["video"] = None

    if seed_key:
        with seed_lock: # 保护对 last_used_seed 的访问
            current_seed = 0
            if seed_mode == "随机":
                current_seed = random.randint(0, 0xffffffff)
                print(f"[{execution_id}] 种子模式: 随机. 生成种子: {current_seed}")
            elif seed_mode == "递增":
                if last_used_seed == -1: # 如果是第一次运行递增
                    last_used_seed = random.randint(0, 0xffffffff -1) # 随机选一个初始值，避免总是从0开始且确保能+1
                last_used_seed = (last_used_seed + 1) & 0xffffffff # 递增并处理溢出 (按位与)
                current_seed = last_used_seed
                print(f"[{execution_id}] 种子模式: 递增. 使用种子: {current_seed}")
            elif seed_mode == "递减":
                if last_used_seed == -1: # 如果是第一次运行递减
                    last_used_seed = random.randint(1, 0xffffffff) # 随机选一个初始值，避免总是从0开始且确保能-1
                last_used_seed = (last_used_seed - 1) & 0xffffffff # 递减并处理下溢 (按位与)
                current_seed = last_used_seed
                print(f"[{execution_id}] 种子模式: 递减. 使用种子: {current_seed}")
            elif seed_mode == "固定":
                try:
                    current_seed = int(fixed_seed) & 0xffffffff # 确保是整数且在范围内
                    last_used_seed = current_seed # 固定模式也更新 last_used_seed
                    print(f"[{execution_id}] 种子模式: 固定. 使用种子: {current_seed}")
                except (ValueError, TypeError):
                    current_seed = random.randint(0, 0xffffffff)
                    last_used_seed = current_seed
                    print(f"[{execution_id}] 种子模式: 固定. 固定种子值无效 ('{fixed_seed}')，回退到随机种子: {current_seed}")
            else: # 未知模式，默认为随机
                current_seed = random.randint(0, 0xffffffff)
                last_used_seed = current_seed
                print(f"[{execution_id}] 未知种子模式 '{seed_mode}'. 回退到随机种子: {current_seed}")

            prompt[seed_key]["inputs"]["seed"] = current_seed

    # 更新文本提示词 (如果节点存在)
    if text_ok_key: prompt[text_ok_key]["inputs"]["string"] = prompt_text_positive
    if text_ok_key_2: prompt[text_ok_key_2]["inputs"]["string"] = prompt_text_positive_2
    if text_ok_key_3: prompt[text_ok_key_3]["inputs"]["string"] = prompt_text_positive_3
    if text_ok_key_4: prompt[text_ok_key_4]["inputs"]["string"] = prompt_text_positive_4
    if text_bad_key: prompt[text_bad_key]["inputs"]["string"] = prompt_text_negative

    if fenbianlv_key:
        try:
            width_val = int(hua_width)
            height_val = int(hua_height)
            prompt[fenbianlv_key]["inputs"]["custom_width"] = width_val
            prompt[fenbianlv_key]["inputs"]["custom_height"] = height_val
            print(f"[{execution_id}] 设置分辨率: {width_val}x{height_val}")
            # 添加调试信息
            print(f"[{execution_id}] 分辨率节点ID: {fenbianlv_key}")
            print(f"[{execution_id}] 分辨率节点输入: {prompt[fenbianlv_key]['inputs']}")
        except (ValueError, TypeError, KeyError) as e:
             print(f"[{execution_id}] 更新分辨率时出错: {e}. 使用默认值或跳过。")
             # 打印当前prompt结构帮助调试
             print(f"[{execution_id}] 当前prompt结构: {json.dumps(prompt, indent=2, ensure_ascii=False)}")

    # 更新模型选择 (如果节点存在且选择了模型)
    if lora_key and hua_lora != "None": prompt[lora_key]["inputs"]["lora_name"] = hua_lora
    if checkpoint_key and hua_checkpoint != "None": prompt[checkpoint_key]["inputs"]["ckpt_name"] = hua_checkpoint
    if unet_key and hua_unet != "None": prompt[unet_key]["inputs"]["unet_name"] = hua_unet

    # --- 新增：更新 Float 和 Int 节点输入 ---
    if float_node_key and hua_float_value is not None:
        try:
            prompt[float_node_key]["inputs"]["float_value"] = float(hua_float_value)
            print(f"[{execution_id}] 设置浮点数输入: {hua_float_value}")
        except (ValueError, TypeError, KeyError) as e:
            print(f"[{execution_id}] 更新浮点数输入时出错: {e}. 使用默认值或跳过。")

    if int_node_key and hua_int_value is not None:
        try:
            prompt[int_node_key]["inputs"]["int_value"] = int(hua_int_value)
            print(f"[{execution_id}] 设置整数输入: {hua_int_value}")
        except (ValueError, TypeError, KeyError) as e:
            print(f"[{execution_id}] 更新整数输入时出错: {e}. 使用默认值或跳过。")

    # --- 新增：更新 Float/Int 2/3/4 节点输入 ---
    new_inputs = {
        float_node_key_2: hua_float_value_2, int_node_key_2: hua_int_value_2,
        float_node_key_3: hua_float_value_3, int_node_key_3: hua_int_value_3,
        float_node_key_4: hua_float_value_4, int_node_key_4: hua_int_value_4,
    }
    for node_key, value in new_inputs.items():
        if node_key and value is not None:
            node_info = prompt.get(node_key, {})
            node_type = node_info.get("class_type", "Unknown")
            input_field = "float_value" if "Float" in node_type else "int_value"
            try:
                converted_value = float(value) if "Float" in node_type else int(value)
                prompt[node_key]["inputs"][input_field] = converted_value
                print(f"[{execution_id}] 设置 {node_type} 输入 ({input_field}): {converted_value}")
            except (ValueError, TypeError, KeyError) as e:
                print(f"[{execution_id}] 更新 {node_type} 输入时出错: {e}. 使用默认值或跳过。")


    # --- 设置输出节点的 unique_id ---
    if hua_output_key:
        prompt[hua_output_key]["inputs"]["unique_id"] = execution_id
        output_type = 'image'
        print(f"[{execution_id}] 已将 unique_id 设置给图片输出节点 {hua_output_key}")
    elif hua_video_output_key:
        prompt[hua_video_output_key]["inputs"]["unique_id"] = execution_id
        output_type = 'video'
        print(f"[{execution_id}] 已将 unique_id 设置给视频输出节点 {hua_video_output_key}")
    else:
        print(f"[{execution_id}] 警告: 未找到 '🌙图像输出到gradio前端' 或 '🎬视频输出到gradio前端' 节点，可能无法获取结果。")
        return None, None # 如果必须有输出节点才能工作，则返回失败

    # --- 发送请求并等待结果 ---
    try:
        print(f"[{execution_id}] 调用 start_queue 发送请求...")
        success = start_queue(prompt) # 发送请求到 ComfyUI
        if not success:
             print(f"[{execution_id}] 请求发送失败。")
             return None, None
        print(f"[{execution_id}] 请求已发送，开始等待结果...")
    except Exception as e:
        print(f"[{execution_id}] 调用 start_queue 时发生意外错误: {e}")
        return None, None

    # --- 精确文件获取逻辑 ---
    temp_file_path = os.path.join(TEMP_DIR, f"{execution_id}.json")
    print(f"[{execution_id}] 开始等待临时文件: {temp_file_path}")

    start_time = time.time()
    wait_timeout = 1000
    check_interval = 1

    while time.time() - start_time < wait_timeout:
        if os.path.exists(temp_file_path):
            print(f"[{execution_id}] 检测到临时文件 (耗时: {time.time() - start_time:.1f}秒)")
            try:
                print(f"[{execution_id}] Waiting briefly before reading {temp_file_path}...")
                time.sleep(1.0) # 增加等待时间到 1 秒

                with open(temp_file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if not content:
                        print(f"[{execution_id}] 警告: 临时文件为空。")
                        time.sleep(check_interval)
                        continue
                    print(f"[{execution_id}] Read content: '{content[:200]}...'") # 记录原始内容

                output_paths_data = json.loads(content)
                print(f"[{execution_id}] Parsed JSON data type: {type(output_paths_data)}")

                # --- 检查错误结构 ---
                if isinstance(output_paths_data, dict) and "error" in output_paths_data:
                    error_message = output_paths_data.get("error", "Unknown error from node.")
                    generated_files = output_paths_data.get("generated_files", [])
                    print(f"[{execution_id}] 错误: 节点返回错误: {error_message}. 文件列表 (可能不完整): {generated_files}")
                    try:
                        os.remove(temp_file_path)
                        print(f"[{execution_id}] 已删除包含错误的临时文件。")
                    except OSError as e:
                        print(f"[{execution_id}] 删除包含错误的临时文件失败: {e}")
                    return None, None # 返回失败

                # --- 提取路径列表 ---
                output_paths = []
                if isinstance(output_paths_data, dict) and "generated_files" in output_paths_data:
                    output_paths = output_paths_data["generated_files"]
                    print(f"[{execution_id}] Extracted 'generated_files': {output_paths} (Count: {len(output_paths)})")
                elif isinstance(output_paths_data, list): # 处理旧格式以防万一
                     output_paths = output_paths_data
                     print(f"[{execution_id}] Parsed JSON directly as list: {output_paths} (Count: {len(output_paths)})")
                else:
                    print(f"[{execution_id}] 错误: 无法识别的 JSON 结构。")
                    try: os.remove(temp_file_path)
                    except OSError: pass
                    return None, None # 无法识别的结构

                # --- 详细验证路径 ---
                print(f"[{execution_id}] Starting path validation for {len(output_paths)} paths...")
                valid_paths = []
                invalid_paths = []
                for i, p in enumerate(output_paths):
                    # 在 Windows 上，os.path.abspath 可能不会改变 G:\... 这种已经是绝对路径的格式
                    # 但为了跨平台和标准化，还是用它
                    abs_p = os.path.abspath(p)
                    exists = os.path.exists(abs_p)
                    print(f"[{execution_id}] Validating path {i+1}/{len(output_paths)}: '{p}' -> Absolute: '{abs_p}' -> Exists: {exists}")
                    if exists:
                        valid_paths.append(abs_p)
                    else:
                        invalid_paths.append(p) # 记录原始失败路径

                print(f"[{execution_id}] Validation complete. Valid: {len(valid_paths)}, Invalid: {len(invalid_paths)}")

                # 在记录验证结果后删除临时文件
                try:
                    os.remove(temp_file_path)
                    print(f"[{execution_id}] 已删除临时文件。")
                except OSError as e:
                    print(f"[{execution_id}] 删除临时文件失败: {e}")

                # 检查是否还有有效路径
                if not valid_paths:
                    print(f"[{execution_id}] 错误: 未找到有效的输出文件路径。Invalid paths were: {invalid_paths}")
                    return None, None

                # 确定输出类型 (基于第一个有效文件的后缀)
                first_valid_path = valid_paths[0]
                if first_valid_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')):
                    determined_output_type = 'image'
                elif first_valid_path.lower().endswith(('.mp4', '.webm', '.avi', '.mov', '.mkv')):
                    determined_output_type = 'video'
                else:
                    print(f"[{execution_id}] 警告: 未知的文件类型: {first_valid_path}。默认为图片。")
                    determined_output_type = 'image' # 默认

                # 如果工作流中定义的类型和文件类型不匹配，打印警告
                if output_type and determined_output_type != output_type:
                     print(f"[{execution_id}] 警告: 工作流输出节点类型 ({output_type}) 与实际文件类型 ({determined_output_type}) 不匹配。")

                print(f"[{execution_id}] 任务成功完成，返回类型 '{determined_output_type}' 和 {len(valid_paths)} 个有效路径。")
                return determined_output_type, valid_paths # *** 成功时返回类型和路径列表 ***

            except json.JSONDecodeError as e:
                print(f"[{execution_id}] 读取或解析临时文件 JSON 失败: {e}. 文件内容: '{content[:100]}...'") # 打印部分内容帮助调试
                time.sleep(check_interval * 2) # 等待更长时间再试
            except Exception as e:
                print(f"[{execution_id}] 处理临时文件时发生未知错误: {e}")
                try: os.remove(temp_file_path)
                except OSError: pass
                return None, None # 其他错误，返回 None

        time.sleep(check_interval)

    # 超时处理
    print(f"[{execution_id}] 等待临时文件超时 ({wait_timeout}秒)。")
    return None, None # 超时，返回 None


def fuck(json_file):
    # 检查文件是否存在且有效
    if not json_file or not os.path.exists(os.path.join(OUTPUT_DIR, json_file)):
        print(f"JSON 文件无效或不存在: {json_file}")
        # 返回所有组件都不可见的状态
        return (gr.update(visible=False),) * 10 # 10 个动态组件

    json_path = os.path.join(OUTPUT_DIR, json_file)
    try:
        with open(json_path, "r", encoding="utf-8") as file_json:
            prompt = json.load(file_json)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"读取或解析 JSON 文件时出错 ({json_file}): {e}")
        # 返回所有组件都不可见的状态，并为模型设置默认值 "None"
        visibility_updates = [gr.update(visible=False)] * 7 # 7 non-model dynamic components
        model_updates = [gr.update(visible=False, value="None")] * 3 # 3 model dropdowns
        return tuple(visibility_updates + model_updates) # 10 个动态组件

    # 内部辅助函数 (修改为按 class_type 查找)
    def find_key_by_class_type_internal(p, class_type):
        for k, v in p.items():
            if isinstance(v, dict) and v.get("class_type") == class_type:
                return k
        return None

    # 检查各个节点是否存在 (使用新的内部函数和真实类名)
    has_image_input = find_key_by_class_type_internal(prompt, "GradioInputImage") is not None
    has_pos_prompt_1 = find_key_by_class_type_internal(prompt, "GradioTextOk") is not None
    has_pos_prompt_2 = find_key_by_class_type_internal(prompt, "GradioTextOk2") is not None
    has_pos_prompt_3 = find_key_by_class_type_internal(prompt, "GradioTextOk3") is not None
    has_pos_prompt_4 = find_key_by_class_type_internal(prompt, "GradioTextOk4") is not None
    has_neg_prompt = find_key_by_class_type_internal(prompt, "GradioTextBad") is not None
    has_resolution = find_key_by_class_type_internal(prompt, "Hua_gradio_resolution") is not None
    has_lora = find_key_by_class_type_internal(prompt, "Hua_LoraLoaderModelOnly") is not None
    has_checkpoint = find_key_by_class_type_internal(prompt, "Hua_CheckpointLoaderSimple") is not None
    has_unet = find_key_by_class_type_internal(prompt, "Hua_UNETLoader") is not None

    print(f"检查结果 for {json_file}: Image={has_image_input}, PosP1={has_pos_prompt_1}, PosP2={has_pos_prompt_2}, PosP3={has_pos_prompt_3}, PosP4={has_pos_prompt_4}, NegP={has_neg_prompt}, Res={has_resolution}, Lora={has_lora}, Ckpt={has_checkpoint}, Unet={has_unet}")

    # 返回 gr.update 对象元组，顺序必须与 outputs 列表对应
    return (
        gr.update(visible=has_image_input),
        gr.update(visible=has_pos_prompt_1),
        gr.update(visible=has_pos_prompt_2),
        gr.update(visible=has_pos_prompt_3),
        gr.update(visible=has_pos_prompt_4),
        gr.update(visible=has_neg_prompt),
        gr.update(visible=has_resolution),
        gr.update(visible=has_lora),
        gr.update(visible=has_checkpoint),
        gr.update(visible=has_unet)
    )

# --- 新函数：获取工作流默认值和可见性 ---
def get_workflow_defaults_and_visibility(json_file):
    defaults = {
        "visible_image_input": False,
        "visible_video_input": False, # 新增视频输入可见性
        "visible_pos_prompt_1": False,
        "visible_pos_prompt_2": False,
        "visible_pos_prompt_3": False,
        "visible_pos_prompt_4": False,
        "visible_neg_prompt": False,
        "visible_resolution": False,
        "visible_lora": False,
        "visible_checkpoint": False,
        "visible_unet": False,
        "default_lora": "None",
        "default_checkpoint": "None",
        "default_unet": "None",
        "visible_seed_indicator": False,
        "visible_image_output": False, # 新增
        "visible_video_output": False, # 新增
        "visible_float_input": False, # 新增 Float 可见性
        "default_float_label": "浮点数输入 (Float)", # 新增 Float 默认标签
        "visible_int_input": False,   # 新增 Int 可见性
        "default_int_label": "整数输入 (Int)",     # 新增 Int 默认标签
        "visible_float_input_2": False,
        "default_float_label_2": "浮点数输入 2 (Float)",
        "visible_float_input_3": False,
        "default_float_label_3": "浮点数输入 3 (Float)",
        "visible_float_input_4": False,
        "default_float_label_4": "浮点数输入 4 (Float)",
        "visible_int_input_2": False,
        "default_int_label_2": "整数输入 2 (Int)",
        "visible_int_input_3": False,
        "default_int_label_3": "整数输入 3 (Int)",
        "visible_int_input_4": False,
        "default_int_label_4": "整数输入 4 (Int)",
        # --- 新增：分辨率和提示词默认值 ---
        "default_width": 512,
        "default_height": 512,
        "default_pos_prompt_1": "",
        "default_pos_prompt_2": "",
        "default_pos_prompt_3": "",
        "default_pos_prompt_4": "",
        "default_neg_prompt": "",
        # --- 新增结束 ---
    }
    if not json_file or not os.path.exists(os.path.join(OUTPUT_DIR, json_file)):
        print(f"JSON 文件无效或不存在: {json_file}")
        return defaults # 返回所有都不可见/默认

    json_path = os.path.join(OUTPUT_DIR, json_file)
    try:
        with open(json_path, "r", encoding="utf-8") as file_json:
            prompt = json.load(file_json)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"读取或解析 JSON 文件时出错 ({json_file}): {e}")
        return defaults # 返回所有都不可见/默认

    # 内部辅助函数 (修改为按 class_type 查找)
    def find_key_by_class_type_internal(p, class_type):
        for k, v in p.items():
            if isinstance(v, dict) and v.get("class_type") == class_type:
                return k
        return None

    # 检查节点存在性并更新可见性 (使用新的内部函数和真实类名)
    defaults["visible_image_input"] = find_key_by_class_type_internal(prompt, "GradioInputImage") is not None
    defaults["visible_video_input"] = find_key_by_class_type_internal(prompt, "VHS_LoadVideo") is not None # 检查视频输入节点

    # --- 检查提示词节点并提取默认值 ---
    pos_prompt_1_key = find_key_by_class_type_internal(prompt, "GradioTextOk")
    if pos_prompt_1_key and pos_prompt_1_key in prompt and "inputs" in prompt[pos_prompt_1_key]:
        defaults["visible_pos_prompt_1"] = True
        defaults["default_pos_prompt_1"] = prompt[pos_prompt_1_key]["inputs"].get("string", "")
    else: defaults["visible_pos_prompt_1"] = False

    pos_prompt_2_key = find_key_by_class_type_internal(prompt, "GradioTextOk2")
    if pos_prompt_2_key and pos_prompt_2_key in prompt and "inputs" in prompt[pos_prompt_2_key]:
        defaults["visible_pos_prompt_2"] = True
        defaults["default_pos_prompt_2"] = prompt[pos_prompt_2_key]["inputs"].get("string", "")
    else: defaults["visible_pos_prompt_2"] = False

    pos_prompt_3_key = find_key_by_class_type_internal(prompt, "GradioTextOk3")
    if pos_prompt_3_key and pos_prompt_3_key in prompt and "inputs" in prompt[pos_prompt_3_key]:
        defaults["visible_pos_prompt_3"] = True
        defaults["default_pos_prompt_3"] = prompt[pos_prompt_3_key]["inputs"].get("string", "")
    else: defaults["visible_pos_prompt_3"] = False

    pos_prompt_4_key = find_key_by_class_type_internal(prompt, "GradioTextOk4")
    if pos_prompt_4_key and pos_prompt_4_key in prompt and "inputs" in prompt[pos_prompt_4_key]:
        defaults["visible_pos_prompt_4"] = True
        defaults["default_pos_prompt_4"] = prompt[pos_prompt_4_key]["inputs"].get("string", "")
    else: defaults["visible_pos_prompt_4"] = False

    neg_prompt_key = find_key_by_class_type_internal(prompt, "GradioTextBad")
    if neg_prompt_key and neg_prompt_key in prompt and "inputs" in prompt[neg_prompt_key]:
        defaults["visible_neg_prompt"] = True
        defaults["default_neg_prompt"] = prompt[neg_prompt_key]["inputs"].get("string", "")
    else: defaults["visible_neg_prompt"] = False

    # --- 检查分辨率节点并提取默认值 ---
    resolution_key = find_key_by_class_type_internal(prompt, "Hua_gradio_resolution")
    if resolution_key and resolution_key in prompt and "inputs" in prompt[resolution_key]:
        defaults["visible_resolution"] = True
        # 尝试提取，如果失败则保留默认值 512
        try: defaults["default_width"] = int(prompt[resolution_key]["inputs"].get("custom_width", 512))
        except (ValueError, TypeError): pass
        try: defaults["default_height"] = int(prompt[resolution_key]["inputs"].get("custom_height", 512))
        except (ValueError, TypeError): pass
    else: defaults["visible_resolution"] = False

    defaults["visible_seed_indicator"] = find_key_by_class_type_internal(prompt, "Hua_gradio_Seed") is not None
    defaults["visible_image_output"] = find_key_by_class_type_internal(prompt, "Hua_Output") is not None # 检查图片输出
    defaults["visible_video_output"] = find_key_by_class_type_internal(prompt, "Hua_Video_Output") is not None # 检查视频输出

    # --- 新增：检查 Float 和 Int 节点可见性并提取 name ---
    float_node_key = find_key_by_class_type_internal(prompt, "HuaFloatNode")
    if float_node_key and float_node_key in prompt and "inputs" in prompt[float_node_key]:
        defaults["visible_float_input"] = True
        float_name = prompt[float_node_key]["inputs"].get("name", "FloatInput") # 获取 name，提供默认值
        defaults["default_float_label"] = f"{float_name}: 浮点数输入 (Float)" # 设置带前缀的标签
    else:
        defaults["visible_float_input"] = False
        defaults["default_float_label"] = "浮点数输入 (Float)" # 默认标签

    int_node_key = find_key_by_class_type_internal(prompt, "HuaIntNode")
    if int_node_key and int_node_key in prompt and "inputs" in prompt[int_node_key]:
        defaults["visible_int_input"] = True
        int_name = prompt[int_node_key]["inputs"].get("name", "IntInput") # 获取 name，提供默认值
        defaults["default_int_label"] = f"{int_name}: 整数输入 (Int)" # 设置带前缀的标签
    else:
        defaults["visible_int_input"] = False
        defaults["default_int_label"] = "整数输入 (Int)" # 默认标签

    # --- 新增：检查 Float/Int 2/3/4 节点 ---
    for i in range(2, 5):
        # Float
        float_node_key_i = find_key_by_class_type_internal(prompt, f"HuaFloatNode{i}")
        if float_node_key_i and float_node_key_i in prompt and "inputs" in prompt[float_node_key_i]:
            defaults[f"visible_float_input_{i}"] = True
            float_name_i = prompt[float_node_key_i]["inputs"].get("name", f"FloatInput{i}")
            defaults[f"default_float_label_{i}"] = f"{float_name_i}: 浮点数输入 {i} (Float)"
        else:
            defaults[f"visible_float_input_{i}"] = False
            defaults[f"default_float_label_{i}"] = f"浮点数输入 {i} (Float)"
        # Int
        int_node_key_i = find_key_by_class_type_internal(prompt, f"HuaIntNode{i}")
        if int_node_key_i and int_node_key_i in prompt and "inputs" in prompt[int_node_key_i]:
            defaults[f"visible_int_input_{i}"] = True
            int_name_i = prompt[int_node_key_i]["inputs"].get("name", f"IntInput{i}")
            defaults[f"default_int_label_{i}"] = f"{int_name_i}: 整数输入 {i} (Int)"
        else:
            defaults[f"visible_int_input_{i}"] = False
            defaults[f"default_int_label_{i}"] = f"整数输入 {i} (Int)"

    # 检查模型节点并提取默认值 (使用新的内部函数和真实类名)
    lora_key = find_key_by_class_type_internal(prompt, "Hua_LoraLoaderModelOnly")
    if lora_key and lora_key in prompt and "inputs" in prompt[lora_key]:
        defaults["visible_lora"] = True
        defaults["default_lora"] = prompt[lora_key]["inputs"].get("lora_name", "None")
    else:
        defaults["visible_lora"] = False
        defaults["default_lora"] = "None"

    checkpoint_key = find_key_by_class_type_internal(prompt, "Hua_CheckpointLoaderSimple")
    if checkpoint_key and checkpoint_key in prompt and "inputs" in prompt[checkpoint_key]:
        defaults["visible_checkpoint"] = True
        defaults["default_checkpoint"] = prompt[checkpoint_key]["inputs"].get("ckpt_name", "None")
    else:
        defaults["visible_checkpoint"] = False
        defaults["default_checkpoint"] = "None"

    unet_key = find_key_by_class_type_internal(prompt, "Hua_UNETLoader")
    if unet_key and unet_key in prompt and "inputs" in prompt[unet_key]:
        defaults["visible_unet"] = True
        defaults["default_unet"] = prompt[unet_key]["inputs"].get("unet_name", "None")
    else:
        defaults["visible_unet"] = False
        defaults["default_unet"] = "None"

    print(f"检查结果 for {json_file}: Defaults={defaults}")
    return defaults


# --- 队列处理函数 (更新签名以包含种子参数和新 Float/Int) ---
def run_queued_tasks(inputimage1, input_video, prompt_text_positive, prompt_text_positive_2, prompt_text_positive_3, prompt_text_positive_4, prompt_text_negative, json_file, hua_width, hua_height, hua_lora, hua_checkpoint, hua_unet, hua_float_value, hua_int_value, hua_float_value_2, hua_int_value_2, hua_float_value_3, hua_int_value_3, hua_float_value_4, hua_int_value_4, seed_mode, fixed_seed, queue_count=1, progress=gr.Progress(track_tqdm=True)): # 添加新参数
    global accumulated_image_results, last_video_result # 声明我们要修改全局变量

    # 初始化当前批次结果 (仅用于批量图片任务)
    current_batch_image_results = []

    # 1. 将新任务加入队列
    if queue_count > 1:
        with results_lock:
            accumulated_image_results = []
            current_batch_image_results = []
            last_video_result = None # 批量任务开始时清除旧视频
    elif queue_count == 1:
         # 单任务模式，清除旧视频结果，图片结果将在成功后直接替换
         with results_lock:
             last_video_result = None

    # 将所有参数（包括新的种子参数和 Float/Int 值）打包到 task_params
    task_params = (inputimage1, input_video, prompt_text_positive, prompt_text_positive_2, prompt_text_positive_3, prompt_text_positive_4, prompt_text_negative, json_file, hua_width, hua_height, hua_lora, hua_checkpoint, hua_unet, hua_float_value, hua_int_value, hua_float_value_2, hua_int_value_2, hua_float_value_3, hua_int_value_3, hua_float_value_4, hua_int_value_4, seed_mode, fixed_seed) # 添加新参数到元组
    log_message(f"[QUEUE_DEBUG] 接收到新任务请求 (种子模式: {seed_mode})。当前队列长度 (加锁前): {len(task_queue)}")
    with queue_lock:
        for _ in range(max(1, int(queue_count))):
            task_queue.append(task_params)
        current_queue_size = len(task_queue)
        log_message(f"[QUEUE_DEBUG] 已添加 {queue_count} 个任务到队列。当前队列长度 (加锁后): {current_queue_size}")
    log_message(f"[QUEUE_DEBUG] 任务添加完成，释放锁。")

    # 初始状态更新：显示当前累积结果和队列信息
    with results_lock:
        current_images_copy = accumulated_image_results[:]
        current_video = last_video_result
    log_message(f"[QUEUE_DEBUG] 准备 yield 初始状态更新。队列: {current_queue_size}, 处理中: {processing_event.is_set()}")
    yield {
        queue_status_display: gr.update(value=f"队列中: {current_queue_size} | 处理中: {'是' if processing_event.is_set() else '否'}"),
        output_gallery: gr.update(value=current_images_copy),
        output_video: gr.update(value=current_video) # 显示当前视频
    }
    log_message(f"[QUEUE_DEBUG] 已 yield 初始状态更新。")

    # 2. 检查是否已有进程在处理队列
    log_message(f"[QUEUE_DEBUG] 检查处理状态: processing_event.is_set() = {processing_event.is_set()}")
    if processing_event.is_set():
        log_message("[QUEUE_DEBUG] 已有任务在处理队列，新任务已排队。函数返回。")
        return

    # 3. 开始处理队列
    log_message(f"[QUEUE_DEBUG] 没有任务在处理，准备设置 processing_event 为 True。")
    processing_event.set()
    log_message(f"[QUEUE_DEBUG] processing_event 已设置为 True。开始处理循环。")

    def process_task(task_params):
        try:
            output_type, new_paths = generate_image(*task_params)
            return output_type, new_paths
        except Exception as e:
            log_message(f"[QUEUE_DEBUG] Exception in process_task: {e}")
            return None, None

    try:
        log_message("[QUEUE_DEBUG] Entering main processing loop (while True).")
        while True:
            task_to_run = None
            current_queue_size = 0
            log_message("[QUEUE_DEBUG] Checking queue for tasks (acquiring lock)...")
            with queue_lock:
                if task_queue:
                    task_to_run = task_queue.popleft()
                    current_queue_size = len(task_queue)
                    log_message(f"[QUEUE_DEBUG] Task popped from queue. Remaining: {current_queue_size}")
                else:
                    log_message("[QUEUE_DEBUG] Queue is empty. Breaking loop.")
                    break
            log_message("[QUEUE_DEBUG] Queue lock released.")

            if not task_to_run:
                 log_message("[QUEUE_DEBUG] Warning: No task found after lock release, but loop didn't break?")
                 continue

            # 更新状态：显示正在处理和队列大小
            with results_lock:
                current_images_copy = accumulated_image_results[:]
                current_video = last_video_result
            log_message(f"[QUEUE_DEBUG] Preparing to yield 'Processing' status. Queue: {current_queue_size}")
            yield {
                queue_status_display: gr.update(value=f"队列中: {current_queue_size} | 处理中: 是"),
                output_gallery: gr.update(value=current_images_copy),
                output_video: gr.update(value=current_video)
            }
            log_message(f"[QUEUE_DEBUG] Yielded 'Processing' status.")

            if task_to_run:
                log_message(f"[QUEUE_DEBUG] Starting execution for popped task. Remaining queue: {current_queue_size}")
                progress(0, desc=f"处理任务 (队列剩余 {current_queue_size})")
                log_message(f"[QUEUE_DEBUG] Progress set to 0. Desc: Processing task (Queue remaining {current_queue_size})")
                
                # 提交任务到线程池
                future = executor.submit(process_task, task_to_run)
                log_message(f"[QUEUE_DEBUG] Task submitted to thread pool")
                
                # 等待任务完成，但每0.1秒检查一次，避免完全阻塞
                while not future.done():
                    time.sleep(0.1)
                    yield {
                        queue_status_display: gr.update(value=f"队列中: {current_queue_size} | 处理中: 是 (运行中)"),
                        output_gallery: gr.update(value=accumulated_image_results[:]),
                        output_video: gr.update(value=last_video_result)
                    }
                
                output_type, new_paths = future.result()
                log_message(f"[QUEUE_DEBUG] Task completed. Type: {output_type}, Result: {'Success' if new_paths else 'Failure'}")
                
                progress(1)
                log_message(f"[QUEUE_DEBUG] Progress set to 1.")

                if new_paths:
                    log_message(f"[QUEUE_DEBUG] Task successful, got {len(new_paths)} new paths of type '{output_type}'.")
                    update_dict = {}
                    with results_lock:
                        if output_type == 'image':
                            if queue_count == 1:
                                accumulated_image_results = new_paths # 替换
                            else:
                                current_batch_image_results.extend(new_paths) # 累加批次
                                accumulated_image_results = current_batch_image_results[:] # 更新全局
                            last_video_result = None # 清除旧视频
                            update_dict[output_gallery] = gr.update(value=accumulated_image_results[:], visible=True)
                            update_dict[output_video] = gr.update(value=None, visible=False) # 隐藏视频
                        elif output_type == 'video':
                            # 视频只显示最新的一个
                            last_video_result = new_paths[0] if new_paths else None
                            accumulated_image_results = [] # 清除旧图片
                            update_dict[output_gallery] = gr.update(value=[], visible=False) # 隐藏图片
                            update_dict[output_video] = gr.update(value=last_video_result, visible=True) # 显示视频
                        else: # 未知类型或失败
                             log_message(f"[QUEUE_DEBUG] Unknown output type '{output_type}' or task failed.")
                             # 保持现有显示不变或显示错误？暂时不变
                             update_dict[output_gallery] = gr.update(value=accumulated_image_results[:])
                             update_dict[output_video] = gr.update(value=last_video_result)

                        log_message(f"[QUEUE_DEBUG] Updated results (lock acquired). Images: {len(accumulated_image_results)}, Video: {last_video_result is not None}")

                    update_dict[queue_status_display] = gr.update(value=f"队列中: {current_queue_size} | 处理中: 是 (完成)")
                    log_message(f"[QUEUE_DEBUG] Preparing to yield success update. Queue: {current_queue_size}")
                    yield update_dict
                    log_message(f"[QUEUE_DEBUG] Yielded success update.")
                else:
                    log_message("[QUEUE_DEBUG] Task failed or returned no paths.")
                    with results_lock:
                        current_images_copy = accumulated_image_results[:]
                        current_video = last_video_result
                    log_message(f"[QUEUE_DEBUG] Preparing to yield failure update. Queue: {current_queue_size}")
                    yield {
                         queue_status_display: gr.update(value=f"队列中: {current_queue_size} | 处理中: 是 (失败)"),
                         output_gallery: gr.update(value=current_images_copy),
                         output_video: gr.update(value=current_video),
                    }
                    log_message(f"[QUEUE_DEBUG] Yielded failure update.")

    finally:
        log_message(f"[QUEUE_DEBUG] Entering finally block. Clearing processing_event (was {processing_event.is_set()}).")
        processing_event.clear()
        log_message(f"[QUEUE_DEBUG] processing_event cleared (is now {processing_event.is_set()}).")
        with queue_lock: current_queue_size = len(task_queue)
        with results_lock:
            final_images = accumulated_image_results[:]
            final_video = last_video_result
        log_message(f"[QUEUE_DEBUG] Preparing to yield final status update. Queue: {current_queue_size}, Processing: No")
        yield {
            queue_status_display: gr.update(value=f"队列中: {current_queue_size} | 处理中: 否"),
            output_gallery: gr.update(value=final_images),
            output_video: gr.update(value=final_video)
        }
        log_message("[QUEUE_DEBUG] Yielded final status update. Exiting run_queued_tasks.")

# --- 赞助码处理函数 ---
def show_sponsor_code():
    # 动态读取 js/icon.js 并提取 Base64 数据
    js_icon_path = os.path.join(current_dir, 'js', 'icon.js')
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
            # 使用正则表达式查找第一个 loadImage("data:image/...") 中的 Base64 数据
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

    # 返回一个更新指令，让 Markdown 组件可见并显示内容
    return gr.update(value=sponsor_info, visible=True)

# --- 清除函数 ---
def clear_queue():
    global task_queue
    with queue_lock:
        task_queue.clear()
        current_queue_size = 0
    log_message("任务队列已清除。")
    return gr.update(value=f"队列中: {current_queue_size} | 处理中: {'是' if processing_event.is_set() else '否'}")

def clear_history():
    global accumulated_image_results, last_video_result
    with results_lock:
        accumulated_image_results.clear()
        last_video_result = None
    log_message("图像和视频历史已清除。")
    with queue_lock: current_queue_size = len(task_queue)
    return {
        output_gallery: gr.update(value=[]), # 清空但不隐藏
        output_video: gr.update(value=None), # 清空但不隐藏
        queue_status_display: gr.update(value=f"队列中: {current_queue_size} | 处理中: {'是' if processing_event.is_set() else '否'}")
    }


# --- Gradio 界面 ---
# 黑客风格CSS - 黑底绿字
hacker_css = """
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
"""

with gr.Blocks(css=hacker_css) as demo:
    with gr.Tab("封装comfyui工作流"):
        with gr.Row():
           with gr.Column():  # 左侧列
               # --- 添加实时日志显示区域 ---
               with gr.Accordion("实时日志 (ComfyUI)", open=True, elem_classes="log-display-container"):
                   log_display = gr.Textbox(
                       label="日志输出",
                       lines=20,
                       max_lines=20,
                       autoscroll=True,
                       interactive=False,
                       show_copy_button=True,
                       elem_classes="log-display-container"  # 使用 CSS 控制滚动条和高度
                   )
                
               image_accordion = gr.Accordion("上传图像 (折叠,有gradio传入图像节点才会显示上传)", visible=True, open=True)
               with image_accordion:
                   input_image = gr.Image(type="pil", label="上传图像", height=256, width=256)
    
               # --- 添加视频上传组件 ---
               video_accordion = gr.Accordion("上传视频 (折叠,有gradio传入视频节点才会显示上传)", visible=False, open=True) # 初始隐藏
               with video_accordion:
                   # 使用 filepath 类型，因为 ComfyUI 节点需要文件名
                   # sources=["upload"] 限制为仅上传
                   input_video = gr.Video(label="上传视频", sources=["upload"], height=256, width=256)
    
               with gr.Row():
                   with gr.Column(scale=3):
                       json_dropdown = gr.Dropdown(choices=get_json_files(), label="选择工作流")
                   with gr.Column(scale=1):
                       with gr.Column(scale=1): # 调整比例使按钮不至于太宽
                           refresh_button = gr.Button("🔄 刷新工作流")
                       with gr.Column(scale=1):
                           refresh_model_button = gr.Button("🔄 刷新模型")
    
    
    
               with gr.Row():
                   with gr.Accordion("正向提示文本(折叠)", open=True) as positive_prompt_col:
                       prompt_positive = gr.Textbox(label="正向提示文本 1", elem_id="prompt_positive_1")
                       prompt_positive_2 = gr.Textbox(label="正向提示文本 2", elem_id="prompt_positive_2")
                       prompt_positive_3 = gr.Textbox(label="正向提示文本 3", elem_id="prompt_positive_3")
                       prompt_positive_4 = gr.Textbox(label="正向提示文本 4", elem_id="prompt_positive_4")
               with gr.Column() as negative_prompt_col:
                   prompt_negative = gr.Textbox(label="负向提示文本", elem_id="prompt_negative")
    
               with gr.Row() as resolution_row:
                   with gr.Column(scale=1):
                       resolution_dropdown = gr.Dropdown(choices=resolution_presets, label="分辨率预设", value=resolution_presets[0])
                   with gr.Column(scale=1):
                       with gr.Accordion("宽度和高度设置", open=False):
                           with gr.Column(scale=1):
                               hua_width = gr.Number(label="宽度", value=512, minimum=64, step=64, elem_id="hua_width_input")
                               hua_height = gr.Number(label="高度", value=512, minimum=64, step=64, elem_id="hua_height_input")
                               ratio_display = gr.Markdown("当前比例: 1:1")
                       with gr.Row():
                           with gr.Column(scale=1):
                              flip_btn = gr.Button("↔ 切换宽高")
    
    
    
               with gr.Row():
                   with gr.Column(scale=1):
                       hua_lora_dropdown = gr.Dropdown(choices=lora_list, label="选择 Lora 模型", value="None", elem_id="hua_lora_dropdown")
                   with gr.Column(scale=1):
                       hua_checkpoint_dropdown = gr.Dropdown(choices=checkpoint_list, label="选择 Checkpoint 模型", value="None", elem_id="hua_checkpoint_dropdown")
                   with gr.Column(scale=1):
                       hua_unet_dropdown = gr.Dropdown(choices=unet_list, label="选择 UNet 模型", value="None", elem_id="hua_unet_dropdown")
    
               # --- 添加 Float 和 Int 输入组件 (初始隐藏) ---
               with gr.Row() as float_int_row:
                    with gr.Column(scale=1):
                        hua_float_input = gr.Number(label="浮点数输入 (Float)", visible=False, elem_id="hua_float_input")
                        hua_float_input_2 = gr.Number(label="浮点数输入 2 (Float)", visible=False, elem_id="hua_float_input_2")
                        hua_float_input_3 = gr.Number(label="浮点数输入 3 (Float)", visible=False, elem_id="hua_float_input_3")
                        hua_float_input_4 = gr.Number(label="浮点数输入 4 (Float)", visible=False, elem_id="hua_float_input_4")
                    with gr.Column(scale=1):
                        hua_int_input = gr.Number(label="整数输入 (Int)", precision=0, visible=False, elem_id="hua_int_input") # precision=0 for integer
                        hua_int_input_2 = gr.Number(label="整数输入 2 (Int)", precision=0, visible=False, elem_id="hua_int_input_2")
                        hua_int_input_3 = gr.Number(label="整数输入 3 (Int)", precision=0, visible=False, elem_id="hua_int_input_3")
                        hua_int_input_4 = gr.Number(label="整数输入 4 (Int)", precision=0, visible=False, elem_id="hua_int_input_4")
    
    
    
    
    
    
    
           with gr.Column(): # 右侧列
    
               with gr.Accordion("预览所有输出图片 (点击加载)", open=False):
                   output_preview_gallery = gr.Gallery(label="输出图片预览", columns=4, height="auto", preview=True, object_fit="contain")
                   load_output_button = gr.Button("加载输出图片")
    
               with gr.Row():
                   # 图片和视频输出区域，初始都隐藏，根据工作流显示
                   output_gallery = gr.Gallery(label="生成图片结果", columns=3, height=600, preview=True, object_fit="contain", visible=False)
                   output_video = gr.Video(label="生成视频结果", height=600, autoplay=True, loop=True, visible=False) # 添加视频组件
    
               # --- 添加队列控制按钮 ---
               with gr.Row():
                   queue_status_display = gr.Markdown("队列中: 0 | 处理中: 否") # 移到按钮上方
    
               with gr.Row():
                   with gr.Row():
                       run_button = gr.Button("🚀 开始跑图 (加入队列)", variant="primary",elem_id="align-center")
                       clear_queue_button = gr.Button("🧹 清除队列",elem_id="align-center")
    
                   with gr.Row():
                       clear_history_button = gr.Button("🗑️ 清除显示历史")
                        # --- 添加赞助按钮和显示区域 ---
                       sponsor_button = gr.Button("💖 赞助作者")
    
                   with gr.Row():
                       queue_count = gr.Number(label="队列数量", value=1, minimum=1, step=1, precision=0)
    
    
    
    
    
               with gr.Row():
                   with gr.Column(scale=1, visible=False) as seed_options_col: # 种子选项列，初始隐藏
                       seed_mode_dropdown = gr.Dropdown(
                           choices=["随机", "递增", "递减", "固定"],
                           value="随机",
                           label="种子模式",
                           elem_id="seed_mode_dropdown"
                       )
                       fixed_seed_input = gr.Number(
                           label="固定种子值",
                           value=0,
                           minimum=0,
                           maximum=0xffffffff, # Max unsigned 32-bit int
                           step=1,
                           precision=0,
                           visible=False, # 初始隐藏，仅在模式为 "固定" 时显示
                           elem_id="fixed_seed_input"
                       )
                       sponsor_display = gr.Markdown(visible=False) # 初始隐藏
                   with gr.Column(scale=1):
                       gr.Markdown('我要打十个') # 保留这句骚话
                   # with gr.Row(): # queue_status_display 已移到上方
                   #     with gr.Column(scale=1):
                   #         queue_status_display = gr.Markdown("队列中: 0 | 处理中: 否")
    with gr.Tab("设置"):
        with gr.Column(): # 使用 Column 布局
            gr.Markdown("## 🎛️ ComfyUI 节点徽章控制")
            gr.Markdown("控制 ComfyUI 界面中节点 ID 徽章的显示方式。设置完成请刷新comfyui界面即可。")
            node_badge_mode_radio = gr.Radio(
                choices=["Show all", "Hover", "None"],
                value="Show all", # 默认值可以尝试从 ComfyUI 获取，但这里先设为 Show all
                label="选择节点 ID 徽章显示模式"
            )
            node_badge_output_text = gr.Textbox(label="更新结果", interactive=False)

            # 将事件处理移到 UI 定义之后
            node_badge_mode_radio.change(
                fn=update_node_badge_mode,
                inputs=node_badge_mode_radio,
                outputs=node_badge_output_text
            )
            # TODO: 添加一个按钮或在加载时尝试获取当前设置并更新 Radio 的 value

            gr.Markdown("---") # 添加分隔线
            gr.Markdown("## ⚡ ComfyUI 控制")
            gr.Markdown("重启 ComfyUI 或中断当前正在执行的任务。")

            with gr.Row():
                reboot_button = gr.Button("🔄 重启ComfyUI")
                interrupt_button = gr.Button("🛑 清理/中断当前任务")

            reboot_output = gr.Textbox(label="重启结果", interactive=False)
            interrupt_output = gr.Textbox(label="清理结果", interactive=False)

            # 将事件处理移到 UI 定义之后
            reboot_button.click(fn=reboot_manager, inputs=[], outputs=[reboot_output])
            interrupt_button.click(fn=interrupt_task, inputs=[], outputs=[interrupt_output])

    with gr.Tab("信息"):
        with gr.Column():
            gr.Markdown("### ℹ️ 插件与开发者信息") # 添加标题

            # GitHub Repo Button
            github_repo_btn = gr.Button("本插件 GitHub 仓库")
            github_repo_btn.click(lambda: gr.update(value="https://github.com/kungful/ComfyUI_to_webui.git",visible=True), inputs=[], outputs=[sponsor_display]) # 显示链接

            # Free Mirror Button
            free_mirror_btn = gr.Button("开发者的免费镜像")
            free_mirror_btn.click(lambda: gr.update(value="https://www.xiangongyun.com/image/detail/7b36c1a3-da41-4676-b5b3-03ec25d6e197",visible=True), inputs=[], outputs=[sponsor_display]) # 显示链接

            # Sponsor Button & Display Area
            sponsor_info_btn = gr.Button("💖 赞助开发者")
            info_sponsor_display = gr.Markdown(visible=False) # 此选项卡中用于显示赞助信息的区域
            sponsor_info_btn.click(fn=show_sponsor_code, inputs=[], outputs=[info_sponsor_display]) # 目标新的显示区域

            # Contact Button & Display Area
            contact_btn = gr.Button("开发者联系方式")
            contact_display = gr.Markdown(visible=False) # 联系信息显示区域
            # 使用 lambda 更新 Markdown 组件的值并使其可见
            contact_btn.click(lambda: gr.update(value="**邮箱:** blenderkrita@gmail.com", visible=True), inputs=[], outputs=[contact_display])

            # Tutorial Button
            tutorial_btn = gr.Button("使用教程 (GitHub)")
            tutorial_btn.click(lambda: gr.update(value="https://github.com/kungful/ComfyUI_to_webui.git",visible=True), inputs=[], outputs=[sponsor_display]) # 显示链接

            # 添加一些间距或说明
            gr.Markdown("---")
            gr.Markdown("点击上方按钮获取相关信息或跳转链接。")


    # --- 事件处理 ---

    # --- 节点徽章设置事件 (已在 Tab 内定义) ---
    # node_badge_mode_radio.change(fn=update_node_badge_mode, inputs=node_badge_mode_radio, outputs=node_badge_output_text)

    # --- 其他事件处理 ---
    resolution_dropdown.change(fn=update_from_preset, inputs=resolution_dropdown, outputs=[resolution_dropdown, hua_width, hua_height, ratio_display])
    hua_width.change(fn=update_from_inputs, inputs=[hua_width, hua_height], outputs=[resolution_dropdown, ratio_display])
    hua_height.change(fn=update_from_inputs, inputs=[hua_width, hua_height], outputs=[resolution_dropdown, ratio_display])
    flip_btn.click(fn=flip_resolution, inputs=[hua_width, hua_height], outputs=[hua_width, hua_height])

    # JSON 下拉菜单改变时，更新所有相关组件的可见性、默认值 + 输出区域可见性
    def update_ui_on_json_change(json_file):
        defaults = get_workflow_defaults_and_visibility(json_file)
        # 计算分辨率预设和比例显示
        closest_preset = find_closest_preset(defaults["default_width"], defaults["default_height"])
        ratio_str = calculate_aspect_ratio(defaults["default_width"], defaults["default_height"])
        ratio_display_text = f"当前比例: {ratio_str}"

        return (
            gr.update(visible=defaults["visible_image_input"]),
            gr.update(visible=defaults["visible_video_input"]),
            # 更新提示词可见性和值
            gr.update(visible=defaults["visible_pos_prompt_1"], value=defaults["default_pos_prompt_1"]),
            gr.update(visible=defaults["visible_pos_prompt_2"], value=defaults["default_pos_prompt_2"]),
            gr.update(visible=defaults["visible_pos_prompt_3"], value=defaults["default_pos_prompt_3"]),
            gr.update(visible=defaults["visible_pos_prompt_4"], value=defaults["default_pos_prompt_4"]),
            gr.update(visible=defaults["visible_neg_prompt"], value=defaults["default_neg_prompt"]),
            # 更新分辨率区域可见性
            gr.update(visible=defaults["visible_resolution"]),
            # 更新分辨率组件的值
            gr.update(value=closest_preset), # resolution_dropdown
            gr.update(value=defaults["default_width"]), # hua_width
            gr.update(value=defaults["default_height"]), # hua_height
            gr.update(value=ratio_display_text), # ratio_display
            # 更新模型可见性和值
            gr.update(visible=defaults["visible_lora"], value=defaults["default_lora"]),
            gr.update(visible=defaults["visible_checkpoint"], value=defaults["default_checkpoint"]),
            gr.update(visible=defaults["visible_unet"], value=defaults["default_unet"]),
            # 更新种子区域可见性
            gr.update(visible=defaults["visible_seed_indicator"]),
            # 更新输出区域可见性
            gr.update(visible=defaults["visible_image_output"]),
            gr.update(visible=defaults["visible_video_output"]),
            # 更新 Float/Int 可见性和标签 (包括 2/3/4)
            gr.update(visible=defaults["visible_float_input"], label=defaults["default_float_label"]),
            gr.update(visible=defaults["visible_int_input"], label=defaults["default_int_label"]),
            gr.update(visible=defaults["visible_float_input_2"], label=defaults["default_float_label_2"]),
            gr.update(visible=defaults["visible_int_input_2"], label=defaults["default_int_label_2"]),
            gr.update(visible=defaults["visible_float_input_3"], label=defaults["default_float_label_3"]),
            gr.update(visible=defaults["visible_int_input_3"], label=defaults["default_int_label_3"]),
            gr.update(visible=defaults["visible_float_input_4"], label=defaults["default_float_label_4"]),
            gr.update(visible=defaults["visible_int_input_4"], label=defaults["default_int_label_4"])
        )

    json_dropdown.change(
        fn=update_ui_on_json_change,
        inputs=json_dropdown,
        outputs=[ # 扩展 outputs 列表以包含所有需要更新的组件 (共 26 个)
            image_accordion,         # 1. 图片输入 Accordion
            video_accordion,         # 2. 视频输入 Accordion
            prompt_positive,         # 3. 正向提示 1 Textbox
            prompt_positive_2,       # 4. 正向提示 2 Textbox
            prompt_positive_3,       # 5. 正向提示 3 Textbox
            prompt_positive_4,       # 6. 正向提示 4 Textbox
            prompt_negative,         # 7. 负向提示 Textbox (注意：之前是 negative_prompt_col，现在直接指向 Textbox)
            resolution_row,          # 8. 分辨率 Row (控制整体可见性)
            resolution_dropdown,     # 9. 分辨率预设 Dropdown (更新值)
            hua_width,               # 10. 宽度 Number (更新值)
            hua_height,              # 11. 高度 Number (更新值)
            ratio_display,           # 12. 比例显示 Markdown (更新值)
            hua_lora_dropdown,       # 13. Lora Dropdown
            hua_checkpoint_dropdown, # 14. Checkpoint Dropdown
            hua_unet_dropdown,       # 15. UNet Dropdown
            seed_options_col,        # 16. 种子选项 Column
            output_gallery,          # 17. 图片输出 Gallery
            output_video,            # 18. 视频输出 Video
            hua_float_input,         # 19. Float 输入 Number
            hua_int_input,           # 20. Int 输入 Number
            hua_float_input_2,       # 21. Float 输入 2 Number
            hua_int_input_2,         # 22. Int 输入 2 Number
            hua_float_input_3,       # 23. Float 输入 3 Number
            hua_int_input_3,         # 24. Int 输入 3 Number
            hua_float_input_4,       # 25. Float 输入 4 Number
            hua_int_input_4          # 26. Int 输入 4 Number
        ]
    )

    # --- 新增：根据种子模式显示/隐藏固定种子输入框 ---
    def toggle_fixed_seed_input(mode):
        return gr.update(visible=(mode == "固定"))

    seed_mode_dropdown.change(
        fn=toggle_fixed_seed_input,
        inputs=seed_mode_dropdown,
        outputs=fixed_seed_input
    )
    # --- 新增结束 ---

    refresh_button.click(refresh_json_files, inputs=[], outputs=json_dropdown)

    load_output_button.click(fn=get_output_images, inputs=[], outputs=output_preview_gallery)

    # --- 修改运行按钮的点击事件 ---
    run_button.click(
        fn=run_queued_tasks,
        inputs=[
            input_image, input_video, prompt_positive, prompt_positive_2, prompt_positive_3, prompt_positive_4,
            prompt_negative, json_dropdown, hua_width, hua_height, hua_lora_dropdown,
            hua_checkpoint_dropdown, hua_unet_dropdown, hua_float_input, hua_int_input,
            hua_float_input_2, hua_int_input_2, hua_float_input_3, hua_int_input_3, # 添加新的 Float/Int 输入
            hua_float_input_4, hua_int_input_4, # 添加新的 Float/Int 输入
            seed_mode_dropdown, fixed_seed_input, # 添加新的种子输入
            queue_count
        ],
        outputs=[queue_status_display, output_gallery, output_video] # 增加 output_video
    )

    # --- 添加新按钮的点击事件 ---
    clear_queue_button.click(fn=clear_queue, inputs=[], outputs=[queue_status_display])
    clear_history_button.click(fn=clear_history, inputs=[], outputs=[output_gallery, output_video, queue_status_display]) # 增加 output_video
    sponsor_button.click(fn=show_sponsor_code, inputs=[], outputs=[sponsor_display]) # 绑定赞助按钮事件

    refresh_model_button.click(
        lambda: (
            gr.update(choices=get_model_list("loras")),
            gr.update(choices=get_model_list("checkpoints")),
            gr.update(choices=get_model_list("unet"))
        ),
        inputs=[],
        outputs=[hua_lora_dropdown, hua_checkpoint_dropdown, hua_unet_dropdown]
    )

    # --- 初始加载 ---
    def on_load_setup():
        json_files = get_json_files()
        if not json_files:
            print("未找到 JSON 文件，隐藏所有动态组件并设置默认值")
            # 返回 20 个更新，模型设置为 None，输出区域隐藏，提示词为空，分辨率为默认
            return (
                gr.update(visible=False), # 1. image_accordion
                gr.update(visible=False), # 2. video_accordion
                gr.update(visible=False, value=""), # 3. prompt_positive
                gr.update(visible=False, value=""), # 4. prompt_positive_2
                gr.update(visible=False, value=""), # 5. prompt_positive_3
                gr.update(visible=False, value=""), # 6. prompt_positive_4
                gr.update(visible=False, value=""), # 7. prompt_negative
                gr.update(visible=False), # 8. resolution_row
                gr.update(value="custom"), # 9. resolution_dropdown
                gr.update(value=512), # 10. hua_width
                gr.update(value=512), # 11. hua_height
                gr.update(value="当前比例: 1:1"), # 12. ratio_display
                gr.update(visible=False, value="None"), # 13. hua_lora_dropdown
                gr.update(visible=False, value="None"), # 14. hua_checkpoint_dropdown
                gr.update(visible=False, value="None"), # 15. hua_unet_dropdown
                gr.update(visible=False), # 16. seed_options_col
                gr.update(visible=False), # 17. output_gallery
                gr.update(visible=False), # 18. output_video
                gr.update(visible=False, label="浮点数输入 (Float)"), # 19. hua_float_input
                gr.update(visible=False, label="整数输入 (Int)"),  # 20. hua_int_input
                gr.update(visible=False, label="浮点数输入 2 (Float)"), # 21. hua_float_input_2
                gr.update(visible=False, label="整数输入 2 (Int)"),  # 22. hua_int_input_2
                gr.update(visible=False, label="浮点数输入 3 (Float)"), # 23. hua_float_input_3
                gr.update(visible=False, label="整数输入 3 (Int)"),  # 24. hua_int_input_3
                gr.update(visible=False, label="浮点数输入 4 (Float)"), # 25. hua_float_input_4
                gr.update(visible=False, label="整数输入 4 (Int)")   # 26. hua_int_input_4
            )
        else:
            default_json = json_files[0]
            print(f"初始加载，检查默认 JSON: {default_json}")
            # 使用更新后的 update_ui_on_json_change 函数
            return update_ui_on_json_change(default_json)

    demo.load(
        fn=on_load_setup,
        inputs=[],
        outputs=[ # 必须严格对应 update_ui_on_json_change 返回的 26 个组件
            image_accordion, video_accordion, prompt_positive, prompt_positive_2, prompt_positive_3, prompt_positive_4,
            prompt_negative, resolution_row, resolution_dropdown, hua_width, hua_height, ratio_display,
            hua_lora_dropdown, hua_checkpoint_dropdown, hua_unet_dropdown, seed_options_col,
            output_gallery, output_video, hua_float_input, hua_int_input,
            hua_float_input_2, hua_int_input_2, hua_float_input_3, hua_int_input_3,
            hua_float_input_4, hua_int_input_4
        ]
    )

    # --- 添加日志轮询 Timer ---
    # 每 0.1 秒调用 fetch_and_format_logs，并将结果输出到 log_display (加快刷新以改善滚动)
    log_timer = gr.Timer(0.1, active=True)  # 每 0.1 秒触发一次
    log_timer.tick(fetch_and_format_logs, inputs=None, outputs=log_display)


    # --- Gradio 启动代码 ---
def luanch_gradio(demo_instance): # 接收 demo 实例
    try:
        # 尝试查找可用端口，从 7861 开始
        port = 7861
        while True:
            try:
                # share=True 会尝试创建公网链接，可能需要登录 huggingface
                # server_name="0.0.0.0" 允许局域网访问
                demo_instance.launch(server_name="0.0.0.0", server_port=port, share=False, prevent_thread_lock=True)
                print(f"Gradio 界面已在 http://127.0.0.1:{port} (或局域网 IP) 启动")
                # 启动成功后打开本地链接
                webbrowser.open(f"http://127.0.0.1:{port}/")
                break # 成功启动，退出循环
            except OSError as e:
                if "address already in use" in str(e).lower():
                    print(f"端口 {port} 已被占用，尝试下一个端口...")
                    port += 1
                    if port > 7870: # 限制尝试范围
                        print("无法找到可用端口 (7861-7870)。")
                        break
                else:
                    print(f"启动 Gradio 时发生未知 OS 错误: {e}")
                    break # 其他 OS 错误，退出
            except Exception as e:
                 print(f"启动 Gradio 时发生未知错误: {e}")
                 break # 其他错误，退出
    except Exception as e:
        print(f"执行 luanch_gradio 时出错: {e}")


# 使用守护线程，这样主程序退出时 Gradio 线程也会退出
gradio_thread = threading.Thread(target=luanch_gradio, args=(demo,), daemon=True)
gradio_thread.start()

# 主线程可以继续执行其他任务或等待，这里简单地保持运行
# 注意：如果这是插件的一部分，主线程可能是 ComfyUI 本身，不需要无限循环
# print("主线程继续运行... 按 Ctrl+C 退出。")
# try:
#     while True:
#         time.sleep(1)
# except KeyboardInterrupt:
#     print("收到退出信号，正在关闭...")
#     # demo.close() # 关闭 Gradio 服务 (如果需要手动关闭)
