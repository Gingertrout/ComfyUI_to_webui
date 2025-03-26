import json
import time
import random
import requests
import shutil
from collections import Counter
from PIL import Image, ImageSequence, ImageOps
import re
import gradio as gr
import numpy as np
import torch
import threading
import folder_paths
import node_helpers 
from pathlib import Path  # 用于处理文件路径
from server import PromptServer  # 用于处理与服务器相关的操作
from server import BinaryEventTypes  # 用于处理二进制事件类型
import sys
import os 
import webbrowser
import glob
from datetime import datetime

def find_key_by_name(prompt, name):
    for key, value in prompt.items():
        if isinstance(value, dict) and value.get("_meta", {}).get("title") == name:
            return key
    return None

def check_seed_node(json_file):
    json_path = os.path.join(OUTPUT_DIR, json_file)
    with open(json_path, "r", encoding="utf-8") as file_json:
        prompt = json.load(file_json)
    seed_key = find_key_by_name(prompt, "🧙hua_gradio随机种")
    if seed_key is None:
        return gr.update(visible=False)
    else:
        return gr.update(visible=True)
        
current_dir = os.path.dirname(os.path.abspath(__file__))# 获取当前文件的目录
parent_dir = os.path.dirname(os.path.dirname(current_dir))# 获取上两级目录
sys.path.append(parent_dir)# 将上两级目录添加到 sys.path
from comfy.cli_args import args
from .hua_icons import icons


class GradioTextOk:
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
            }
        }

    RETURN_TYPES = () # 返回类型为空，因为不需要返回任何内容到前端
    FUNCTION = "output_gradio" # 定义函数名
    OUTPUT_NODE = True
    CATEGORY = icons.get("hua_boy_one")

    def output_gradio(self, images):
        
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
        return image_path_gradio   # 返回路径和文件名


# 定义图像输入输出保存路径
INPUT_DIR = folder_paths.get_input_directory()
OUTPUT_DIR = folder_paths.get_output_directory()

# 把json传递给正在监听的地址
def start_queue(prompt_workflow):
    p = {"prompt": prompt_workflow}
    data = json.dumps(p).encode('utf-8')
    URL = "http://127.0.0.1:8188/prompt"
    
    max_retries = 5  # 增加重试次数到5次
    retry_delay = 10  # 增加重试延迟到10秒
    request_timeout = 60  # 增加请求超时到60秒
    
    for attempt in range(max_retries):
        try:
            # 先检查服务器是否可用
            try:
                requests.get("http://127.0.0.1:8188", timeout=5)
            except requests.exceptions.RequestException as e:
                print(f"服务器连接检查失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                raise
            
            # 发送实际请求
            response = requests.post(URL, data=data, timeout=request_timeout)
            response.raise_for_status()  # 检查HTTP错误状态
            print(f"请求成功 (尝试 {attempt + 1}/{max_retries})")
            return  # 成功则直接返回
            
        except requests.exceptions.RequestException as e:
            error_type = type(e).__name__
            print(f"请求失败 (尝试 {attempt + 1}/{max_retries}, 错误类型: {error_type}): {str(e)}")
            if attempt < max_retries - 1:
                print(f"{retry_delay}秒后重试...")
                time.sleep(retry_delay)
            else:
                print("达到最大重试次数，放弃请求，一个工作流json数据如果随机种seed没有变化，comfyui监听地址就会不鸟你，不进行推理")
                print("可能原因:一个工作流json数据如果随机种seed没有变化，comfyui监听地址就会不鸟你，不进行推理")
                print("- 服务器未运行")
                print("- 网络连接问题") 
                print("- 服务器过载，一个工作流json数据如果随机种seed没有变化，comfyui监听地址就会不鸟你，不进行推理")
                raise  # 抛出最后一个异常

# 检索指定路径的JSON文件
def get_json_files():
    json_files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith('.json')]
    return json_files

# 刷新JSON文件列表
def refresh_json_files():
    new_choices = get_json_files()
    return gr.update(choices=new_choices)




# 开始生成图像，前端UI定义所需变量传递给json
def generate_image(inputimage1, prompt_text_positive, prompt_text_negative, json_file,):

#--------------------------------------------------------------------获取json文件

    # 构建完整的JSON文件路径
    json_path = os.path.join(OUTPUT_DIR, json_file)

    with open(json_path, "r", encoding="utf-8") as file_json:
        prompt = json.load(file_json)  #加载到一个名为 prompt 的字典中。  
        

