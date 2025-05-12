import os
import json
import glob
from math import gcd
import gradio as gr

# --- Resolution and Preset Helper Functions ---

def calculate_aspect_ratio(width, height):
    if width is None or height is None or width <= 0 or height <= 0:
        return "0:0"
    try:
        w, h = int(width), int(height)
        common_divisor = gcd(w, h)
        return f"{w//common_divisor}:{h//common_divisor}"
    except (ValueError, TypeError):
        return "无效输入"

def strip_prefix(resolution_str, resolution_prefixes_list):
    """Removes known prefixes from the resolution string."""
    for prefix in resolution_prefixes_list:
        if resolution_str.startswith(prefix):
            return resolution_str[len(prefix):]
    return resolution_str # Return original if no prefix matches

def parse_resolution(resolution_str, resolution_prefixes_list):
    if resolution_str == "custom":
        return None, None, "自定义", "custom"
    try:
        cleaned_str = strip_prefix(resolution_str, resolution_prefixes_list)
        parts = cleaned_str.split("|")
        if len(parts) != 2: return None, None, "无效格式", resolution_str
        width, height = map(int, parts[0].split("x"))
        ratio = parts[1]
        return width, height, ratio, resolution_str
    except ValueError:
        return None, None, "无效格式", resolution_str

def load_resolution_presets_from_files(relative_filepaths, prefixes, script_dir):
    """Loads resolution presets from multiple files, adding a prefix to each."""
    presets = set()
    if len(relative_filepaths) != len(prefixes):
        print("Error: Number of filepaths and prefixes must match.")
        return ["512x512|1:1", "1024x1024|1:1", "custom"] # Fallback

    for i, relative_path in enumerate(relative_filepaths):
        prefix = prefixes[i]
        full_path = os.path.join(script_dir, relative_path)
        print(f"Attempting to load resolutions from: {full_path} with prefix '{prefix}'")
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    try:
                        if '×' in line:
                            width_str, height_str = line.split('×')
                        elif 'x' in line:
                            width_str, height_str = line.split('x')
                        else:
                            print(f"Skipping line with unknown separator in '{relative_path}': '{line}'")
                            continue
                        width = int(width_str)
                        height = int(height_str)
                        ratio = calculate_aspect_ratio(width, height)
                        presets.add(f"{prefix}{width}x{height}|{ratio}")
                    except ValueError as e:
                        print(f"Skipping invalid number format in resolution file '{relative_path}': '{line}' - Error: {e}")
                        continue
            print(f"Loaded {len(presets)} unique resolutions so far after processing '{relative_path}'.")
        except FileNotFoundError:
            print(f"Warning: Resolution file not found at '{full_path}'. Skipping.")
            continue
        except Exception as e:
            print(f"Warning: Error reading resolution file '{full_path}': {e}. Skipping.")
            continue

    sorted_presets = sorted(list(presets))
    sorted_presets.append("custom")
    if not sorted_presets or len(sorted_presets) == 1:
        print("Error: No valid resolution presets loaded from any file. Using default.")
        return ["512x512|1:1", "1024x1024|1:1", "custom"]
    return sorted_presets

def find_closest_preset(width, height, current_resolution_presets, resolution_prefixes_list):
    if width is None or height is None or width <= 0 or height <= 0:
        return "custom"
    try:
        w, h = int(width), int(height)
    except (ValueError, TypeError):
        return "custom"

    target_aspect = calculate_aspect_ratio(w, h)
    best_match = "custom"
    min_diff = float('inf')

    for preset_str_with_prefix in current_resolution_presets:
        if preset_str_with_prefix == "custom": continue
        preset_width, preset_height, preset_aspect, _ = parse_resolution(preset_str_with_prefix, resolution_prefixes_list)
        if preset_width is None: continue

        if preset_width == w and preset_height == h:
            return preset_str_with_prefix

        if preset_aspect == target_aspect:
            area_diff = abs((preset_width * preset_height) - (w * h))
            if area_diff < min_diff:
                min_diff = area_diff
                best_match = preset_str_with_prefix
    
    if best_match != "custom":
        return best_match
    return "custom"

# --- File and Workflow Helper Functions ---

def get_output_images(output_dir_path):
    image_files = []
    supported_formats = ['*.png', '*.jpg', '*.jpeg', '*.gif', '*.webp', '*.bmp']
    if not os.path.exists(output_dir_path):
        print(f"警告: 输出目录 {output_dir_path} 不存在。")
        return []
    try:
        for fmt in supported_formats:
            pattern = os.path.join(output_dir_path, fmt)
            image_files.extend(glob.glob(pattern))
        image_files.sort(key=os.path.getmtime, reverse=True)
        print(f"在 {output_dir_path} 中找到 {len(image_files)} 张图片。")
        return [os.path.abspath(f) for f in image_files]
    except Exception as e:
        print(f"扫描输出目录时出错: {e}")
        return []

