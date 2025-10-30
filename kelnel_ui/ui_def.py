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
        return "Invalid input"

def strip_prefix(resolution_str, resolution_prefixes_list):
    """Removes known prefixes from the resolution string."""
    for prefix in resolution_prefixes_list:
        if resolution_str.startswith(prefix):
            return resolution_str[len(prefix):]
    return resolution_str # Return original if no prefix matches

def parse_resolution(resolution_str, resolution_prefixes_list):
    if resolution_str == "custom":
        return None, None, "Custom", "custom"
    try:
        cleaned_str = strip_prefix(resolution_str, resolution_prefixes_list)
        parts = cleaned_str.split("|")
        if len(parts) != 2: return None, None, "Invalid format", resolution_str
        width, height = map(int, parts[0].split("x"))
        ratio = parts[1]
        return width, height, ratio, resolution_str
    except ValueError:
        return None, None, "Invalid format", resolution_str

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
                    if not line:
                        continue
                    line = line.replace("\u00d7", "x")
                    try:
                        if 'x' in line:
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
        print(f"Warning: output directory {output_dir_path} does not exist.")
        return []
    try:
        for fmt in supported_formats:
            pattern = os.path.join(output_dir_path, fmt)
            image_files.extend(glob.glob(pattern))
        image_files.sort(key=os.path.getmtime, reverse=True)
        print(f"Found {len(image_files)} image(s) in {output_dir_path}.")
        return [os.path.abspath(f) for f in image_files]
    except Exception as e:
        print(f"Error scanning output directory: {e}")
        return []

def find_key_by_class_type_internal(p, class_type):
    """Finds the first key (node ID) matching the given class_type."""
    if isinstance(class_type, str):
        target_types = {class_type}
    else:
        target_types = set(class_type)
    for k, v in p.items():
        if isinstance(v, dict) and v.get("class_type") in target_types:
            return k
    return None

def find_all_nodes_by_class_type(prompt_workflow, class_type):
    """Finds all nodes matching the given class_type and returns their info."""
    found_nodes = []
    if not isinstance(prompt_workflow, dict):
        return found_nodes
    
    if isinstance(class_type, str):
        target_types = {class_type}
    else:
        target_types = set(class_type)
        
    for node_id, node_data in prompt_workflow.items():
        if isinstance(node_data, dict) and node_data.get("class_type") in target_types:
            title = node_id # Default title to node_id
            if "_meta" in node_data and isinstance(node_data["_meta"], dict) and "title" in node_data["_meta"]:
                title = node_data["_meta"]["title"]
            
            node_info = {
                "id": node_id,
                "inputs": node_data.get("inputs", {}), # The 'inputs' field of the node
                "title": title,
                "class_type": node_data.get("class_type")
            }
            found_nodes.append(node_info)
    return found_nodes


K_SAMPLER_CLASS_TYPES = {
    "KSampler",
    "KSamplerAdvanced",
    "KSamplerSDXL",
    "KSamplerLite",
    "KPyramidSampler",
}

LORA_NODE_CLASSES = {
    "Hua_LoraLoaderModelOnly",
    "LoraLoader",
    "LoraLoaderModelOnly",
}

CHECKPOINT_NODE_CLASSES = {
    "Hua_CheckpointLoaderSimple",
    "CheckpointLoaderSimple",
}

UNET_NODE_CLASSES = {
    "Hua_UNETLoader",
    "UNETLoader",
    "UnetLoader",
    "UnetLoaderGGUF",
}

IMAGE_INPUT_NODE_CLASSES = {
    "GradioInputImage",
    "LoadImage",
    "LoadAndResizeImage",
    "Hua_LoadImage",
    "ImageInput",
}

VIDEO_INPUT_NODE_CLASSES = {
    "VHS_LoadVideo",
    "LoadVideo",
    "Hua_LoadVideo",
}


def _extract_node_ids(value):
    """Return the set of node ids referenced inside a ComfyUI connection value."""
    referenced = set()
    if isinstance(value, (list, tuple)):
        if value and isinstance(value[0], str):
            referenced.add(value[0])
        else:
            for item in value:
                referenced.update(_extract_node_ids(item))
    return referenced


