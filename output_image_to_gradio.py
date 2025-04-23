from datetime import datetime
import os
import numpy as np
from PIL import Image
import folder_paths
from .hua_icons import icons
import json # 导入 json 库

OUTPUT_DIR = folder_paths.get_output_directory()
TEMP_DIR = folder_paths.get_temp_directory() # 获取临时目录

#传递到gradio前端的导出节点
class Hua_Output:
    def __init__(self):
        self.output_dir = folder_paths.get_output_directory() # 获取输出目录
        self.type = "output"  # 设置输出类型为 "output"
        self.prefix_append = "" # 前缀附加字符串，默认为空
        self.compress_level = 4 # 设置 PNG 压缩级别，默认为 4

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "The images to save."}),  # 需要输入的图像
                "unique_id": ("STRING", {"default": "default_id", "multiline": False, "tooltip": "Unique ID for this execution provided by Gradio."}), # 添加 unique_id 输入
            }
        }

    # RETURN_TYPES = () # 不再需要通过 ComfyUI 返回路径，返回空元组
    RETURN_TYPES = ()
    FUNCTION = "output_gradio" # 定义函数名
    OUTPUT_NODE = True
    CATEGORY = icons.get("hua_boy_one")

    def output_gradio(self, images, unique_id): # 添加 unique_id 参数
        image_paths = [] # 初始化一个空列表来存储图片路径
        filename_prefix = "ComfyUI" + self.prefix_append # 使用固定前缀 "ComfyUI"

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # 获取当前时间戳，用于生成唯一的文件名
        full_output_folder, _, _, subfolder, _ = folder_paths.get_save_image_path(  # 获取完整的输出文件夹路径、文件名、计数器、子文件夹和文件名前缀
            filename_prefix, self.output_dir, images[0].shape[1], images[0].shape[0]
        )

        for (batch_number, image) in enumerate(images):# 遍历所有图像
            i = 255. * image.cpu().numpy() # 将图像数据从 PyTorch 张量转换为 NumPy 数组，并缩放到 0-255 范围
            img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8)) # 将 NumPy 数组转换为 PIL 图像对象
            file = f"output_{timestamp}_{batch_number:05}.png" # 固定文件名，使用时间戳生成唯一的文件名
            image_path_gradio = os.path.join(full_output_folder, file)  # 生成图像路径
            img.save(os.path.join(full_output_folder, file), compress_level=self.compress_level) # 保存图像到指定路径，并设置压缩级别
            print(f"打印 output_gradio节点路径及文件名: {image_path_gradio}")  # 打印路径和文件名到终端
            image_paths.append(image_path_gradio) # 将当前图片路径添加到列表中

        # 确保临时目录存在
        os.makedirs(TEMP_DIR, exist_ok=True)
        
        # 将图片路径列表写入临时文件
        temp_file_path = os.path.join(TEMP_DIR, f"{unique_id}.json")
        try:
            with open(temp_file_path, 'w', encoding='utf-8') as f:
                json.dump(image_paths, f)
            print(f"图片路径列表已写入临时文件: {temp_file_path}")
            print(f"临时目录: {TEMP_DIR}")
            print(f"图片路径列表: {image_paths}")
            
            # 验证图片文件是否存在
            for path in image_paths:
                if not os.path.exists(path):
                    print(f"错误: 图片文件不存在: {path}")
                else:
                    print(f"验证: 图片文件存在: {path}")
                    
        except Exception as e:
            print(f"写入临时文件失败 ({temp_file_path}): {e}")
            print(f"临时目录权限: {os.access(TEMP_DIR, os.W_OK)}")

        # 不再需要通过 ComfyUI 返回路径
        return ()
