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

# --- 全局状态变量 ---
task_queue = deque()
queue_lock = Lock()
accumulated_image_results = [] # 明确用于图片
last_video_result = None # 用于存储最新的视频路径
results_lock = Lock()
processing_event = Event() # False: 空闲, True: 正在处理
executor = ThreadPoolExecutor(max_workers=1) # 单线程执行生成任务
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

# --- 日志记录函数 ---
def log_message(message):
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]  # 精确到毫秒
    print(f"{timestamp} - {message}")

def find_key_by_name(prompt, name):
    for key, value in prompt.items():
        if isinstance(value, dict) and value.get("_meta", {}).get("title") == name:
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
        seed_key = find_key_by_name(prompt, "🧙hua_gradio随机种")
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

# 修改 generate_image 函数
def generate_image(inputimage1, prompt_text_positive, prompt_text_positive_2, prompt_text_positive_3, prompt_text_positive_4, prompt_text_negative, json_file, hua_width, hua_height, hua_lora, hua_checkpoint, hua_unet):
    execution_id = str(uuid.uuid4())
    print(f"[{execution_id}] 开始生成任务...")
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

    # --- 节点查找 ---
    image_input_key = find_key_by_name(prompt, "☀️gradio前端传入图像")
    seed_key = find_key_by_name(prompt, "🧙hua_gradio随机种")
    text_ok_key = find_key_by_name(prompt, "💧gradio正向提示词")
    text_ok_key_2 = find_key_by_name(prompt, "💧gradio正向提示词2")
    text_ok_key_3 = find_key_by_name(prompt, "💧gradio正向提示词3")
    text_ok_key_4 = find_key_by_name(prompt, "💧gradio正向提示词4")
    text_bad_key = find_key_by_name(prompt, "🔥gradio负向提示词")
    fenbianlv_key = find_key_by_name(prompt, "📜hua_gradio分辨率")
    lora_key = find_key_by_name(prompt, "🌊hua_gradio_Lora仅模型")
    checkpoint_key = find_key_by_name(prompt, "🌊hua_gradio检查点加载器")
    unet_key = find_key_by_name(prompt, "🌊hua_gradio_UNET加载器")
    hua_output_key = find_key_by_name(prompt, "🌙图像输出到gradio前端")
    hua_video_output_key = find_key_by_name(prompt, "🎬视频输出到gradio前端") # 查找视频输出节点

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
             if "image" in prompt.get(image_input_key, {}).get("inputs", {}):
                 # 尝试移除或设置为空，取决于节点期望
                 # prompt[image_input_key]["inputs"]["image"] = None
                 print(f"[{execution_id}] 无输入图像提供，清除节点 {image_input_key} 的 image 输入。")
                 # 或者如果节点必须有输入，则可能需要报错或使用默认图像
                 # return None, None # 如果图生图节点必须有输入

    if seed_key:
        seed = random.randint(0, 0xffffffff)
        prompt[seed_key]["inputs"]["seed"] = seed
        print(f"[{execution_id}] 设置随机种子: {seed}")

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
        except (ValueError, TypeError, KeyError) as e:
             print(f"[{execution_id}] 更新分辨率时出错: {e}. 使用默认值或跳过。")

    # 更新模型选择 (如果节点存在且选择了模型)
    if lora_key and hua_lora != "None": prompt[lora_key]["inputs"]["lora_name"] = hua_lora
    if checkpoint_key and hua_checkpoint != "None": prompt[checkpoint_key]["inputs"]["ckpt_name"] = hua_checkpoint
    if unet_key and hua_unet != "None": prompt[unet_key]["inputs"]["unet_name"] = hua_unet

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

    # 内部辅助函数
    def find_key_by_name_internal(p, name): # 避免与全局函数冲突
        for k, v in p.items():
            if isinstance(v, dict) and v.get("_meta", {}).get("title") == name:
                return k
        return None

    # 检查各个节点是否存在
    has_image_input = find_key_by_name_internal(prompt, "☀️gradio前端传入图像") is not None
    has_pos_prompt_1 = find_key_by_name_internal(prompt, "💧gradio正向提示词") is not None
    has_pos_prompt_2 = find_key_by_name_internal(prompt, "💧gradio正向提示词2") is not None
    has_pos_prompt_3 = find_key_by_name_internal(prompt, "💧gradio正向提示词3") is not None
    has_pos_prompt_4 = find_key_by_name_internal(prompt, "💧gradio正向提示词4") is not None
    has_neg_prompt = find_key_by_name_internal(prompt, "🔥gradio负向提示词") is not None
    has_resolution = find_key_by_name_internal(prompt, "📜hua_gradio分辨率") is not None
    has_lora = find_key_by_name_internal(prompt, "🌊hua_gradio_Lora仅模型") is not None
    has_checkpoint = find_key_by_name_internal(prompt, "🌊hua_gradio检查点加载器") is not None
    has_unet = find_key_by_name_internal(prompt, "🌊hua_gradio_UNET加载器") is not None

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

    # 内部辅助函数 (避免与全局函数冲突)
    def find_key(p, name):
        for k, v in p.items():
            if isinstance(v, dict) and v.get("_meta", {}).get("title") == name:
                return k
        return None

    # 检查节点存在性并更新可见性
    defaults["visible_image_input"] = find_key(prompt, "☀️gradio前端传入图像") is not None
    defaults["visible_pos_prompt_1"] = find_key(prompt, "💧gradio正向提示词") is not None
    defaults["visible_pos_prompt_2"] = find_key(prompt, "💧gradio正向提示词2") is not None
    defaults["visible_pos_prompt_3"] = find_key(prompt, "💧gradio正向提示词3") is not None
    defaults["visible_pos_prompt_4"] = find_key(prompt, "💧gradio正向提示词4") is not None
    defaults["visible_neg_prompt"] = find_key(prompt, "🔥gradio负向提示词") is not None
    defaults["visible_resolution"] = find_key(prompt, "📜hua_gradio分辨率") is not None
    defaults["visible_seed_indicator"] = find_key(prompt, "🧙hua_gradio随机种") is not None
    defaults["visible_image_output"] = find_key(prompt, "🌙图像输出到gradio前端") is not None # 检查图片输出
    defaults["visible_video_output"] = find_key(prompt, "🎬视频输出到gradio前端") is not None # 检查视频输出

    # 检查模型节点并提取默认值
    lora_key = find_key(prompt, "🌊hua_gradio_Lora仅模型")
    if lora_key and lora_key in prompt and "inputs" in prompt[lora_key]:
        defaults["visible_lora"] = True
        defaults["default_lora"] = prompt[lora_key]["inputs"].get("lora_name", "None")
    else:
        defaults["visible_lora"] = False
        defaults["default_lora"] = "None"

    checkpoint_key = find_key(prompt, "🌊hua_gradio检查点加载器")
    if checkpoint_key and checkpoint_key in prompt and "inputs" in prompt[checkpoint_key]:
        defaults["visible_checkpoint"] = True
        defaults["default_checkpoint"] = prompt[checkpoint_key]["inputs"].get("ckpt_name", "None")
    else:
        defaults["visible_checkpoint"] = False
        defaults["default_checkpoint"] = "None"

    unet_key = find_key(prompt, "🌊hua_gradio_UNET加载器")
    if unet_key and unet_key in prompt and "inputs" in prompt[unet_key]:
        defaults["visible_unet"] = True
        defaults["default_unet"] = prompt[unet_key]["inputs"].get("unet_name", "None")
    else:
        defaults["visible_unet"] = False
        defaults["default_unet"] = "None"

    print(f"检查结果 for {json_file}: Defaults={defaults}")
    return defaults