def find_key_by_class_type_internal(p, class_type):
    """Finds the first key (node ID) matching the given class_type."""
    for k, v in p.items():
        if isinstance(v, dict) and v.get("class_type") == class_type:
            return k
    return None

def find_all_nodes_by_class_type(prompt_workflow, class_type):
    """Finds all nodes matching the given class_type and returns their info."""
    found_nodes = []
    if not isinstance(prompt_workflow, dict):
        return found_nodes
        
    for node_id, node_data in prompt_workflow.items():
        if isinstance(node_data, dict) and node_data.get("class_type") == class_type:
            title = node_id # Default title to node_id
            if "_meta" in node_data and isinstance(node_data["_meta"], dict) and "title" in node_data["_meta"]:
                title = node_data["_meta"]["title"]
            
            node_info = {
                "id": node_id,
                "inputs": node_data.get("inputs", {}), # The 'inputs' field of the node
                "title": title
            }
            found_nodes.append(node_info)
    return found_nodes

# Deprecated: The 'fuck' function's logic is being integrated into get_workflow_defaults_and_visibility
# def fuck(json_file, output_dir_path): ...

def get_workflow_defaults_and_visibility(json_file, output_dir_path, current_resolution_prefixes, current_resolution_presets, max_dynamic_components=5):
    # max_dynamic_components is not used yet, but planned for future user setting
    defaults = {
        "visible_image_input": False, 
        "visible_video_input": False,
        "visible_neg_prompt": False, 
        "default_neg_prompt": "",
        "visible_resolution": False,
        "default_width": 512, 
        "default_height": 512,
        "visible_checkpoint": False, 
        "default_checkpoint": "None",
        "visible_unet": False, 
        "default_unet": "None",
        "visible_seed_indicator": False, 
        "visible_image_output": False, 
        "visible_video_output": False,
        "dynamic_components": {
            "GradioTextOk": [],
            "Hua_LoraLoaderModelOnly": [],
            "HuaIntNode": [],
            "HuaFloatNode": []
        }
    }

    if not json_file or not os.path.exists(os.path.join(output_dir_path, json_file)):
        print(f"JSON 文件无效或不存在: {json_file}")
        return defaults

    json_path = os.path.join(output_dir_path, json_file)
    try:
        with open(json_path, "r", encoding="utf-8") as file_json:
            prompt = json.load(file_json)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"读取或解析 JSON 文件时出错 ({json_file}): {e}")
        return defaults

    # --- Handle Single Instance Components ---
    defaults["visible_image_input"] = find_key_by_class_type_internal(prompt, "GradioInputImage") is not None
    defaults["visible_video_input"] = find_key_by_class_type_internal(prompt, "VHS_LoadVideo") is not None
    
    neg_prompt_key = find_key_by_class_type_internal(prompt, "GradioTextBad")
    if neg_prompt_key and neg_prompt_key in prompt and "inputs" in prompt[neg_prompt_key]:
        defaults["visible_neg_prompt"] = True
        defaults["default_neg_prompt"] = prompt[neg_prompt_key]["inputs"].get("string", "")
    
    resolution_key = find_key_by_class_type_internal(prompt, "Hua_gradio_resolution")
    if resolution_key and resolution_key in prompt and "inputs" in prompt[resolution_key]:
        defaults["visible_resolution"] = True
        try: defaults["default_width"] = int(prompt[resolution_key]["inputs"].get("custom_width", 512))
        except (ValueError, TypeError): pass
        try: defaults["default_height"] = int(prompt[resolution_key]["inputs"].get("custom_height", 512))
        except (ValueError, TypeError): pass
        
    checkpoint_key = find_key_by_class_type_internal(prompt, "Hua_CheckpointLoaderSimple")
    if checkpoint_key and checkpoint_key in prompt and "inputs" in prompt[checkpoint_key]:
        defaults["visible_checkpoint"] = True
        defaults["default_checkpoint"] = prompt[checkpoint_key]["inputs"].get("ckpt_name", "None")

    unet_key = find_key_by_class_type_internal(prompt, "Hua_UNETLoader") # Assuming this is the correct class name
    if unet_key and unet_key in prompt and "inputs" in prompt[unet_key]:
        defaults["visible_unet"] = True
        defaults["default_unet"] = prompt[unet_key]["inputs"].get("unet_name", "None")

    defaults["visible_seed_indicator"] = find_key_by_class_type_internal(prompt, "Hua_gradio_Seed") is not None
    defaults["visible_image_output"] = find_key_by_class_type_internal(prompt, "Hua_Output") is not None
    defaults["visible_video_output"] = find_key_by_class_type_internal(prompt, "Hua_Video_Output") is not None

    # --- Handle Dynamic Components ---
    # GradioTextOk (Positive Prompts)
    gradio_text_nodes = find_all_nodes_by_class_type(prompt, "GradioTextOk")
    for node_info in gradio_text_nodes:
        defaults["dynamic_components"]["GradioTextOk"].append({
            "id": node_info["id"],
            "value": node_info["inputs"].get("string", ""),
            "title": node_info["title"]
        })

    # Hua_LoraLoaderModelOnly (Lora Loaders)
    lora_nodes = find_all_nodes_by_class_type(prompt, "Hua_LoraLoaderModelOnly")
    for node_info in lora_nodes:
        defaults["dynamic_components"]["Hua_LoraLoaderModelOnly"].append({
            "id": node_info["id"],
            "value": node_info["inputs"].get("lora_name", "None"),
            "title": node_info["title"]
        })

    # HuaIntNode
    int_nodes = find_all_nodes_by_class_type(prompt, "HuaIntNode")
    for node_info in int_nodes:
        default_val = 0
        try:
            default_val = int(node_info["inputs"].get("int_value", 0))
        except (ValueError, TypeError):
            pass
        defaults["dynamic_components"]["HuaIntNode"].append({
            "id": node_info["id"],
            "value": default_val,
            "name_from_node": node_info["inputs"].get("name", f"IntInput_{node_info['id']}"), # 'name' field from node's inputs
            "title": node_info["title"]
        })

    # HuaFloatNode
    float_nodes = find_all_nodes_by_class_type(prompt, "HuaFloatNode")
    for node_info in float_nodes:
        default_val = 0.0
        try:
            default_val = float(node_info["inputs"].get("float_value", 0.0))
        except (ValueError, TypeError):
            pass
        defaults["dynamic_components"]["HuaFloatNode"].append({
            "id": node_info["id"],
            "value": default_val,
            "name_from_node": node_info["inputs"].get("name", f"FloatInput_{node_info['id']}"), # 'name' field from node's inputs
            "title": node_info["title"]
        })
    
    # Limit the number of dynamic components to max_dynamic_components if needed (for future use)
    # for comp_type in defaults["dynamic_components"]:
    #     defaults["dynamic_components"][comp_type] = defaults["dynamic_components"][comp_type][:max_dynamic_components]

    print(f"Workflow defaults and visibility for {json_file}: {json.dumps(defaults, indent=2, ensure_ascii=False)}")
    return defaults