#----------------------------------------------------------------------

    #这个函数的意义就是通过类名称定位出数字key，后续自动填写到api节点里，gradio就能方便的传递变量了。参数没写self就不会自动执行，需要调用才会执行
    def find_key_by_name(prompt, name):#这行代码定义了一个名为 find_key_by_name 的函数。prompt：一个字典，表示 JSON 数据。name：一个字符串，表示你要查找的字典名称。
        for key, value in prompt.items():#使用 for 循环遍历 prompt字典中的每一项 。key 是字典的键，value 是字典的值。 
            if isinstance(value, dict) and value.get("_meta", {}).get("title") == name:#字典-键-值；检查一个变量value是否是一个字典，并且该字典中是否包含一个键为"_meta"的子字典，且该子字典中是否包含一个键为"title"的值，并且这个值等于变量name。
                return key#相等就返回一个key数字键
        return None  # 如果遍历完所有项都没有找到匹配的值，返回 None。

   
    # 调用 find_key_by_name 函数，并将返回值赋给左边一个变量。
    image_input_key = find_key_by_name(prompt, "☀️gradio前端传入图像")
    seed_key = find_key_by_name(prompt, "🧙hua_gradio随机种") # 如果comfyui中文界面保存api格式工作流，那么是检索不到的。所以要用英文界面保存api格式工作流。
    text_ok_key = find_key_by_name(prompt, "💧gradio正向提示词")    
    text_bad_key = find_key_by_name(prompt, "🔥gradio负向提示词")   
    
    print("输入图像节点的数字键:", image_input_key)
    print("正向提示词节点的数字键:", text_ok_key)  
    print("随机种子节点的数字键:", seed_key)  

    '''双引号里是字符串哦。在 Python 中，字典的键和值可以是字符串、数字、布尔值、列表、字典等类型。
    当你使用变量名来访问字典中的键时，Python 会自动处理这些类型，包括字符串中的双引号。'''
    

    # 检查 inputimage1 是否为空图像
    if inputimage1 is None or (isinstance(inputimage1, Image.Image) and inputimage1.size == (0, 0)):
        print("inputimage1 is empty or invalid. Skipping the process.")
    else:            
        # 假设 inputimage1 是一个 PIL.Image 对象# 直接使用 PIL 的 Image 类来保存图像 gradio前端传入的图像
        if isinstance(inputimage1, Image.Image):
            inputimage1 = np.array(inputimage1)
        img = Image.fromarray(inputimage1)   
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")   # 生成时间戳      
        inputfilename = f"jieinput_{timestamp}.png" # 生成文件名
        img.save(os.path.join(INPUT_DIR, inputfilename))

    # # 使用变量名来访问字典中的键
    if image_input_key:
        prompt[image_input_key]["inputs"]["image"] = inputfilename  # 指定第一张图像的文件名    
    if seed_key:
        seed = random.randint(0, 0xffffffff)
        print(f"生成的随机种子值: {seed}")  #  一个工作流json数据如果随机种seed没有变化，comfyui监听地址就会不鸟你，不进行推理
        prompt[seed_key]["inputs"]["seed"] = seed
    # prompt["3"]["inputs"]["seed"] = random.randint(1, 1500000000000000)  # 定义种子随机数1到1500000，json的参数传递给comfyUI
    if text_ok_key:
        prompt[text_ok_key]["inputs"]["string"] = f"{prompt_text_positive}" #字典中的键[]的值是字符串，f代表字符串，占位符{}里是变量的函数的参数prompt_text_positive，就是gradio前端传入的字符串
    if text_bad_key:
        prompt[text_bad_key]["inputs"]["string"] = f"{prompt_text_negative}"
    

    
    start_queue(prompt)

    # 定义获取最新图像的逻辑方法，不调用的话是不执行的
    def get_latest_image(folder):
        files = os.listdir(folder)
        # 过滤出以 "output" 为前缀且后缀为图片格式的文件
        image_files = [f for f in files if f.startswith('output') and f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        image_files.sort(key=lambda x: os.path.getmtime(os.path.join(folder, x)))
        latest_image = os.path.join(folder, image_files[-1]) if image_files else None
        return latest_image
        
    previous_image = get_latest_image(OUTPUT_DIR)
    
    
    max_attempts = 30  # 进一步增加最大尝试次数到30次
    attempt = 0
    check_interval = 5  # 检查间隔保持5秒
    total_timeout = 300  # 总超时时间增加到300秒
    
    start_time = time.time()
    
    # 先检查ComfyUI服务是否可用
    try:
        requests.get("http://127.0.0.1:8188", timeout=5)
    except requests.exceptions.RequestException as e:
        error_msg = f"无法连接到ComfyUI服务: {str(e)}"
        print(error_msg)
        raise ConnectionError(error_msg)
    
    # 检查输出目录权限
    if not os.access(OUTPUT_DIR, os.W_OK):
        error_msg = f"输出目录没有写入权限: {OUTPUT_DIR}"
        print(error_msg)
        raise PermissionError(error_msg)
    
    while attempt < max_attempts and (time.time() - start_time) < total_timeout:
        try:
            latest_image = get_latest_image(OUTPUT_DIR)
            if latest_image != previous_image:
                print(f"检测到新图像 (尝试 {attempt + 1}/{max_attempts}, 耗时: {time.time() - start_time:.1f}秒):")
                print("旧图像路径:", previous_image)
                print("新图像路径:", latest_image)
                return latest_image
                
            remaining_time = total_timeout - (time.time() - start_time)
            print(f"等待新图像中... (尝试 {attempt + 1}/{max_attempts}, 剩余时间: {remaining_time:.1f}秒)")
            
            # 每5次尝试检查一次服务状态
            if attempt % 5 == 0:
                try:
                    requests.get("http://127.0.0.1:8188", timeout=5)
                except requests.exceptions.RequestException as e:
                    print(f"服务状态检查失败 (尝试 {attempt + 1}/{max_attempts}): {str(e)}")
            
            time.sleep(check_interval)
            attempt += 1
            
        except Exception as e:
            print(f"检测新图像时出错 (尝试 {attempt + 1}/{max_attempts}): {str(e)}")
            time.sleep(check_interval)
            attempt += 1
    
    error_msg = f"达到最大尝试次数 {max_attempts} 或总超时 {total_timeout}秒，未检测到新图像"
    print(error_msg)
    print("可能原因:")
    print("- 图像生成服务未正常运行")
    print("- 输出目录权限问题")
    print("- 网络连接问题")
    print("- 工作流执行时间过长")
    print("建议检查:")
    print("1. 确保ComfyUI服务正在运行")
    print("2. 检查输出目录权限")
    print("3. 检查网络连接")
    print("4. 简化工作流或增加超时时间")
    raise TimeoutError(error_msg)




def fuck(json_file):
    json_path = os.path.join(OUTPUT_DIR, json_file)
    with open(json_path, "r", encoding="utf-8") as file_json:
        prompt = json.load(file_json)  #加载到一个名为 prompt 的字典中。     
    def find_key_by_name(prompt, name):
        for key, value in prompt.items():
            if isinstance(value, dict) and value.get("_meta", {}).get("title") == name:
                return key
        return None 
    image_input_key = find_key_by_name(prompt, "☀️gradio前端传入图像")
    if image_input_key is None:
        image_accordion: gr.update(visible=False)
        return gr.update(visible=False)
    else:
        image_accordion: gr.update(visible=True)
        return gr.update(visible=True)
        

# 创建Gradio界面
with gr.Blocks() as demo:
    gr.Markdown("# [封装comfyUI工作流](https://github.com/kungful/ComfyUI_to_webui.git)")

    # 将输入和输出图像放在同一行
    with gr.Row():
        # 可折叠的上传图像区域 - 现在整个Accordion会根据返回值动态显示/隐藏
        image_accordion = gr.Accordion("上传图像 (折叠,有gradio传入图像节点才会显示上传)", 
                                     visible=True,  # 默认隐藏
                                     open=True)  # 但一旦显示，默认是展开的
        with image_accordion:  # 将内容放在Accordion内部
            input_image = gr.Image(type="pil", label="上传图像", height=156, width=156)
            
        output_image = gr.Image(
            type="filepath",
            label="生成的图像",
            height=256,
            width=256,            
            show_download_button=True,
            format="png"
        )
    
    with gr.Row():
        with gr.Column():
            prompt_positive = gr.Textbox(label="正向提示文本")
        with gr.Column():
            prompt_negative = gr.Textbox(label="负向提示文本")


    
    with gr.Row():
        with gr.Column(scale=3):
            json_dropdown = gr.Dropdown(choices=get_json_files(), label="选择工作流")
        with gr.Column(scale=1):
            refresh_button = gr.Button("刷新工作流")
    
    Random_Seed = gr.HTML("""
    <div style='text-align: center; margin-bottom: 5px;'>
        <h2 style="font-size: 12px; margin: 0; color: #00ff00; font-style: italic;">
            已添加gradio随机种节点
        </h2>
    </div>
    """)


    #   选择工作流  绑定change事件,  # 修改change事件绑定到整个Accordion而不是input_image
    json_dropdown.change(
        lambda x: (fuck(x), check_seed_node(x)),
        inputs=json_dropdown,
        outputs=[image_accordion, Random_Seed] 
    )
    # 绑定事件,刷新工作流按钮
    refresh_button.click(refresh_json_files, inputs=[], outputs=json_dropdown)


    with gr.Row():
        run_button = gr.Button("开始跑图")
    
        
    run_button.click(generate_image, inputs=[input_image, prompt_positive, prompt_negative, json_dropdown,], outputs=output_image)

    # 初始加载时检查工作流
    def on_load():
        json_files = get_json_files()
        if not json_files:
            return (gr.update(visible=False), gr.update(visible=False))
        default_json = json_files[0]
        return (fuck(default_json), check_seed_node(default_json))
    
    # 在 Blocks 上下文中添加加载事件
    demo.load(
        on_load,
        inputs=[],
        outputs=[image_accordion, Random_Seed]
    )

# 启动 Gradio 界面，并创建一个公共链接
def luanch_gradio(demo):
    demo.launch(share=True)

#使用多线程启动gradio界面
gradio_thread = threading.Thread(target=luanch_gradio, args=(demo,))
gradio_thread.start()

# # 等待 Gradio 界面启动
# gradio_thread.join(timeout=10)  # 等待 Gradio 启动，最多等待 10 秒

# 打开浏览器并访问 Gradio 的默认本地链接
gradio_url = "http://127.0.0.1:7860/"
print(f"Gradio 默认本地链接: {gradio_url}")
webbrowser.open(gradio_url)
