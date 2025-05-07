#---------------------------------------------------------------------------------------------------------------------#
#节点作者：hua   代码地址：https://github.com/kungful/ComfyUI_hua_boy.git
#---------------------------------------------------------------------------------------------------------------------#
import sys
from .hua_icons import icons
import typing as tg
import json
import os
import random
import numpy as np  # 用于处理图像数据
from PIL import Image, ImageOps, ImageSequence, ImageFile
from PIL.PngImagePlugin import PngInfo
import folder_paths  # 假设这是一个自定义模块，用于处理文件路径
from comfy.cli_args import args
import comfy.utils # Need this import for Hua_LoraLoader
import node_helpers # Need this import for GradioInputImage
import torch # Need this import for GradioInputImage
from datetime import datetime # Need this import for Hua_Output
import barcode
from barcode.writer import ImageWriter
# Removed duplicate Image import, kept ImageDraw and ImageFont
from PIL import ImageDraw, ImageFont
from comfy.cli_args import args


OUTPUT_DIR = folder_paths.get_output_directory()
FONT_PATH = os.path.join(os.path.dirname(__file__),  "fonts/SimHei.ttf")

def find_key_by_name(prompt, name):
    for key, value in prompt.items():
        if isinstance(value, dict) and value.get("_meta", {}).get("title") == name:
            return key
    return None

def check_seed_node(json_file):
    # 检查文件是否存在且有效
    if not json_file or not os.path.exists(os.path.join(OUTPUT_DIR, json_file)):
        print(f"JSON 文件无效或不存在: {json_file}")
        return gr.update(visible=False) # 如果文件无效，隐藏种子节点指示器

    json_path = os.path.join(OUTPUT_DIR, json_file)
    try:
        with open(json_path, "r", encoding="utf-8") as file_json:
            prompt = json.load(file_json)
        seed_key = find_key_by_name(prompt, "🧙hua_gradio随机种")
        if seed_key is None:
            return gr.update(visible=False)
        else:
            return gr.update(visible=True)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"读取或解析 JSON 文件时出错 ({json_file}): {e}")
        return gr.update(visible=False) # 出错时也隐藏

current_dir = os.path.dirname(os.path.abspath(__file__))# 获取当前文件的目录
print("当前hua插件文件的目录为：", current_dir)
parent_dir = os.path.dirname(os.path.dirname(current_dir))# 获取上两级目录
sys.path.append(parent_dir)# 将上两级目录添加到 sys.path
from comfy.cli_args import args
from .hua_icons import icons




class GradioTextBad:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "string": ("STRING", {"multiline": True, "dynamicPrompts": True, "tooltip": "The text to be encoded."}),

            }
        }
    RETURN_TYPES = ("STRING",)
    OUTPUT_TOOLTIPS = ("A conditioning containing the embedded text used to guide the diffusion model.",)
    FUNCTION = "encode"

    CATEGORY = icons.get("hua_boy_one")
    DESCRIPTION = "Encodes a text prompt using a CLIP model into an embedding that can be used to guide the diffusion model towards generating specific images."

    def encode(self,string):
        return (string,)