def _get_text_input_key(class_type):
    """Return the input key that holds user-editable text for a given node class."""
    if class_type in {"GradioTextOk", "GradioTextBad"}:
        return "string"
    if class_type and class_type.startswith("CLIPTextEncode"):
        return "text"
    if class_type and class_type.startswith("TextEncodeQwen"):
        return "prompt"
    if class_type in {"TextPreview", "PromptInputNode"}:
        return "text"
    return None


def _collect_upstream_text_nodes(prompt_workflow, start_ids):
    """Walk upstream from the provided node ids and collect any text nodes encountered."""
    discovered = set()
    visited = set()
    queue = list(start_ids)

    while queue:
        current = queue.pop()
        if current in visited:
            continue
        visited.add(current)

        node = prompt_workflow.get(current)
        if not isinstance(node, dict):
            continue

        class_type = node.get("class_type")
        text_key = _get_text_input_key(class_type)
        if text_key:
            discovered.add(current)

        inputs = node.get("inputs", {})
        for key, value in inputs.items():
            # Restrict traversal to conditioning/text-related edges so we don't wander
            # through latent/image branches that loop back into the graph (which caused
            # prompt nodes to be misclassified).
            key_lower = key.lower() if isinstance(key, str) else ""
            follow_connection = False

            if text_key and key == text_key:
                follow_connection = True
            elif "cond" in key_lower:  # match conditioning*, cond, etc.
                follow_connection = True
            elif key_lower in {"positive", "negative"}:
                follow_connection = True

            if not follow_connection:
                continue

            for ref_id in _extract_node_ids(value):
                if ref_id not in visited:
                    queue.append(ref_id)

    return discovered

def _convert_workflow_to_prompt(workflow_data: dict) -> dict:
    """Convert a ComfyUI workflow (graph) JSON to the API prompt dictionary structure."""
    prompt = {}
    link_lookup = {}

    for link in workflow_data.get("links", []):
        # Expected format: [link_id, from_node_id, from_slot, to_node_id, to_slot, type]
        if not isinstance(link, list) or len(link) < 5:
            continue
        link_id, from_node, from_slot, *_rest = link
        try:
            link_lookup[int(link_id)] = (str(from_node), from_slot)
        except (TypeError, ValueError):
            continue

    extra_meta = workflow_data.get("extra", {}).get("nodeMetadata", {}) or {}

    for node in workflow_data.get("nodes", []):
        try:
            node_id = str(node["id"])
        except (KeyError, TypeError):
            continue

        inputs_map = {}
        widget_values = list(node.get("widgets_values") or [])
        widget_index = 0
        extra_widget_values = []

        def _matches_expected(expected_type, candidate):
            if expected_type is None:
                return True
            if candidate is None:
                return True
            expected_upper = str(expected_type).upper()
            if expected_upper in {"INT", "INTEGER"}:
                return isinstance(candidate, (int, float)) and not isinstance(candidate, bool)
            if expected_upper in {"FLOAT", "DOUBLE"}:
                return isinstance(candidate, (int, float)) and not isinstance(candidate, bool)
            if expected_upper in {"BOOLEAN", "BOOL"}:
                if isinstance(candidate, bool):
                    return True
                if isinstance(candidate, str):
                    return candidate.lower() in {"true", "false", "enable", "disable"}
                return False
            if expected_upper == "STRING":
                return isinstance(candidate, str)
            if expected_upper == "COMBO":
                return isinstance(candidate, (str, int, float, bool))
            # For other custom types (MODEL, IMAGE, etc.), accept any primitive
            return True

        def _consume_widget_value(expected_type):
            nonlocal widget_index
            while widget_index < len(widget_values):
                candidate = widget_values[widget_index]
                widget_index += 1
                if _matches_expected(expected_type, candidate):
                    return candidate
                extra_widget_values.append(candidate)
            return None

        for input_def in node.get("inputs", []):
            name = input_def.get("name")
            if not name:
                continue

            link_id = input_def.get("link")
            if link_id is not None:
                link_entry = link_lookup.get(int(link_id)) if isinstance(link_id, int) else link_lookup.get(link_id)
                if link_entry:
                    inputs_map[name] = [link_entry[0], link_entry[1]]
                # If the link cannot be resolved, ignore for now (will rely on defaults)
                continue

            if "widget" in input_def:
                value = _consume_widget_value(input_def.get("type"))
            else:
                value = None
            inputs_map[name] = value

        # Capture any remaining widget values that were not matched to inputs.
        if widget_index < len(widget_values):
            extra_widget_values.extend(widget_values[widget_index:])

        prompt_entry = {
            "class_type": node.get("type"),
            "inputs": inputs_map
        }

        title = None
        node_properties = node.get("properties") or {}
        title = node_properties.get("Node name for S&R") or node_properties.get("title")
        if not title:
            meta_entry = extra_meta.get(node_id)
            if isinstance(meta_entry, dict):
                title = meta_entry.get("title")
        if title:
            prompt_entry["_meta"] = {"title": title}
        if extra_widget_values:
            prompt_entry.setdefault("_meta", {}).setdefault("info", {})["unused_widget_values"] = extra_widget_values

        prompt[node_id] = prompt_entry

    return prompt


