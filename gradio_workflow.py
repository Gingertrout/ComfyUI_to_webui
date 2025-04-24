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
accumulated_results = []
results_lock = Lock()
processing_event = Event() # False: 空闲, True: 正在处理

# --- 日志读取相关全局变量 ---
# 构建日志文件的绝对路径
# __file__ 是当前脚本 (gradio_workflow.py) 的路径
# os.path.dirname(__file__) 获取脚本所在目录 (ComfyUI_to_webui)
# '..' 向上移动一级到 custom_nodes
# '..' 再次向上移动一级到 ComfyUI
# 'user' 进入 user 目录
# 'comfyui.log' 指定日志文件名
LOG_FILE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'user', 'comfyui.log'))
print(f"日志文件路径设置为: {LOG_FILE_PATH}") # 打印确认路径
MAX_LOG_LINES = 200 # 显示最后 N 行日志
log_lines_deque = deque(maxlen=MAX_LOG_LINES)
last_log_pos = 0 # 记录上次读取的文件位置
log_timer_active = False # 跟踪日志定时器的状态
# --- 全局状态变量结束 ---

# --- 日志读取函数 ---
def read_new_log_entries():
    global log_lines_deque, last_log_pos
    try:
        # 检查文件是否存在，如果不存在则清空 deque 并重置位置
        if not os.path.exists(LOG_FILE_PATH):
            if last_log_pos > 0 or len(log_lines_deque) > 0: # 仅在之前有内容时清除
                log_lines_deque.clear()
                last_log_pos = 0
                print("日志文件不存在，已清空显示。")
            return "等待日志文件创建..."

        # 使用二进制模式打开以精确控制位置
        with open(LOG_FILE_PATH, 'rb') as f:
            # 移动到文件末尾获取当前大小
            f.seek(0, io.SEEK_END)
            current_size = f.tell()

            # 检查文件是否变小（可能被截断或替换）
            if current_size < last_log_pos:
                print("日志文件似乎已重置，从头开始读取。")
                log_lines_deque.clear()
                last_log_pos = 0

            # 移动到上次读取的位置
            f.seek(last_log_pos)
            # 读取新内容
            new_bytes = f.read()
            # 更新上次读取的位置
            last_log_pos = f.tell()

        if new_bytes:
            # 解码新内容并按行分割
            # 使用 errors='ignore' 处理可能的解码错误
            new_content = new_bytes.decode('utf-8', errors='ignore')
            # 使用 splitlines() 而不是 split('\n') 来正确处理不同的换行符
            new_lines = new_content.splitlines(keepends=True) # 保留换行符以便正确显示
            if new_lines:
                 # 如果第一行不完整（因为上次读取可能在行中间结束），尝试与 deque 的最后一行合并
                 # 检查 deque 是否为空，以及最后一行是否以换行符结束
                 if log_lines_deque and not log_lines_deque[-1].endswith(('\n', '\r')):
                     log_lines_deque[-1] += new_lines[0]
                     new_lines = new_lines[1:] # 处理剩余的新行

                 log_lines_deque.extend(new_lines) # 添加新行，deque 会自动处理长度限制

        # 返回 deque 中的所有行，反转顺序，最新的在顶部
        return "".join(reversed(log_lines_deque))

    except FileNotFoundError:
        # 文件可能在检查后、打开前被删除
        if last_log_pos > 0 or len(log_lines_deque) > 0:
            log_lines_deque.clear()
            last_log_pos = 0
            print("日志文件读取时未找到，已清空显示。")
        return f"错误：日志文件未找到于 {LOG_FILE_PATH}"
    except Exception as e:
        print(f"读取日志文件时出错: {e}") # 打印错误到控制台
        # 返回当前 deque 内容加上错误信息
        return "".join(log_lines_deque) + f"\n\n--- 读取日志时出错: {e} ---"

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

    if not json_file:
        print(f"[{execution_id}] 错误: 未选择工作流 JSON 文件。")
        return None

    json_path = os.path.join(OUTPUT_DIR, json_file)
    if not os.path.exists(json_path):
        print(f"[{execution_id}] 错误: 工作流 JSON 文件不存在: {json_path}")
        return None

    try:
        with open(json_path, "r", encoding="utf-8") as file_json:
            prompt = json.load(file_json)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[{execution_id}] 读取或解析 JSON 文件时出错 ({json_path}): {e}")
        return None

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
                 # return None # 如果图生图节点必须有输入

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

    if hua_output_key:
        prompt[hua_output_key]["inputs"]["unique_id"] = execution_id
        print(f"[{execution_id}] 已将 unique_id 设置给节点 {hua_output_key}")
    else:
        print(f"[{execution_id}] 警告: 未找到 '🌙图像输出到gradio前端' 节点，可能无法获取结果。")
        # return None # 如果必须有输出节点才能工作，则返回失败

    # --- 发送请求并等待结果 ---
    try:
        print(f"[{execution_id}] 调用 start_queue 发送请求...")
        success = start_queue(prompt) # 发送请求到 ComfyUI
        if not success:
             print(f"[{execution_id}] 请求发送失败。")
             return None
        print(f"[{execution_id}] 请求已发送，开始等待结果...")
    except Exception as e:
        print(f"[{execution_id}] 调用 start_queue 时发生意外错误: {e}")
        return None

    # --- 精确图像获取逻辑 ---
    temp_file_path = os.path.join(TEMP_DIR, f"{execution_id}.json")
    print(f"[{execution_id}] 开始等待临时文件: {temp_file_path}")

    start_time = time.time()
    wait_timeout = 1000
    check_interval = 1

    while time.time() - start_time < wait_timeout:
        if os.path.exists(temp_file_path):
            print(f"[{execution_id}] 检测到临时文件 (耗时: {time.time() - start_time:.1f}秒)")
            try:
                time.sleep(0.5) # 确保写入完成
                with open(temp_file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if not content: # 文件可能是空的
                        print(f"[{execution_id}] 警告: 临时文件为空。")
                        time.sleep(check_interval) # 再等一下
                        continue
                    image_paths = json.loads(content) # 解析 JSON
                print(f"[{execution_id}] 成功读取 {len(image_paths)} 个图片路径。")

                try:
                    os.remove(temp_file_path)
                    print(f"[{execution_id}] 已删除临时文件。")
                except OSError as e:
                    print(f"[{execution_id}] 删除临时文件失败: {e}")

                # 返回绝对路径
                valid_paths = [os.path.abspath(p) for p in image_paths if os.path.exists(p)]
                if len(valid_paths) != len(image_paths):
                    print(f"[{execution_id}] 警告: 部分路径无效。有效路径数: {len(valid_paths)} / {len(image_paths)}")

                if not valid_paths:
                    print(f"[{execution_id}] 错误: 未找到有效的输出图片路径。")
                    return None

                print(f"[{execution_id}] 任务成功完成，返回 {len(valid_paths)} 个有效路径。")
                return valid_paths # *** 成功时返回路径列表 ***

            except json.JSONDecodeError as e:
                print(f"[{execution_id}] 读取或解析临时文件 JSON 失败: {e}. 文件内容: '{content[:100]}...'") # 打印部分内容帮助调试
                # 不要立即删除，可能只是写入未完成
                # try: os.remove(temp_file_path)
                # except OSError: pass
                # return None # 解析失败，暂时不返回失败，再等等
                time.sleep(check_interval * 2) # 等待更长时间再试
            except Exception as e:
                print(f"[{execution_id}] 处理临时文件时发生未知错误: {e}")
                try: os.remove(temp_file_path)
                except OSError: pass
                return None # 其他错误，返回 None

        time.sleep(check_interval)

    # 超时处理
    print(f"[{execution_id}] 等待临时文件超时 ({wait_timeout}秒)。")
    return None # 超时，返回 None


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
        return (gr.update(visible=False),) * 10

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

# --- 队列处理函数 ---
def run_queued_tasks(inputimage1, prompt_text_positive, prompt_text_positive_2, prompt_text_positive_3, prompt_text_positive_4, prompt_text_negative, json_file, hua_width, hua_height, hua_lora, hua_checkpoint, hua_unet, queue_count=1, progress=gr.Progress(track_tqdm=True)):
    global accumulated_results # 声明我们要修改全局变量

    # 初始化当前批次结果
    current_batch_results = []

    # 1. 将新任务加入队列 (根据queue_count添加多个相同任务)
    # 如果是批量任务(queue_count>1)，先清除之前的结果
    if queue_count > 1:
        with results_lock:
            accumulated_results = []
            current_batch_results = []  # 重置当前批次结果
    task_params = (inputimage1, prompt_text_positive, prompt_text_positive_2, prompt_text_positive_3, prompt_text_positive_4, prompt_text_negative, json_file, hua_width, hua_height, hua_lora, hua_checkpoint, hua_unet)
    print(f"[QUEUE_DEBUG] 接收到新任务请求。当前队列长度 (加锁前): {len(task_queue)}")
    with queue_lock:
        for _ in range(max(1, int(queue_count))):  # 确保至少添加1个任务
            task_queue.append(task_params)
        current_queue_size = len(task_queue)
        print(f"[QUEUE_DEBUG] 已添加 {queue_count} 个任务到队列。当前队列长度 (加锁后): {current_queue_size}")
    print(f"[QUEUE_DEBUG] 任务添加完成，释放锁。")

    # 初始状态更新：显示当前累积结果和队列信息
    with results_lock:
        # 使用副本以防在 yield 时被修改
        current_results_copy = accumulated_results[:]
    print(f"[QUEUE_DEBUG] 准备 yield 初始状态更新。队列: {current_queue_size}, 处理中: {processing_event.is_set()}")
    yield {
        queue_status_display: gr.update(value=f"队列中: {current_queue_size} | 处理中: {'是' if processing_event.is_set() else '否'}"),
        output_gallery: gr.update(value=current_results_copy)
    }
    print(f"[QUEUE_DEBUG] 已 yield 初始状态更新。")

    # 2. 检查是否已有进程在处理队列
    print(f"[QUEUE_DEBUG] 检查处理状态: processing_event.is_set() = {processing_event.is_set()}")
    if processing_event.is_set():
        print("[QUEUE_DEBUG] 已有任务在处理队列，新任务已排队。函数返回。")
        # 不需要 return，让 yield 完成更新即可
        return

    # 3. 开始处理队列 (如果没有其他进程在处理)
    print(f"[QUEUE_DEBUG] 没有任务在处理，准备设置 processing_event 为 True。")
    processing_event.set() # 标记为正在处理
    print(f"[QUEUE_DEBUG] processing_event 已设置为 True。开始处理循环。")

    try:
        print("[QUEUE_DEBUG] Entering main processing loop (while True).")
        while True:
            task_to_run = None
            current_queue_size = 0 # Initialize
            print("[QUEUE_DEBUG] Checking queue for tasks (acquiring lock)...")
            with queue_lock:
                if task_queue:
                    task_to_run = task_queue.popleft()
                    current_queue_size = len(task_queue)
                    print(f"[QUEUE_DEBUG] Task popped from queue. Remaining: {current_queue_size}")
                else:
                    print("[QUEUE_DEBUG] Queue is empty. Breaking loop.")
                    break # 队列空了
            print("[QUEUE_DEBUG] Queue lock released.")

            # 如果队列空了，上面的 break 会执行，不会到这里
            if not task_to_run: # Double check in case break didn't happen? Should not be needed.
                 print("[QUEUE_DEBUG] Warning: No task found after lock release, but loop didn't break?")
                 continue # Skip to next iteration

            # 更新状态：显示正在处理和队列大小
            with results_lock: current_results_copy = accumulated_results[:]
            print(f"[QUEUE_DEBUG] Preparing to yield 'Processing' status. Queue: {current_queue_size}")
            yield {
                queue_status_display: gr.update(value=f"队列中: {current_queue_size} | 处理中: 是"),
                output_gallery: gr.update(value=current_results_copy)
            }
            print(f"[QUEUE_DEBUG] Yielded 'Processing' status.")

            if task_to_run: # This check is now redundant due to the earlier check, but keep for clarity
                print(f"[QUEUE_DEBUG] Starting execution for popped task. Remaining queue: {current_queue_size}")
                # --- 进度条开始 ---
                progress(0, desc=f"处理任务 (队列剩余 {current_queue_size})") # 取消注释并设置描述
                print(f"[QUEUE_DEBUG] Progress set to 0. Desc: Processing task (Queue remaining {current_queue_size})")
                # --- 进度条开始结束 ---
                print(f"[QUEUE_DEBUG] Calling generate_image...")
                new_image_paths = None # Initialize
                try:
                    new_image_paths = generate_image(*task_to_run) # 执行任务
                    print(f"[QUEUE_DEBUG] generate_image returned. Result: {'Success (paths received)' if new_image_paths else 'Failure (None received)'}")
                except Exception as e:
                    print(f"[QUEUE_DEBUG] Exception during generate_image call: {e}")
                    # Consider how to handle this - maybe yield a failure status?

                # --- 进度条结束 ---
                progress(1) # 无论成功失败，都标记完成
                print(f"[QUEUE_DEBUG] Progress set to 1.")
                # --- 进度条结束结束 ---

                if new_image_paths:
                    print(f"[QUEUE_DEBUG] Task successful, got {len(new_image_paths)} new image paths.")
                    with results_lock:
                        if queue_count == 1:
                            # 单任务模式：只显示当前结果，不累积
                            accumulated_results = new_image_paths
                        else:
                            # 批量任务模式：累积当前批次的所有结果
                            current_batch_results.extend(new_image_paths)
                            accumulated_results = current_batch_results[:]

                        current_results_copy = accumulated_results[:] # 获取更新后的副本
                        print(f"[QUEUE_DEBUG] Updated accumulated_results (lock acquired). Queue count: {queue_count}. Current batch: {len(current_batch_results)}. Total: {len(accumulated_results)}")
                    print(f"[QUEUE_DEBUG] Preparing to yield success update. Queue: {current_queue_size}")
                    # 更新 UI
                    yield {
                         queue_status_display: gr.update(value=f"队列中: {current_queue_size} | 处理中: 是 (完成)"),
                         output_gallery: gr.update(value=current_results_copy, visible=True)  # 强制更新并显示
                    }
                    print(f"[QUEUE_DEBUG] Yielded success update.")
                else:
                    print("[QUEUE_DEBUG] Task failed or returned no images.")
                    with results_lock: current_results_copy = accumulated_results[:] # Get current results even on failure
                    print(f"[QUEUE_DEBUG] Preparing to yield failure update. Queue: {current_queue_size}")
                    yield {
                         queue_status_display: gr.update(value=f"队列中: {current_queue_size} | 处理中: 是 (失败)"),
                         output_gallery: gr.update(value=current_results_copy), # Show existing results
                    }
                    print(f"[QUEUE_DEBUG] Yielded failure update.")
            # else: # 理论上不应发生, 因为前面有检查
            #      print("[QUEUE_DEBUG] Warning: task_to_run was unexpectedly None here.")

    finally:
        print(f"[QUEUE_DEBUG] Entering finally block. Clearing processing_event (was {processing_event.is_set()}).")
        processing_event.clear() # 清除处理标志
        print(f"[QUEUE_DEBUG] processing_event cleared (is now {processing_event.is_set()}).")
        with queue_lock: current_queue_size = len(task_queue)
        with results_lock: final_results = accumulated_results[:]
        print(f"[QUEUE_DEBUG] Preparing to yield final status update. Queue: {current_queue_size}, Processing: No")
        yield {
            queue_status_display: gr.update(value=f"队列中: {current_queue_size} | 处理中: 否"),
            output_gallery: gr.update(value=final_results)
        }
        print("[QUEUE_DEBUG] Yielded final status update. Exiting run_queued_tasks.")

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
    print("任务队列已清除。")
    return gr.update(value=f"队列中: {current_queue_size} | 处理中: {'是' if processing_event.is_set() else '否'}")

def clear_history():
    global accumulated_results
    with results_lock:
        accumulated_results.clear()
    print("图像历史已清除。")
    with queue_lock: current_queue_size = len(task_queue)
    return {
        output_gallery: gr.update(value=[]),
        queue_status_display: gr.update(value=f"队列中: {current_queue_size} | 处理中: {'是' if processing_event.is_set() else '否'}")
    }


# --- Gradio 界面 ---
with gr.Blocks() as demo:
    gr.Markdown("# [封装comfyUI工作流](https://github.com/kungful/ComfyUI_to_webui.git)")

    with gr.Row():
       with gr.Column():  # 左侧列
           with gr.Accordion("预览所有输出图片 (点击加载)", open=False):
               output_preview_gallery = gr.Gallery(label="输出图片预览", columns=4, height="auto", preview=True, object_fit="contain")
               load_output_button = gr.Button("加载输出图片")
               
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
                   flip_btn = gr.Button("↔ 切换宽高")
               with gr.Accordion("宽度和高度设置", open=False):
                   with gr.Column(scale=1):
                       hua_width = gr.Number(label="宽度", value=512, minimum=64, step=64, elem_id="hua_width_input")
                       hua_height = gr.Number(label="高度", value=512, minimum=64, step=64, elem_id="hua_height_input")
                       ratio_display = gr.Markdown("当前比例: 1:1")

           with gr.Row():
               with gr.Column(scale=3):
                   json_dropdown = gr.Dropdown(choices=get_json_files(), label="选择工作流")
               with gr.Column(scale=1): # 调整比例使按钮不至于太宽
                   refresh_button = gr.Button("🔄 刷新工作流")

           with gr.Row():
               with gr.Column(scale=1):
                   hua_lora_dropdown = gr.Dropdown(choices=lora_list, label="选择 Lora 模型", value="None", elem_id="hua_lora_dropdown")
               with gr.Column(scale=1):
                   hua_checkpoint_dropdown = gr.Dropdown(choices=checkpoint_list, label="选择 Checkpoint 模型", value="None", elem_id="hua_checkpoint_dropdown")
               with gr.Column(scale=1):
                   hua_unet_dropdown = gr.Dropdown(choices=unet_list, label="选择 UNet 模型", value="None", elem_id="hua_unet_dropdown")

           Random_Seed = gr.HTML("""
           <div style='text-align: center; margin-bottom: 5px;'>
               <h2 style="font-size: 12px; margin: 0; color: #00ff00; font-style: italic;">
                   已添加gradio随机种节点
               </h2>
           </div>
           """, visible=False) # 初始隐藏，由 check_seed_node 控制

           # --- 添加队列控制按钮 ---
           with gr.Row():
                queue_count = gr.Number(label="队列数量", value=1, minimum=1, step=1, precision=0)
                with gr.Column(scale=1):
                    run_button = gr.Button("🚀 开始跑图 (加入队列)", variant="primary")

                with gr.Column(scale=1):
                    clear_queue_button = gr.Button("🧹 清除队列")
                    queue_status_display = gr.Markdown("队列中: 0 | 处理中: 否")



       with gr.Column(): # 右侧列

           with gr.Row():
               output_gallery = gr.Gallery(label="生成结果 (队列累计)", columns=3, height=600, preview=True, object_fit="contain")
                       # --- 添加实时日志显示区域 ---
           with gr.Accordion("实时 ComfyUI 日志 (轮询)", open=True, elem_id="comfyui_log_accordion"):
               log_display = gr.HTML(
                   value="""
                   <div id='log-container' style='height:250px; border:1px solid #00ff2f; overflow-y:auto; padding:10px; background:#000;'>
                       <pre id='log-content' style='margin:0; white-space:pre-wrap; font-size:12px; line-height:1.2; color:#00ff2f; font-family:monospace;'>日志内容将在此处更新...</pre>
                   </div>
                   <script>
                       // Function to scroll the log container
                       function scrollLogToEnd() {
                           const container = document.querySelector('#comfyui_log_display #log-container');
                           if (container) {
                               setTimeout(() => {
                                   container.scrollTop = container.scrollHeight;
                               }, 50); // Delay to allow rendering
                           }
                       }
                       // Initialize with scroll to bottom
                       scrollLogToEnd();
                   </script>
                   """,
                   elem_id="comfyui_log_display" # Give the HTML component an ID
               )
               with gr.Row():
                   start_log_button = gr.Button("开始监控日志")
                   stop_log_button = gr.Button("停止监控日志")
               # Timer 定义在 Blocks 内部，初始 inactive
               log_timer = gr.Timer(1, active=True) # 每 1 秒触发一次，初始激活

           with gr.Row():
               clear_history_button = gr.Button("🗑️ 清除显示历史")
               gr.Markdown('我要打十个') # 保留这句骚话

           # --- 添加赞助按钮和显示区域 ---
           with gr.Row(): # 将按钮放在一行，居中效果可能更好
                gr.Markdown() # 左侧占位
                sponsor_button = gr.Button("💖 赞助作者")
                gr.Markdown() # 右侧占位
           sponsor_display = gr.Markdown(visible=False) # 初始隐藏



    # --- 事件处理 ---
    resolution_dropdown.change(fn=update_from_preset, inputs=resolution_dropdown, outputs=[resolution_dropdown, hua_width, hua_height, ratio_display])
    hua_width.change(fn=update_from_inputs, inputs=[hua_width, hua_height], outputs=[resolution_dropdown, ratio_display])
    hua_height.change(fn=update_from_inputs, inputs=[hua_width, hua_height], outputs=[resolution_dropdown, ratio_display])
    flip_btn.click(fn=flip_resolution, inputs=[hua_width, hua_height], outputs=[hua_width, hua_height])

    # JSON 下拉菜单改变时，更新所有相关组件的可见性 + 随机种子指示器
    json_dropdown.change(
        lambda x: (*fuck(x), check_seed_node(x)), # fuck 返回 10 个, check_seed_node 返回 1 个
        inputs=json_dropdown,
        outputs=[ # 必须严格对应 11 个组件
            image_accordion,
            prompt_positive,      # Textbox
            prompt_positive_2,    # Textbox
            prompt_positive_3,    # Textbox
            prompt_positive_4,    # Textbox
            negative_prompt_col,  # Column (包含 Textbox)
            resolution_row,       # Row (包含 Dropdown, Button, Accordion)
            hua_lora_dropdown,    # Dropdown
            hua_checkpoint_dropdown, # Dropdown
            hua_unet_dropdown,    # Dropdown
            Random_Seed           # HTML
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
        outputs=[queue_status_display, output_gallery]
    )

    # --- 添加新按钮的点击事件 ---
    clear_queue_button.click(fn=clear_queue, inputs=[], outputs=[queue_status_display])
    clear_history_button.click(fn=clear_history, inputs=[], outputs=[output_gallery, queue_status_display])
    sponsor_button.click(fn=show_sponsor_code, inputs=[], outputs=[sponsor_display]) # 绑定赞助按钮事件

    # --- 日志监控事件处理 ---
    # Timer 触发时调用日志读取函数更新日志显示 (只返回 HTML 内容)
    def update_log_display_html():
        log_content = read_new_log_entries() # 最新的在顶部
        return f"""
        <div id='log-container' style='max-height:250px; border:1px solid #ccc; overflow-y:auto; padding:10px; background:#000;'>
            <pre id='log-content' style='margin:0; white-space:pre-wrap;color:#00ff00'>{log_content}</pre>
        </div>
        """ # 确保没有 script 块

    log_timer.tick(update_log_display_html, None, log_display) # 更新 HTML 组件

    # 点击 "开始监控" 按钮激活 Timer
    def start_log_monitoring():
        # 只返回 Timer 更新和初始 HTML 内容
        initial_log_content = read_new_log_entries() # 获取反转后的初始日志
        return (
            gr.Timer(active=True),
            f"""
            <div id='log-container' style='max-height:250px; border:1px solid #ccc; overflow-y:auto; padding:10px; background:#000;'>
                <pre id='log-content' style='margin:0; white-space:pre-wrap;color:#00ff00'>{initial_log_content}</pre>
            </div>
            """ # 确保没有 script 块
        )

    start_log_button.click(
        start_log_monitoring,
        inputs=None,
        outputs=[log_timer, log_display] # 更新 Timer 和 HTML 组件
    )

    # 点击 "停止监控" 按钮禁用 Timer
    stop_log_button.click(lambda: gr.Timer(active=False), None, log_timer)

    # --- 初始加载 ---
    def on_load_setup():
        json_files = get_json_files()
        updates = []
        if not json_files:
            print("未找到 JSON 文件，隐藏所有动态组件")
            # 返回 11 个 False 更新
            updates = [gr.update(visible=False)] * 11
        else:
            default_json = json_files[0]
            print(f"初始加载，检查默认 JSON: {default_json}")
            fuck_results = fuck(default_json) # 10 个更新
            seed_result = check_seed_node(default_json) # 1 个更新
            updates = list(fuck_results) + [seed_result] # 组合成 11 个

        # 确保返回 11 个更新对象
        if len(updates) != 11:
             print(f"警告: on_load_setup 返回了 {len(updates)} 个更新，需要 11 个。补充默认值。")
             # 补充或截断以匹配输出数量
             default_update = gr.update(visible=False) # 或其他合适的默认值
             updates = (updates + [default_update] * 11)[:11]

        # 返回初始日志内容
        initial_log_content = read_new_log_entries()

        # 返回所有更新，包括日志显示框的初始内容 (仅 HTML)
        initial_log_html = f"""
        <div id='log-container' style='max-height:250px; border:1px solid #ccc; overflow-y:auto; padding:10px; background:#000;'>
            <pre id='log-content' style='margin:0; white-space:pre-wrap;color:#00ff00'>{initial_log_content}</pre>
        </div>
        """ # 确保没有 script 块
        return tuple(updates) + (initial_log_html,) # 11 + 1 = 12 个输出

    demo.load(
        fn=lambda: (*on_load_setup(), gr.Timer(active=True)),
        inputs=[],
        outputs=[ # 11 dynamic components + log_display + log_timer
            image_accordion, prompt_positive, prompt_positive_2, prompt_positive_3, prompt_positive_4,
            negative_prompt_col, resolution_row, hua_lora_dropdown, hua_checkpoint_dropdown,
            hua_unet_dropdown, Random_Seed,
            log_display,
            log_timer
        ]
    )

# --- Gradio 启动代码 ---
def luanch_gradio(demo_instance): # 接收 demo 实例
    try:
        # 尝试查找可用端口，从 7860 开始
        port = 7860
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
                        print("无法找到可用端口 (7860-7870)。")
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