class GradioInputImage:
    @classmethod
    def INPUT_TYPES(s):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
        return {"required":
                    {"image": (sorted(files), {"image_upload": True})},
                }

    OUTPUT_TOOLTIPS = ("这是一个gradio输入图片的节点",)
    FUNCTION = "load_image"
    OUTPUT_NODE = True
    CATEGORY = icons.get("hua_boy_one")
    RETURN_TYPES = ("IMAGE", "MASK")



    def load_image(self, image):
        image_path = folder_paths.get_annotated_filepath(image)
        print("laodimage函数读取图像路径为：", image_path)

        img = node_helpers.pillow(Image.open, image_path)

        output_images = [] #用于存储处理后的图像的列表。
        output_masks = [] #用于存储对应掩码的列表。
        w, h = None, None # 用于存储图像的宽度和高度，初始值为 None。

        excluded_formats = ['MPO']  #这里只排除了 'MPO' 格式

        for i in ImageSequence.Iterator(img):
            i = node_helpers.pillow(ImageOps.exif_transpose, i)#根据 EXIF 数据纠正图像方向

            if i.mode == 'I': #如果图像模式为 'I'（32 位有符号整数像素），则将像素值缩放到 [0, 1] 范围。
                i = i.point(lambda i: i * (1 / 255))
            image = i.convert("RGB")#将图像转换为 RGB 模式

            if len(output_images) == 0: #如果是第一帧，则设置图像的宽度和高度。
                w = image.size[0]
                h = image.size[1]

            if image.size[0] != w or image.size[1] != h: #如果不等于那么跳过不匹配初始宽度和高度的帧。
                continue

            image = np.array(image).astype(np.float32) / 255.0 #将图像转换为 NumPy 数组，并将像素值归一化到 [0, 1] 范围。
            image = torch.from_numpy(image)[None,] #将 NumPy 数组转换为 PyTorch 张量。
            if 'A' in i.getbands(): #检查图像是否有 alpha 通道。
                mask = np.array(i.getchannel('A')).astype(np.float32) / 255.0 #提取 alpha 通道并将其归一化。
                mask = 1. - torch.from_numpy(mask)#反转掩码（假设 alpha 通道表示透明度）
            else:
                mask = torch.zeros((64,64), dtype=torch.float32, device="cpu") #如果没有 alpha 通道，则创建一个大小为 (64, 64) 的零掩码。
            output_images.append(image) #将处理后的图像添加到列表中。
            output_masks.append(mask.unsqueeze(0)) #将掩码添加到列表中。

        if len(output_images) > 1 and img.format not in excluded_formats:#检查处理后的图像帧数量是否大于 1。如果大于 1，说明图像包含多个帧（例如 GIF 或多帧图像）。 检查图像格式是否不在排除的格式列表中。
            output_image = torch.cat(output_images, dim=0)# 将所有处理后的图像沿批次维度（dim=0）连接起来。假设 output_images 是一个包含多个图像张量的列表，torch.cat 会将这些张量在批次维度上拼接成一个大的张量。
            output_mask = torch.cat(output_masks, dim=0)#将所有掩码沿批次维度（dim=0）连接起来。假设 output_masks 是一个包含多个掩码张量的列表，torch.cat 会将这些张量在批次维度上拼接成一个大的张量。
        else:
            # 单帧情况：
            output_image = output_images[0] #如果图像只有一个帧或格式在排除列表中，则直接使用第一个帧作为输出图像。
            output_mask = output_masks[0]#同样，使用第一个帧的掩码作为输出掩码。

        return (output_image, output_mask) #返回一个包含处理后的图像及其对应掩码的元组。






#_________________________________________________条形码生成器____________________________________________________#
class Barcode_seed:

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff})}}

    RETURN_TYPES = ("INT", "STRING", )
    RETURN_NAMES = ("种子值", "帮助链接", )
    FUNCTION = "hua_seed"
    OUTPUT_NODE = True
    CATEGORY = icons.get("hua_boy_one")

    @staticmethod
    def hua_seed(seed):
        show_help = "https://github.com/kungful/ComfyUI_hua_boy.git"
        return (seed, show_help,)