def load_prompt_from_file(json_path: str) -> dict:
    """Load a workflow or prompt JSON file and return a prompt dictionary compatible with ComfyUI API."""
    try:
        with open(json_path, "r", encoding="utf-8") as file_json:
            data = json.load(file_json)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error reading or parsing JSON file ({json_path}): {e}")
        return {}
    except Exception as e:
        print(f"Unknown error loading workflow ({json_path}): {e}")
        return {}

    if isinstance(data, dict) and "nodes" in data and "links" in data:
        try:
            prompt = _convert_workflow_to_prompt(data)
            print(f"Converted workflow graph to prompt for {json_path}.")
            return prompt
        except Exception as e:
            print(f"Failed to convert workflow graph to prompt for {json_path}: {e}")
            return {}

    if isinstance(data, dict):
        return data

    print(f"Unsupported workflow format in {json_path}; expected dict structure.")
    return {}

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
            "PowerLoraLoader": [],
            "HuaIntNode": [],
            "HuaFloatNode": [],
            "KSampler": [],
            "APersonMaskGenerator": [],
            "ImageLoaders": []
        },
        "negative_prompt_nodes": []
    }

    full_path = os.path.join(output_dir_path, json_file) if json_file else None
    if not full_path or not os.path.isfile(full_path):
        print(f"Invalid or missing JSON file: {json_file}")
        return defaults

    prompt = load_prompt_from_file(full_path)
    if not isinstance(prompt, dict) or not prompt:
        print(f"Error: Workflow prompt data unavailable for {json_file}.")
        return defaults

    # --- Handle Single Instance Components ---
    defaults["visible_image_input"] = find_key_by_class_type_internal(prompt, tuple(IMAGE_INPUT_NODE_CLASSES)) is not None
    defaults["visible_video_input"] = find_key_by_class_type_internal(prompt, tuple(VIDEO_INPUT_NODE_CLASSES)) is not None
    
    neg_prompt_key = find_key_by_class_type_internal(prompt, ("GradioTextBad",))
    if neg_prompt_key and neg_prompt_key in prompt and "inputs" in prompt[neg_prompt_key]:
        defaults["visible_neg_prompt"] = True
        defaults["default_neg_prompt"] = prompt[neg_prompt_key]["inputs"].get("string", "")
    
    resolution_key = find_key_by_class_type_internal(prompt, ("Hua_gradio_resolution",))
    if resolution_key and resolution_key in prompt and "inputs" in prompt[resolution_key]:
        defaults["visible_resolution"] = True
        try: defaults["default_width"] = int(prompt[resolution_key]["inputs"].get("custom_width", 512))
        except (ValueError, TypeError): pass
        try: defaults["default_height"] = int(prompt[resolution_key]["inputs"].get("custom_height", 512))
        except (ValueError, TypeError): pass
        
    checkpoint_key = find_key_by_class_type_internal(prompt, tuple(CHECKPOINT_NODE_CLASSES))
    if checkpoint_key and checkpoint_key in prompt and "inputs" in prompt[checkpoint_key]:
        defaults["visible_checkpoint"] = True
        defaults["default_checkpoint"] = prompt[checkpoint_key]["inputs"].get("ckpt_name", "None")

    unet_key = find_key_by_class_type_internal(prompt, tuple(UNET_NODE_CLASSES))
    if unet_key and unet_key in prompt and "inputs" in prompt[unet_key]:
        defaults["visible_unet"] = True
        defaults["default_unet"] = prompt[unet_key]["inputs"].get("unet_name", "None")

    defaults["visible_seed_indicator"] = find_key_by_class_type_internal(prompt, ("Hua_gradio_Seed",)) is not None
    defaults["visible_image_output"] = find_key_by_class_type_internal(prompt, ("Hua_Output", "SaveImage")) is not None
    defaults["visible_video_output"] = find_key_by_class_type_internal(prompt, ("Hua_Video_Output", "SaveVideo", "VHS_VideoCombine")) is not None

    image_loader_nodes = find_all_nodes_by_class_type(prompt, tuple(IMAGE_INPUT_NODE_CLASSES))

    def _to_int_local(value, default=None):
        try:
            if value is None or value == "":
                return default
            return int(value)
        except (ValueError, TypeError):
            return default

    def _to_bool_local(value, default=False):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in {"true", "1", "yes", "on", "enable"}
        return default

    for node_info in image_loader_nodes:
        inputs_map = node_info.get("inputs", {}) or {}
        field_name = None
        if "image" in inputs_map:
            field_name = "image"
        elif "images" in inputs_map:
            field_name = "images"
        if not field_name:
            continue

        current_value = inputs_map.get(field_name)
        loader_entry = {
            "id": node_info.get("id"),
            "title": node_info.get("title"),
            "field_name": field_name,
            "resize": _to_bool_local(inputs_map.get("resize", False), False),
            "width": _to_int_local(inputs_map.get("width")),
            "height": _to_int_local(inputs_map.get("height")),
            "keep_proportion": _to_bool_local(inputs_map.get("keep_proportion", False), False),
            "divisible_by": _to_int_local(inputs_map.get("divisible_by")),
            "connected": isinstance(current_value, list),
        }

        defaults["dynamic_components"]["ImageLoaders"].append(loader_entry)

    # --- Analyse conditioning graph to discover text prompts ---
    positive_conditioning_ids = set()
    negative_conditioning_ids = set()
    for node_id, node_data in prompt.items():
        if not isinstance(node_data, dict):
            continue
        if node_data.get("class_type") in K_SAMPLER_CLASS_TYPES:
            inputs = node_data.get("inputs", {})
            positive_conditioning_ids.update(_extract_node_ids(inputs.get("positive")))
            negative_conditioning_ids.update(_extract_node_ids(inputs.get("negative")))

    positive_text_nodes = _collect_upstream_text_nodes(prompt, positive_conditioning_ids)
    negative_text_nodes = _collect_upstream_text_nodes(prompt, negative_conditioning_ids)

    for node_id, node_data in prompt.items():
        if not isinstance(node_data, dict):
            continue
        class_type = node_data.get("class_type")
        text_key = _get_text_input_key(class_type)
        if not text_key:
            continue

        inputs = node_data.get("inputs", {})
        text_value = inputs.get(text_key)
        if not isinstance(text_value, str):
            continue

        title = node_data.get("_meta", {}).get("title", node_id)
        entry_base = {
            "id": node_id,
            "value": text_value,
            "title": title,
            "class_type": class_type,
            "text_key": text_key
        }

        if (node_id in positive_text_nodes) or (node_id not in negative_text_nodes):
            pos_entry = entry_base.copy()
            if node_id in positive_text_nodes and node_id in negative_text_nodes:
                pos_entry["role"] = "mixed"
            elif node_id in positive_text_nodes:
                pos_entry["role"] = "positive"
            else:
                pos_entry["role"] = "unspecified"
            defaults["dynamic_components"]["GradioTextOk"].append(pos_entry)

        if node_id in negative_text_nodes:
            neg_entry = entry_base.copy()
            neg_entry["role"] = "mixed" if node_id in positive_text_nodes else "negative"
            defaults["negative_prompt_nodes"].append(neg_entry)

    if defaults["negative_prompt_nodes"] and not defaults["visible_neg_prompt"]:
        defaults["visible_neg_prompt"] = True
        defaults["default_neg_prompt"] = defaults["negative_prompt_nodes"][0]["value"]
    elif defaults["negative_prompt_nodes"] and not defaults["default_neg_prompt"]:
        defaults["default_neg_prompt"] = defaults["negative_prompt_nodes"][0]["value"]

    # Sort positive prompts so that clearly positive ones appear first
    role_priority = {"positive": 0, "mixed": 1, "unspecified": 2}
    defaults["dynamic_components"]["GradioTextOk"].sort(key=lambda item: role_priority.get(item.get("role", "unspecified"), 3))

    # --- Handle Dynamic Components ---
    # Hua_LoraLoaderModelOnly (Lora Loaders and equivalents)
    lora_nodes = find_all_nodes_by_class_type(prompt, tuple(LORA_NODE_CLASSES))
    for node_info in lora_nodes:
        defaults["dynamic_components"]["Hua_LoraLoaderModelOnly"].append({
            "id": node_info["id"],
            "value": node_info["inputs"].get("lora_name", "None"),
            "title": node_info["title"],
            "class_type": node_info["class_type"]
        })

    # Power Lora Loader (rgthree) - Multi-lora loader
    power_lora_nodes = find_all_nodes_by_class_type(prompt, "Power Lora Loader (rgthree)")
    for node_info in power_lora_nodes:
        # Extract lora entries from inputs (lora_01, lora_02, etc.)
        # In prompt format, the loras are stored as lora_01, lora_02, etc. in inputs
        loras = []
        inputs = node_info.get("inputs", {})

        # Try to find loras by looking for lora_01, lora_02, etc. keys
        for key, value in inputs.items():
            if key.lower().startswith("lora_") and isinstance(value, dict) and "lora" in value:
                loras.append({
                    "key": key,
                    "on": value.get("on", True),
                    "lora": value.get("lora", "None"),
                    "strength": value.get("strength", 1.0),
                    "strengthTwo": value.get("strengthTwo", None)
                })

        # Always add the node, even if no loras are found (user can configure them in UI)
        defaults["dynamic_components"]["PowerLoraLoader"].append({
            "id": node_info["id"],
            "title": node_info["title"],
            "class_type": node_info["class_type"],
            "loras": loras
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

    # KSampler controls
    ksampler_nodes = find_all_nodes_by_class_type(prompt, tuple(K_SAMPLER_CLASS_TYPES))
    for node_info in ksampler_nodes:
        inputs = node_info["inputs"]
        def _to_int(value, default=0):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        def _to_float(value, default=0.0):
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        seed_field = None
        raw_seed_value = ""
        if "noise_seed" in inputs:
            seed_field = "noise_seed"
            raw_seed_value = inputs.get("noise_seed", "")
        elif "seed" in inputs:
            seed_field = "seed"
            raw_seed_value = inputs.get("seed", "")

        seed_string = str(raw_seed_value).strip() if raw_seed_value is not None else ""
        seed_locked = bool(seed_field) and seed_string not in {"", "0", "random", "auto", "randomize"}
        seed_hint = seed_string if seed_locked else ""
        seed_display = "" if seed_locked or seed_string.lower() in {"random", "auto", "randomize"} else seed_string

        defaults["dynamic_components"]["KSampler"].append({
            "id": node_info["id"],
            "title": node_info["title"],
            "steps": _to_int(inputs.get("steps", 20), 20),
            "cfg": _to_float(inputs.get("cfg", 8.0), 8.0),
            "sampler_name": inputs.get("sampler_name", ""),
            "scheduler": inputs.get("scheduler", ""),
            "denoise": _to_float(inputs.get("denoise", 1.0), 1.0),
            "add_noise": inputs.get("add_noise", "enable"),
            "start_at_step": _to_int(inputs.get("start_at_step", 0), 0),
            "end_at_step": _to_int(inputs.get("end_at_step", 0), 0),
            "return_with_leftover_noise": inputs.get("return_with_leftover_noise", "disable"),
            "seed_field": seed_field or "noise_seed",
            "seed": seed_display,
            "seed_hint": seed_hint,
            "seed_locked": seed_locked,
        })

    # APersonMaskGenerator controls
    mask_nodes = find_all_nodes_by_class_type(prompt, "APersonMaskGenerator")
    for node_info in mask_nodes:
        inputs = node_info["inputs"]
        def _to_bool(value, default=False):
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in {"true", "1", "yes", "on", "enable"}
            return default

        def _to_float_local(value, default=0.0):
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        defaults["dynamic_components"]["APersonMaskGenerator"].append({
            "id": node_info["id"],
            "title": node_info["title"],
            "face_mask": _to_bool(inputs.get("face_mask", True), True),
            "background_mask": _to_bool(inputs.get("background_mask", False), False),
            "hair_mask": _to_bool(inputs.get("hair_mask", False), False),
            "body_mask": _to_bool(inputs.get("body_mask", False), False),
            "clothes_mask": _to_bool(inputs.get("clothes_mask", False), False),
            "confidence": _to_float_local(inputs.get("confidence", 0.15), 0.15),
            "refine_mask": _to_bool(inputs.get("refine_mask", False), False),
        })
    
    return defaults

# --- Plugin Settings Management ---
# These helper functions expect the settings file to live in the plugin root (ComfyUI_to_webui)

PLUGIN_SETTINGS_FILE = "plugin_settings.json" 
DEFAULT_MAX_DYNAMIC_COMPONENTS = 5
DEFAULT_THEME_MODE = "dark"

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
                if not isinstance(settings, dict):
                    raise ValueError("Settings file does not contain a JSON object.")
        else:
            print(f"Info: Plugin settings file '{settings_file_path}' not found. Creating default settings.")
            settings = {}

        changed = False
        if not isinstance(settings.get("max_dynamic_components"), int):
            print(f"Warning: 'max_dynamic_components' missing or invalid in '{settings_file_path}'. Using default ({DEFAULT_MAX_DYNAMIC_COMPONENTS}) and updating file.")
            settings["max_dynamic_components"] = DEFAULT_MAX_DYNAMIC_COMPONENTS
            changed = True
        if not isinstance(settings.get("theme_mode"), str):
            settings["theme_mode"] = DEFAULT_THEME_MODE
            changed = True

        if changed:
            save_plugin_settings(settings) # persist corrected settings
        return settings
    except Exception as e:
        print(f"Error: Failed to load plugin settings '{settings_file_path}': {e}. Using defaults.")
        fallback = {
            "max_dynamic_components": DEFAULT_MAX_DYNAMIC_COMPONENTS,
            "theme_mode": DEFAULT_THEME_MODE,
        }
        save_plugin_settings(fallback)
        return fallback

def save_plugin_settings(settings_dict):
    """Saves plugin settings to the main plugin directory."""
    settings_file_path = _get_settings_file_path()
    try:
        with open(settings_file_path, "w", encoding="utf-8") as f:
            json.dump(settings_dict, f, indent=4, ensure_ascii=False)
        print(f"Info: Plugin settings saved to '{settings_file_path}'.")
        return "Settings saved."
    except Exception as e:
        print(f"Error: Unable to save plugin settings to '{settings_file_path}': {e}")
        return f"Failed to save settings: {e}"
# --- End Plugin Settings Management ---