# --- Plugin Settings Management ---
# 这些设置函数假定 settings 文件位于此插件的根目录 (ComfyUI_to_webui)

PLUGIN_SETTINGS_FILE = "plugin_settings.json" 
DEFAULT_MAX_DYNAMIC_COMPONENTS = 5

def _get_settings_file_path():
    """Internal helper to get the absolute path to the settings file."""
    # __file__ in ui_def.py is .../ComfyUI_to_webui/kelnel_ui/ui_def.py
    # os.path.dirname(__file__) is .../ComfyUI_to_webui/kelnel_ui/
    # os.path.dirname(os.path.dirname(__file__)) is .../ComfyUI_to_webui/
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), PLUGIN_SETTINGS_FILE)

def load_plugin_settings():
    """Loads plugin settings, primarily the max dynamic components.
    The settings file is expected to be in the main plugin directory."""
    settings_file_path = _get_settings_file_path()
    try:
        if os.path.exists(settings_file_path):
            with open(settings_file_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
                if not isinstance(settings.get("max_dynamic_components"), int):
                    print(f"警告: '{settings_file_path}' 中的 'max_dynamic_components' 缺失或类型不正确。将使用默认值 ({DEFAULT_MAX_DYNAMIC_COMPONENTS}) 并更新文件。")
                    settings["max_dynamic_components"] = DEFAULT_MAX_DYNAMIC_COMPONENTS
                    save_plugin_settings(settings) # 保存修正后的设置
                return settings
        else:
            print(f"提示: 插件配置文件 '{settings_file_path}' 未找到。将创建并使用默认设置。")
            default_settings = {"max_dynamic_components": DEFAULT_MAX_DYNAMIC_COMPONENTS}
            save_plugin_settings(default_settings)
            return default_settings
    except Exception as e:
        print(f"错误: 加载插件设置 '{settings_file_path}' 时发生错误: {e}. 将使用默认设置。")
        return {"max_dynamic_components": DEFAULT_MAX_DYNAMIC_COMPONENTS}

def save_plugin_settings(settings_dict):
    """Saves plugin settings to the main plugin directory."""
    settings_file_path = _get_settings_file_path()
    try:
        with open(settings_file_path, "w", encoding="utf-8") as f:
            json.dump(settings_dict, f, indent=4, ensure_ascii=False)
        print(f"信息: 插件设置已成功保存到 '{settings_file_path}'。")
        return "设置已保存。"
    except Exception as e:
        print(f"错误: 保存插件设置到 '{settings_file_path}' 时发生错误: {e}")
        return f"保存设置失败: {e}"
# --- End Plugin Settings Management ---