class BarcodeGeneratorNode: # 类名修改得更清晰
    # 用于存储上一次运行的数字 - 注意：ComfyUI 节点通常是无状态的，
    # 每次执行都是独立的。这种类级别的变量可能不会按预期跨执行保留状态。
    # 实现自动递增的更可靠方法是在工作流中将输出连接回输入，
    # 或者让用户手动更新输入。
    # 这里我们实现一个简单的逻辑：接收输入数字，将其+1后用于生成。
    # last_number = None # 暂时不使用类变量存储状态

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "前缀": ("STRING", { # 修改键名
                    "display_name": "前缀(可选)",
                    "multiline": False,
                    "default": "" # 默认前缀为空
                }),
                "输入数字": ("INT", { # 修改为INT类型
                    "display_name": "起始数字",
                    "default": 0, # 默认从0开始
                    "min": 0,
                    "max": 0xffffffffffffffff
                }),
                 "字体大小": ("INT", { # 修改键名
                    "display_name": "文本大小(px)",
                    "default": 25,
                    "min": 10,
                    "max": 200,
                    "step": 1
                }),
                    "条码高度缩放": ("FLOAT", { # 修改键名
                        "display_name": "条码高度比例",
                        "default": 0.5,
                        "min": 0.1, # 将最小值改为 0.1
                        "max": 3.0,
                        "step": 0.1
                    }),
                 "文本下边距": ("INT", { # 修改键名
                    "display_name": "文本底部间距(px)",
                    "default": 15,
                    "min": 5,
                    "max": 50,
                    "step": 1
                }),
                "条码与文本间距": ("INT", { # 新增参数
                    "display_name": "条码与文本间距(px)",
                    "default": 10,
                    "min": -80, # 允许负值以减少间距
                    "max": 50,
                    "step": 1
                }),
                "左右边距": ("FLOAT", {
                    "display_name": "左右边距比例",
                    "default": 2.0,
                    "min": 0.0,
                    "max": 20.0,
                    "step": 0.5
                }),
                "顶部边距": ("INT", {
                    "display_name": "顶部边距(px)",
                    "default": 5,
                    "min": 0,
                    "max": 100,
                    "step": 1
                }),
                "全局缩放比例": ("FLOAT", { # 新增全局缩放参数
                    "display_name": "全局缩放比例",
                    "default": 1.0,
                    "min": 0.1, # 最小缩放到 10%
                    "max": 10.0, # 最大放大到 10 倍
                    "step": 0.1
                })
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING") # 增加返回递增后的数字字符串
    RETURN_NAMES = ("条形码图像", "尺寸遮罩", "输出数字") # 已汉化
    FUNCTION = "generate"
    CATEGORY = icons.get("hua_boy_one") # 统一分类前缀

    # --- Helper for PIL version compatibility ---
    try:
        RESAMPLING_MODE = Image.Resampling.LANCZOS
    except AttributeError:
        # Fallback for older PIL versions
        RESAMPLING_MODE = Image.LANCZOS
    # --- End Helper ---

    def validate_number_input(self, num):
        """验证输入数字范围"""
        if num < 0:
            raise ValueError("错误：起始数字不能为负数")
        return num

    def draw_text(self, img, text, font_path, font_size, top_y): # 修改参数名 bottom_margin -> top_y
        """在图像指定 top_y 位置绘制文本，支持中英文字体，并居中"""
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(font_path, font_size)
        except IOError:
            print(f"警告：无法加载字体 {font_path}。尝试使用默认字体。")
            try:
                # 尝试加载 PIL 默认字体，如果可用
                font = ImageFont.load_default()
                # 对于默认字体，可能需要调整大小或接受其固有大小
                # font_size = 10 # 可以取消注释以强制默认字体大小
            except IOError:
                print("警告：无法加载默认字体。将不绘制文本。")
                return img # 无法绘制文本，返回原图

        # 使用 textbbox 获取更准确的文本边界框
        try:
            # textbbox 需要 4 个参数 (xy, text, font, spacing) 或 (xy, text, font)
            # 我们先在 (0,0) 处计算尺寸
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
        except AttributeError: # 兼容旧版 PIL 可能没有 textbbox
             text_width, text_height = draw.textsize(text, font=font)


        # 计算文本绘制位置
        img_width, _ = img.size # 只需宽度用于居中
        x = (img_width - text_width) // 2
        # y 坐标现在直接使用传入的 top_y
        y = top_y

        # 绘制文本 (不再需要检查 y 是否为负，因为它是从顶部计算的)
        draw.text((x, y), text, font=font, fill="black")

        return img

    def generate(self, 前缀, 输入数字, 字体大小, 条码高度缩放, 文本下边距, 条码与文本间距, 左右边距, 顶部边距, 全局缩放比例): # 添加全局缩放比例参数
        # 1. 输入验证
        try:
            # 验证数字输入
            current_number = self.validate_number_input(输入数字)
            # 验证缩放比例
            if 全局缩放比例 <= 0:
                raise ValueError("全局缩放比例必须大于 0")
            next_number_str = str(输入数字)  # 转换为字符串
        except ValueError as e:
            print(f"输入错误: {e}")
            # 可以返回一个错误图像或默认图像
            error_img = Image.new("RGB", (300, 100), "white")
            draw = ImageDraw.Draw(error_img)
            draw.text((10, 10), f"错误: {e}", fill="red")
            image_np = np.array(error_img).astype(np.float32) / 255.0
            image_tensor = torch.from_numpy(image_np)[None,]
            mask = torch.ones((100, 300), dtype=torch.float32)
            return (image_tensor, mask, str(输入数字)) # 返回原始输入数字

        # 2. 生成条形码核心 (只使用递增后的数字)
        try:
            code128 = barcode.get_barcode_class('code128')
            # 设置 writer 选项来调整条码本身参数
            writer_options = {
                'module_height': 15.0 * 条码高度缩放, # 控制条码高度，使用修改后的参数名
                'write_text': False, # 禁用库自带的文本
                'quiet_zone': 左右边距, # 使用输入参数控制左右边距
                'dpi': int(300 * 全局缩放比例) # 动态计算dpi，根据缩放比例提高分辨率
            }
            barcode_pil_img = code128(next_number_str, writer=ImageWriter()).render(writer_options)
        except Exception as e:
            print(f"条形码生成错误: {e}")
            # 返回错误图像
            error_img = Image.new("RGB", (300, 100), "white")
            draw = ImageDraw.Draw(error_img)
            draw.text((10, 10), f"条码错误: {e}", fill="red")
            image_np = np.array(error_img).astype(np.float32) / 255.0
            image_tensor = torch.from_numpy(image_np)[None,]
            mask = torch.ones((100, 300), dtype=torch.float32)
            return (image_tensor, mask, str(输入数字)) # 返回原始输入数字

        # 3. 计算最终画布尺寸
        barcode_width, barcode_height = barcode_pil_img.size
        # 估算文本高度，需要加载字体
        try:
            font = ImageFont.truetype(FONT_PATH, 字体大小) # 使用修改后的参数名
            # 估算组合文本的高度 (只需要文本本身的高度)
            combined_text = f"{前缀}{next_number_str}" # 使用修改后的参数名
            bbox = ImageDraw.Draw(Image.new("RGB",(1,1))).textbbox((0,0), combined_text, font=font)
            text_actual_height = bbox[3] - bbox[1]
        except Exception:
            text_actual_height = 字体大小 # 粗略估计

        # 计算文本区域总共需要的高度 = 间距 + 文本高度 + 底部边距
        text_area_total_height = 条码与文本间距 + text_actual_height + 文本下边距

        # 确保最小尺寸
        min_width = 200
        min_height = 50 # 降低最小高度要求

        canvas_width = max(barcode_width, min_width)
        # 总高度 = 顶部边距 + 条码高度 + 文本区域总高度
        # top_padding = 5 # 不再硬编码顶部留白
        canvas_height = max(顶部边距 + barcode_height + text_area_total_height, min_height) # 使用输入参数

        # 4. 创建画布并将条形码粘贴到顶部（居中）
        canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
        paste_x = (canvas_width - barcode_width) // 2
        paste_y = 顶部边距 # 使用输入参数作为顶部留白
        canvas.paste(barcode_pil_img, (paste_x, paste_y))

        # 5. 在条形码下方绘制组合文本
        combined_text_to_draw = f"{前缀}{输入数字}" # 使用原始输入数字
        # 计算文本绘制的顶部 Y 坐标
        text_top_y = paste_y + barcode_height + 条码与文本间距 # 条码底部 + 间距

        try:
            # 调用修改后的 draw_text，传入计算好的 text_top_y
            canvas_with_text = self.draw_text(canvas, combined_text_to_draw, FONT_PATH, 字体大小, text_top_y)

        except Exception as e:
            print(f"绘制文本时出错: {e}")
            # 出错也继续，可能只显示条形码
            canvas_with_text = canvas # 使用没有文本的画布

        # 6. 应用全局缩放
        original_width, original_height = canvas_with_text.size
        scaled_width = max(1, int(original_width * 全局缩放比例)) # 确保最小为 1
        scaled_height = max(1, int(original_height * 全局缩放比例)) # 确保最小为 1

        if 全局缩放比例 != 1.0:
            try:
                print(f"原始尺寸: {original_width}x{original_height}, 缩放比例: {全局缩放比例}, 缩放后尺寸: {scaled_width}x{scaled_height}")
                # 创建临时高分辨率画布进行高质量缩放
                temp_canvas = Image.new("RGB", (original_width, original_height), "white")
                temp_canvas.paste(canvas_with_text, (0, 0))
                # 使用高质量的 LANCZOS 滤波器进行缩放，并保持高分辨率
                final_canvas = temp_canvas.resize((scaled_width, scaled_height), self.RESAMPLING_MODE)
            except Exception as e:
                print(f"图像缩放时出错: {e}")
                final_canvas = canvas_with_text # 缩放失败则返回原始图像
        else:
            final_canvas = canvas_with_text # 无需缩放

        # 7. 转换为 ComfyUI 兼容格式
        final_image_np = np.array(final_canvas).astype(np.float32) / 255.0
        final_image_tensor = torch.from_numpy(final_image_np)[None,]

        # 创建与最终缩放后图像尺寸匹配的 mask
        final_height, final_width = final_image_np.shape[:2] # 从缩放后的 numpy 数组获取尺寸
        mask = torch.ones((final_height, final_width), dtype=torch.float32)

        # 返回图像、mask 和原始输入数字字符串
        return (final_image_tensor, mask, str(输入数字))