# --- 队列处理函数 ---
def run_queued_tasks(inputimage1, prompt_text_positive, prompt_text_positive_2, prompt_text_positive_3, prompt_text_positive_4, prompt_text_negative, json_file, hua_width, hua_height, hua_lora, hua_checkpoint, hua_unet, queue_count=1, progress=gr.Progress(track_tqdm=True)):
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

    task_params = (inputimage1, prompt_text_positive, prompt_text_positive_2, prompt_text_positive_3, prompt_text_positive_4, prompt_text_negative, json_file, hua_width, hua_height, hua_lora, hua_checkpoint, hua_unet)
    log_message(f"[QUEUE_DEBUG] 接收到新任务请求。当前队列长度 (加锁前): {len(task_queue)}")
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
with gr.Blocks() as demo:
    gr.Markdown("# [封装comfyUI工作流](https://github.com/kungful/ComfyUI_to_webui.git)")

    with gr.Row():
       with gr.Column():  # 左侧列
           # --- 添加实时日志显示区域 ---
           with gr.Accordion("实时日志 (ComfyUI)", open=True):
               log_display = gr.Textbox(
                   label="日志输出",
                   lines=20,
                   max_lines=20,
                   autoscroll=True,
                   interactive=False,
                   show_copy_button=True,
               )

           with gr.Row():
               with gr.Column(scale=3):
                   json_dropdown = gr.Dropdown(choices=get_json_files(), label="选择工作流")
               with gr.Column(scale=1):
                   with gr.Column(scale=1): # 调整比例使按钮不至于太宽
                       refresh_button = gr.Button("🔄 刷新工作流")
                   with gr.Column(scale=1):
                       refresh_model_button = gr.Button("🔄 刷新模型")

           image_accordion = gr.Accordion("上传图像 (折叠,有gradio传入图像节点才会显示上传)", visible=True, open=True)
           with image_accordion:
               input_image = gr.Image(type="pil", label="上传图像", height=156, width=156)

           with gr.Row():
               with gr.Column() as positive_prompt_col:
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
               with gr.Column(scale=1):
                   Random_Seed = gr.HTML("""
                   <div style='text-align: center; margin-bottom: 5px;'>
                       <h2 style="font-size: 12px; margin: 0; color: #00ff00; font-style: italic;">
                           已添加gradio随机种节点
                       </h2>
                   </div>
                   """, visible=False) # 初始隐藏，由 check_seed_node 控制
                   sponsor_display = gr.Markdown(visible=False) # 初始隐藏
               with gr.Column(scale=1):
                   gr.Markdown('我要打十个') # 保留这句骚话
               with gr.Row():
                   with gr.Column(scale=1):
                       queue_status_display = gr.Markdown("队列中: 0 | 处理中: 否")





    # --- 事件处理 ---
    resolution_dropdown.change(fn=update_from_preset, inputs=resolution_dropdown, outputs=[resolution_dropdown, hua_width, hua_height, ratio_display])
    hua_width.change(fn=update_from_inputs, inputs=[hua_width, hua_height], outputs=[resolution_dropdown, ratio_display])
    hua_height.change(fn=update_from_inputs, inputs=[hua_width, hua_height], outputs=[resolution_dropdown, ratio_display])
    flip_btn.click(fn=flip_resolution, inputs=[hua_width, hua_height], outputs=[hua_width, hua_height])

    # JSON 下拉菜单改变时，更新所有相关组件的可见性、默认值 + 输出区域可见性
    def update_ui_on_json_change(json_file):
        defaults = get_workflow_defaults_and_visibility(json_file)
        return (
            gr.update(visible=defaults["visible_image_input"]),
            gr.update(visible=defaults["visible_pos_prompt_1"]),
            gr.update(visible=defaults["visible_pos_prompt_2"]),
            gr.update(visible=defaults["visible_pos_prompt_3"]),
            gr.update(visible=defaults["visible_pos_prompt_4"]),
            gr.update(visible=defaults["visible_neg_prompt"]),
            gr.update(visible=defaults["visible_resolution"]),
            gr.update(visible=defaults["visible_lora"], value=defaults["default_lora"]),
            gr.update(visible=defaults["visible_checkpoint"], value=defaults["default_checkpoint"]),
            gr.update(visible=defaults["visible_unet"], value=defaults["default_unet"]),
            gr.update(visible=defaults["visible_seed_indicator"]),
            gr.update(visible=defaults["visible_image_output"]), # 控制图片 Gallery 可见性
            gr.update(visible=defaults["visible_video_output"])  # 控制视频播放器可见性
        )

    json_dropdown.change(
        fn=update_ui_on_json_change,
        inputs=json_dropdown,
        outputs=[ # 必须严格对应 13 个组件
            image_accordion,         # Accordion
            prompt_positive,         # Textbox
            prompt_positive_2,       # Textbox
            prompt_positive_3,       # Textbox
            prompt_positive_4,       # Textbox
            negative_prompt_col,     # Column (包含 Textbox)
            resolution_row,          # Row (包含 Dropdown, Button, Accordion)
            hua_lora_dropdown,       # Dropdown
            hua_checkpoint_dropdown, # Dropdown
            hua_unet_dropdown,       # Dropdown
            Random_Seed,             # HTML
            output_gallery,          # Gallery (图片输出)
            output_video             # Video (视频输出)
        ]
    )

    refresh_button.click(refresh_json_files, inputs=[], outputs=json_dropdown)

    load_output_button.click(fn=get_output_images, inputs=[], outputs=output_preview_gallery)

    # --- 修改运行按钮的点击事件 ---
    run_button.click(
        fn=run_queued_tasks,
        inputs=[
            input_image, prompt_positive, prompt_positive_2, prompt_positive_3, prompt_positive_4,
            prompt_negative, json_dropdown, hua_width, hua_height, hua_lora_dropdown,
            hua_checkpoint_dropdown, hua_unet_dropdown, queue_count
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
            # 返回 13 个更新，模型设置为 None，输出区域隐藏
            return (
                gr.update(visible=False), # image_accordion
                gr.update(visible=False), # prompt_positive
                gr.update(visible=False), # prompt_positive_2
                gr.update(visible=False), # prompt_positive_3
                gr.update(visible=False), # prompt_positive_4
                gr.update(visible=False), # negative_prompt_col
                gr.update(visible=False), # resolution_row
                gr.update(visible=False, value="None"), # hua_lora_dropdown
                gr.update(visible=False, value="None"), # hua_checkpoint_dropdown
                gr.update(visible=False, value="None"), # hua_unet_dropdown
                gr.update(visible=False), # Random_Seed
                gr.update(visible=False), # output_gallery
                gr.update(visible=False)  # output_video
            )
        else:
            default_json = json_files[0]
            print(f"初始加载，检查默认 JSON: {default_json}")
            # 使用新的更新函数
            return update_ui_on_json_change(default_json)

    demo.load(
        fn=on_load_setup,
        inputs=[],
        outputs=[ # 13 dynamic components
            image_accordion, prompt_positive, prompt_positive_2, prompt_positive_3, prompt_positive_4,
            negative_prompt_col, resolution_row, hua_lora_dropdown, hua_checkpoint_dropdown,
            hua_unet_dropdown, Random_Seed, output_gallery, output_video
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