class Hua_gradio_Seed:

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff})}}

    RETURN_TYPES = ("INT", "STRING", )
    RETURN_NAMES = ("seed", "show_help", )
    FUNCTION = "hua_seed"
    OUTPUT_NODE = True
    CATEGORY = icons.get("hua_boy_one")

    @staticmethod
    def hua_seed(seed):
        show_help = "https://github.com/kungful/ComfyUI_hua_boy.git"
        return (seed, show_help,)
#---------------------------------------------------------------------------------------------------------------------#




class GradioTextOk2:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "string": ("STRING", {"multiline": True, "dynamicPrompts": True, "tooltip": "The text to be encoded."}),

            }
        }
    RETURN_TYPES = ("STRING",)
    OUTPUT_TOOLTIPS = ("A conditioning containing the embedded text used to guide the diffusion model.",)
    FUNCTION = "encode"

    CATEGORY = icons.get("hua_boy_one")
    DESCRIPTION = "Encodes a text prompt using a CLIP model into an embedding that can be used to guide the diffusion model towards generating specific images."

    def encode(self,string):
        return (string,)

class GradioTextOk3:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "string": ("STRING", {"multiline": True, "dynamicPrompts": True, "tooltip": "The text to be encoded."}),

            }
        }
    RETURN_TYPES = ("STRING",)
    OUTPUT_TOOLTIPS = ("A conditioning containing the embedded text used to guide the diffusion model.",)
    FUNCTION = "encode"

    CATEGORY = icons.get("hua_boy_one")
    DESCRIPTION = "Encodes a text prompt using a CLIP model into an embedding that can be used to guide the diffusion model towards generating specific images."

    def encode(self,string):
        return (string,)

class GradioTextOk4:

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "string": ("STRING", {"multiline": True, "dynamicPrompts": True, "tooltip": "The text to be encoded."}),

            }
        }
    RETURN_TYPES = ("STRING",)
    OUTPUT_TOOLTIPS = ("A conditioning containing the embedded text used to guide the diffusion model.",)
    FUNCTION = "encode"

    CATEGORY = icons.get("hua_boy_one")
    DESCRIPTION = "Encodes a text prompt using a CLIP model into an embedding that can be used to guide the diffusion model towards generating specific images."

    def encode(self,string):
        return (string,)

#---------------------------------------------------------------------------------------------------------------------#
class Hua_gradio_Seed:

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff})}}

    RETURN_TYPES = ("INT", "STRING", )
    RETURN_NAMES = ("seed", "show_help", )
    FUNCTION = "hua_seed"
    OUTPUT_NODE = True
    CATEGORY = icons.get("hua_boy_one")

    @staticmethod
    def hua_seed(seed):
        show_help = "https://github.com/kungful/ComfyUI_hua_boy.git"
        return (seed, show_help,)
#---------------------------------------------------------------------------------------------------------------------#
class Hua_gradio_resolution:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "custom_width": ("INT", {"default": 512, "min": 64, "max": 8192, "step": 64}),
                "custom_height": ("INT", {"default": 512, "min": 64, "max": 8192, "step": 64}),
            }
        }

    RETURN_TYPES = ("INT", "INT",)
    RETURN_NAMES = ("width", "height",)
    FUNCTION = "get_resolutions"

    CATEGORY = icons.get("hua_boy_one")

    def get_resolutions(self, custom_width, custom_height):
        width, height = custom_width, custom_height


        return (width, height)
#---------------------------------------------------------------------------------------------------------------------#

class Hua_gradio_jsonsave:
    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()
        self.type = "output"
        self.prefix_append = ""
        self.compress_level = 4

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "The images to save."}),
                "filename_prefix": ("STRING", {"default": "apijson", "tooltip": "The prefix for the file to save. This may include formatting information such as %date:yyyy-MM-dd% or %Empty Latent Image.width% to include values from nodes."})
            },
            "hidden": {
                "prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"
            },
        }


    RETURN_TYPES = ()
    RETURN_NAMES = ()
    FUNCTION = "autosavejson"
    OUTPUT_NODE = True
    CATEGORY = icons.get("hua_boy_one")
    DESCRIPTION = "保存api格式json工作流到input文件夹下"

    def autosavejson(self, images, filename_prefix="apijson", prompt=None, extra_pnginfo=None):
        filename_prefix += self.prefix_append
        full_output_folder, filename, counter, subfolder, filename_prefix = folder_paths.get_save_image_path(filename_prefix, self.output_dir, images[0].shape[1], images[0].shape[0])
        results = list()
        # results = []
        counter = 0  # 初始化计数器
        for i, image in enumerate(images):
            imagefilename = f"{filename_prefix}_{i}.png"
            results.append({
                "imagefilename": imagefilename,
            })

            # Save JSON file
            filename_with_batch_num = f"{filename_prefix}"

            json_filename = f"{filename_with_batch_num}.json"
            json_data = prompt
            json_file_path = os.path.join(full_output_folder, json_filename)
            with open(json_file_path, 'w', encoding='utf-8') as json_file:
                json.dump(json_data, json_file, ensure_ascii=False, indent=4)

            # 调试信息0+
            print(f"保存的api格式json文件位置: {json_file_path}")
            counter += 1



        return { "ui": { "images": results } }


class Hua_LoraLoader:
    def __init__(self):
        self.loaded_lora = None

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("MODEL", {"tooltip": "The diffusion model the LoRA will be applied to."}),
                "clip": ("CLIP", {"tooltip": "The CLIP model the LoRA will be applied to."}),
                "lora_name": (folder_paths.get_filename_list("loras"), {"tooltip": "The name of the LoRA."}),
                "strength_model": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01, "tooltip": "How strongly to modify the diffusion model. This value can be negative."}),
                "strength_clip": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01, "tooltip": "How strongly to modify the CLIP model. This value can be negative."}),
            }
        }

    RETURN_TYPES = ("MODEL", "CLIP")
    OUTPUT_TOOLTIPS = ("The modified diffusion model.", "The modified CLIP model.")
    FUNCTION = "load_lora"

    CATEGORY = icons.get("hua_boy_one")
    DESCRIPTION = "LoRAs are used to modify diffusion and CLIP models, altering the way in which latents are denoised such as applying styles. Multiple LoRA nodes can be linked together."

    def load_lora(self, model, clip, lora_name, strength_model, strength_clip):
        if strength_model == 0 and strength_clip == 0:
            return (model, clip)

        lora_path = folder_paths.get_full_path_or_raise("loras", lora_name)
        lora = None
        if self.loaded_lora is not None:
            if self.loaded_lora[0] == lora_path:
                lora = self.loaded_lora[1]
            else:
                self.loaded_lora = None

        if lora is None:
            lora = comfy.utils.load_torch_file(lora_path, safe_load=True)
            self.loaded_lora = (lora_path, lora)

        model_lora, clip_lora = comfy.sd.load_lora_for_models(model, clip, lora, strength_model, strength_clip)
        return (model_lora, clip_lora)


class Hua_LoraLoaderModelOnly(Hua_LoraLoader):
    @classmethod
    def INPUT_TYPES(s):
        return {"required": { "model": ("MODEL",),
                              "lora_name": (folder_paths.get_filename_list("loras"), ),
                              "strength_model": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01}),
                              }}
    RETURN_TYPES = ("MODEL",)
    FUNCTION = "load_lora_model_only"
    CATEGORY = icons.get("hua_boy_one")
    def load_lora_model_only(self, model, lora_name, strength_model):
        return (self.load_lora(model, None, lora_name, strength_model, 0)[0],)


class Hua_LoraLoaderModelOnly2(Hua_LoraLoader):
    @classmethod
    def INPUT_TYPES(s):
        return {"required": { "model": ("MODEL",),
                              "lora_name": (folder_paths.get_filename_list("loras"), ),
                              "strength_model": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01}),
                              }}
    RETURN_TYPES = ("MODEL",)
    FUNCTION = "load_lora_model_only"
    CATEGORY = icons.get("hua_boy_one")
    def load_lora_model_only(self, model, lora_name, strength_model):
        return (self.load_lora(model, None, lora_name, strength_model, 0)[0],)


class Hua_LoraLoaderModelOnly3(Hua_LoraLoader):
    @classmethod
    def INPUT_TYPES(s):
        return {"required": { "model": ("MODEL",),
                              "lora_name": (folder_paths.get_filename_list("loras"), ),
                              "strength_model": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01}),
                              }}
    RETURN_TYPES = ("MODEL",)
    FUNCTION = "load_lora_model_only"
    CATEGORY = icons.get("hua_boy_one")
    def load_lora_model_only(self, model, lora_name, strength_model):
        return (self.load_lora(model, None, lora_name, strength_model, 0)[0],)


class Hua_LoraLoaderModelOnly4(Hua_LoraLoader):
    @classmethod
    def INPUT_TYPES(s):
        return {"required": { "model": ("MODEL",),
                              "lora_name": (folder_paths.get_filename_list("loras"), ),
                              "strength_model": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01}),
                              }}
    RETURN_TYPES = ("MODEL",)
    FUNCTION = "load_lora_model_only"
    CATEGORY = icons.get("hua_boy_one")
    def load_lora_model_only(self, model, lora_name, strength_model):
        return (self.load_lora(model, None, lora_name, strength_model, 0)[0],)


class Hua_CheckpointLoaderSimple:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "ckpt_name": (folder_paths.get_filename_list("checkpoints"), {"tooltip": "The name of the checkpoint (model) to load."}),
            }
        }
    RETURN_TYPES = ("MODEL", "CLIP", "VAE")
    OUTPUT_TOOLTIPS = ("The model used for denoising latents.",
                       "The CLIP model used for encoding text prompts.",
                       "The VAE model used for encoding and decoding images to and from latent space.")
    FUNCTION = "load_checkpoint"

    CATEGORY = icons.get("hua_boy_one")
    DESCRIPTION = "Loads a diffusion model checkpoint, diffusion models are used to denoise latents."

    def load_checkpoint(self, ckpt_name):
        ckpt_path = folder_paths.get_full_path_or_raise("checkpoints", ckpt_name)
        out = comfy.sd.load_checkpoint_guess_config(ckpt_path, output_vae=True, output_clip=True, embedding_directory=folder_paths.get_folder_paths("embeddings"))
        return out[:3]

class Hua_UNETLoader:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": { "unet_name": (folder_paths.get_filename_list("diffusion_models"), ),
                              "weight_dtype": (["default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"],)
                             }}
    RETURN_TYPES = ("MODEL",)
    FUNCTION = "load_unet"

    CATEGORY = icons.get("hua_boy_one")

    def load_unet(self, unet_name, weight_dtype):
        model_options = {}
        if weight_dtype == "fp8_e4m3fn":
            model_options["dtype"] = torch.float8_e4m3fn
        elif weight_dtype == "fp8_e4m3fn_fast":
            model_options["dtype"] = torch.float8_e4m3fn
            model_options["fp8_optimizations"] = True
        elif weight_dtype == "fp8_e5m2":
            model_options["dtype"] = torch.float8_e5m2

        unet_path = folder_paths.get_full_path_or_raise("diffusion_models", unet_name)
        model = comfy.sd.load_diffusion_model(unet_path, model_options=model_options)
        return (model,)
