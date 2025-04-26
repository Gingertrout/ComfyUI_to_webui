import subprocess
import importlib
import sys
import os
import subprocess
import platform # 移到这里，因为下面的代码需要它


# --- 改进的自动依赖安装 ---
# 映射 PyPI 包名到导入时使用的模块名（如果不同）
package_to_module_map = {
    "python-barcode": "barcode",
    "Pillow": "PIL",
    # 添加其他需要的映射
}

# 获取当前脚本目录
current_dir = os.path.dirname(os.path.realpath(__file__))
# 推断 ComfyUI 根目录 (假设 custom_nodes 在根目录下)
comfyui_root = os.path.abspath(os.path.join(current_dir, '..', '..'))

# --- 跨平台确定 Python 可执行文件 ---
python_exe_to_use = sys.executable # 默认使用当前 Python 解释器
print(f"Default Python executable: {python_exe_to_use}")

# 检查 Windows 嵌入式 Python
if platform.system() == "Windows":
    embed_python_exe_win = os.path.join(comfyui_root, 'python_embeded', 'python.exe')
    if os.path.exists(embed_python_exe_win):
        print(f"Found ComfyUI Windows embedded Python: {embed_python_exe_win}")
        python_exe_to_use = embed_python_exe_win
    else:
         print(f"Warning: ComfyUI Windows embedded python not found at '{embed_python_exe_win}'. Using system python '{sys.executable}'.")

# 检查 Linux/macOS venv Python
elif platform.system() in ["Linux", "Darwin"]: # Darwin is macOS
    venv_python_exe = os.path.join(comfyui_root, 'venv', 'bin', 'python')
    venv_python3_exe = os.path.join(comfyui_root, 'venv', 'bin', 'python3') # 有些系统可能叫 python3

    if os.path.exists(venv_python_exe):
        print(f"Found ComfyUI venv Python: {venv_python_exe}")
        python_exe_to_use = venv_python_exe
    elif os.path.exists(venv_python3_exe):
         print(f"Found ComfyUI venv Python3: {venv_python3_exe}")
         python_exe_to_use = venv_python3_exe
    else:
         print(f"Warning: ComfyUI venv python not found at '{venv_python_exe}' or '{venv_python3_exe}'. Using system python '{sys.executable}'.")
else:
    # 其他操作系统或未检测到特定环境时的回退
    print(f"Warning: Could not detect specific ComfyUI Python environment for OS '{platform.system()}'. Using system python '{sys.executable}'.")

print(f"Using Python executable for pip: {python_exe_to_use}")
# --- 结束 Python 可执行文件确定 ---


def check_and_install_dependencies(requirements_file):
    print("--- Checking custom node dependencies ---")
    installed_packages = False
    try:
        with open(requirements_file, 'r') as file:
            for line in file:
                package_line = line.strip()
                if package_line and not package_line.startswith('#') and not package_line.startswith('--'):
                    # --- 从行中提取纯包名和安装名 ---
                    package_name_for_install = package_line # 用于 pip install 的完整行
                    package_name_for_import = package_line # 用于 import 的纯包名，先假设一致
                    # 查找版本说明符的位置来分离纯包名
                    for spec in ['==', '>=', '<=', '>', '<', '~=', '!=']:
                        if spec in package_name_for_import:
                            package_name_for_import = package_name_for_import.split(spec)[0].strip()
                            break # 找到第一个就停止
                    # --- 结束提取 ---

                    # 使用提取出的纯包名查找模块名映射 (例如 Pillow -> PIL)
                    module_name = package_to_module_map.get(package_name_for_import, package_name_for_import)
                    try:
                        # 尝试导入纯模块名
                        importlib.import_module(module_name)
                        # print(f"Dependency '{package_name_for_install}' (module: {module_name}) already installed.")
                    except ImportError:
                        print(f"Dependency '{package_name_for_install}' (module: {module_name}) not found. Installing...")
                        try:
                            # 使用包含版本约束的原始行进行安装
                            subprocess.check_call([python_exe_to_use, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir", package_name_for_install])
                            print(f"Successfully installed '{package_name_for_install}'.")
                            # 尝试再次导入以确认
                            importlib.invalidate_caches() # 清除导入缓存很重要
                            importlib.import_module(module_name) # 使用纯模块名再次尝试导入
                            installed_packages = True
                        except subprocess.CalledProcessError as e:
                            print(f"ERROR: Failed to install dependency '{package_name_for_install}'. Command failed: {e}")
                            print("Please try installing dependencies manually:")
                            print(f"cd \"{comfyui_root}\"")
                            # 建议命令保持不变，因为它读取整个文件
                            print(f"\"{python_exe_to_use}\" -m pip install -r \"{requirements_file}\"")
                        except ImportError:
                             # 调整错误信息，使其更清晰
                             print(f"ERROR: Could not import module '{module_name}' even after attempting to install package '{package_name_for_install}'. Check if the package name '{package_name_for_install}' correctly provides the module '{module_name}'.")
                        except Exception as e:
                            print(f"ERROR: An unexpected error occurred during installation of '{package_name_for_install}': {e}")
    except FileNotFoundError:
         print(f"Warning: requirements.txt not found at '{requirements_file}', skipping dependency check.")
    except Exception as e:
        print(f"ERROR: An unexpected error occurred while processing requirements: {e}")


    if installed_packages:
        print("--- Dependency installation complete. You may need to restart ComfyUI. ---")
    else:
        print("--- All dependencies seem to be installed. ---")


# 自动检测并安装依赖 (移到文件顶部执行)
requirements_path = os.path.join(current_dir, "requirements.txt")
check_and_install_dependencies(requirements_path)

# --- 结束自动依赖安装 ---

from .hua_word_image import Huaword
from .hua_word_models import Modelhua
# Removed GradioInputImage, GradioTextOk, GradioTextBad from gradio_workflow import
from .mind_map import Go_to_image
from .hua_nodes import GradioInputImage, GradioTextBad
from .gradio_workflow import GradioTextOk
# Added GradioInputImage, GradioTextOk, GradioTextBad to hua_nodes import
from .hua_nodes import Hua_gradio_Seed, Hua_gradio_jsonsave, Hua_gradio_resolution
from .hua_nodes import Hua_LoraLoader, Hua_LoraLoaderModelOnly,Hua_CheckpointLoaderSimple,Hua_UNETLoader
from .hua_nodes import GradioTextOk2, GradioTextOk3,GradioTextOk4
from .hua_nodes import BarcodeGeneratorNode, Barcode_seed
from .output_image_to_gradio import Hua_Output
from .output_video_to_gradio import Hua_Video_Output # 添加视频节点导入
NODE_CLASS_MAPPINGS = {
    "ComfyUI_hua_boy": Huaword,
    "小字体说明：我是comfyui_hua_boy的model": Modelhua,
    "hua_gradioinput": GradioInputImage,
    "hua_gradiooutput": Hua_Output,
    "brucelee": Go_to_image,
    "hua_textok": GradioTextOk,
    "hua_textok2": GradioTextOk2,
    "hua_textok3": GradioTextOk3,
    "hua_textok4": GradioTextOk4,
    "hua_textbad": GradioTextBad,
    "hua_gradio_seed": Hua_gradio_Seed,
    "Hua_gradio_resolution": Hua_gradio_resolution,
    "Hua_LoraLoader": Hua_LoraLoader,
    "Hua_LoraLoaderModelOnly": Hua_LoraLoaderModelOnly,
    "Hua_CheckpointLoaderSimple": Hua_CheckpointLoaderSimple,
    "Hua_UNETLoader": Hua_UNETLoader,
    "BarcodeGeneratorNode": BarcodeGeneratorNode, # 使用新的类名
    "Barcode_seed": Barcode_seed,
    "hua_gradio_jsonsave": Hua_gradio_jsonsave,
    "hua_gradio_video_output": Hua_Video_Output # 添加视频节点类映射
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ComfyUI_hua_boy": "🌵布尔图片Boolean_image",
    "小字体说明:我是comfyui_hua_boy的model": "🌴布尔模型Boolean_model",
    "hua_gradioinput": "☀️gradio前端传入图像",
    "hua_gradiooutput": "🌙图像输出到gradio前端",
    "brucelee": "⭐思维导图",
    "hua_textok": "💧gradio正向提示词",
    "hua_textok2": "💧gradio正向提示词2",
    "hua_textok3": "💧gradio正向提示词3",
    "hua_textok4": "💧gradio正向提示词4",
    "hua_textbad": "🔥gradio负向提示词",
    "hua_gradio_seed": "🧙hua_gradio随机种",
    "Hua_gradio_resolution": "📜hua_gradio分辨率",
    "Hua_LoraLoader": "🌊hua_gradio_Lora加载器",
    "Hua_LoraLoaderModelOnly": "🌊hua_gradio_Lora仅模型",
    "Hua_CheckpointLoaderSimple": "🌊hua_gradio检查点加载器",
    "Hua_UNETLoader": "🌊hua_gradio_UNET加载器",
    "BarcodeGeneratorNode": "hua_条形码生成器", # 使用新的显示名称，与节点文件一致
    "Barcode_seed": "hua_条形码种子",
    "hua_gradio_jsonsave": "📁hua_gradio_json保存",
    "hua_gradio_video_output": "🎬视频输出到gradio前端" # 添加视频节点显示名称

    
}

jie = """
➕➖✖️➗  ✨✨✨✨✨        ✨  ⭐️✨✨✨✨✨✨    ➖✖️➗ ✨✨           ✨✨   ✨   ➖✖️➗  ✨
⣿⣟⣿⣻⣟⣿⣟⣿⣟⣿⣟⣿⣟⣿⣟⣿⢿⣻⣿⢿⡿⣿⢿⡿⣿⢿⡿⣿⢿⡿⣿⡿⣿⡿⣿⣿⢿⣿⡿⣿⣿⣿⢿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⣟⣗⣽⣪⠕⡜⡜⢆⠏⡖⡡⡑⢆⢑⠜⢌⠂⡇⢎⠂⡂⠂
⣿⣯⣿⣽⣯⣷⡿⣷⢿⡷⣟⣯⣿⢷⣿⣻⡿⣿⣽⡿⣟⣿⣟⣿⢿⣻⣿⢿⡿⣿⣻⣿⣻⣿⢿⣾⣿⣟⣿⡿⣷⣿⡿⣿⣾⡿⣾⣷⣿⣷⣿⢿⣾⣿⣽⣿⣽⣿⣽⣿⣻⣿⣻⣿⣻⣿⡿⣿⡿⣟⣿⣾⣿⡽⣿⢿⢱⡯⣷⠯⣚⠜⢌⢊⠄⢕⢸⢸⠨⢊⠢⠢⡑⢗⡇⡃⡂⡂⢂⠡
⣿⣾⣳⣿⢾⣯⡿⣟⣿⣻⣿⣻⣽⡿⣯⣿⣻⣟⣷⣿⣿⣻⣽⡿⣿⣟⣿⣟⣿⣿⣻⣽⣿⣽⣿⣟⣷⣿⣟⣿⡿⣷⣿⣿⣷⣿⣿⢿⣾⣿⣾⣿⣿⣯⣿⣿⣽⣿⣟⣿⣿⢿⣿⣿⣿⢿⣿⣿⣿⣿⡿⣿⢮⢻⢚⢎⢮⢫⡏⡇⡗⢅⠕⡐⢍⠌⡐⡐⠌⠢⡘⡐⢬⠣⢊⢐⠐⠄⡁⠂
⣿⣷⣻⣾⢿⣯⣿⣟⣿⣽⣯⣿⣯⣿⢿⣽⣟⣯⣿⡷⣿⣻⣯⣿⣿⣽⣿⣽⣿⣽⣿⣻⣽⡿⣷⣿⢿⣯⣿⣟⣿⣿⣻⣾⡿⣷⣿⣿⡿⣯⣿⣿⣾⡿⣿⣾⣿⣟⣿⣟⣿⣿⣿⣷⣿⣿⣿⣿⣯⣷⣿⡿⡪⣣⡱⡱⡱⡘⡌⢎⠜⡐⡡⠨⡐⡐⡐⠠⠡⢡⢘⠜⠄⢕⢐⠡⠡⡁⡊⠄
⡿⣞⣷⣻⣻⡿⣾⣯⡿⣷⢿⡷⣿⣾⡿⣿⣽⡿⣷⣿⢿⣻⣯⣷⣿⡷⣿⣷⢿⣻⣾⣿⢿⡿⣟⣿⣿⣻⣽⣿⣻⣽⣿⣟⣿⣿⣯⣷⣿⣿⣿⣷⣿⣿⡿⣿⣽⣿⡿⣿⣿⣿⣽⣿⣟⣿⣯⣷⣿⣿⢿⣳⣽⣿⣾⣿⣱⠥⡣⣕⢌⢢⠃⠅⡂⢂⠢⠡⡃⢂⠅⡊⠌⡂⡂⠌⡐⠄⠌⡐
⣿⢿⣺⣷⣻⡿⣿⢾⡿⣟⣿⢿⣻⣾⣿⣻⣷⣿⢿⣽⣿⢿⣻⣯⣷⣿⣿⣻⣿⢿⣿⣽⣿⣿⣿⢿⣯⣿⣿⣻⣿⣟⣯⣿⣿⣷⣿⡿⣟⣯⣷⣿⣷⣻⡻⣟⢿⣟⣿⣿⣿⣾⣿⣿⣿⣿⣿⣿⡿⣿⣿⣿⣿⣿⢿⡺⡺⡹⡸⡸⠢⡱⠡⡑⠄⠅⡊⠨⠠⡁⡂⡂⠅⢂⠄⠅⢂⠂⡁⠄
⣿⡿⡽⣾⣽⢿⣻⡿⣿⣟⣿⡿⣟⣿⡾⣿⢷⣿⢿⣻⣽⣿⣿⣻⣯⣿⣾⣿⣻⣿⣯⣿⣷⣿⣻⣿⣟⣯⣿⣟⣯⣿⣿⢿⣷⣿⣷⣿⣿⣿⣿⣿⣻⣷⣿⣾⣷⣯⣯⣿⣽⣻⢿⣷⣿⣿⣽⣿⣿⢿⣯⣿⣿⣿⢳⢹⢸⢌⠆⢕⡑⡱⣁⠢⠡⢁⠂⠅⡁⢂⢂⢔⠨⢐⢑⠨⢀⠂⡐⢀
⣿⣻⣯⣿⣾⢿⣟⣿⣯⣿⢷⣿⣿⣻⣿⣻⣿⣻⣿⢿⣿⣽⣾⡿⣿⣽⣷⣿⢿⣽⣾⣿⣾⣿⣻⣯⣿⣿⣟⣿⣿⢿⣻⣿⣿⣽⣾⣿⣟⣯⣷⣿⣿⡿⣟⣿⣽⣿⣿⣿⢿⣿⣿⣾⣷⣟⣟⡿⣿⣿⣿⣿⡿⣯⡣⡳⣹⠰⡱⡱⡪⡪⣪⠎⢌⢐⠈⠄⡂⠢⠡⠐⡈⠄⢂⢐⢀⠂⡐⡀
⣿⣻⣞⣷⢿⣻⣟⣯⣷⣿⢿⣻⣾⣿⣽⣿⣽⣿⣽⣿⣯⣿⣽⣿⢿⣯⣿⣾⣿⡿⣿⣽⣾⣿⣻⣿⣯⣷⣿⣿⢿⣿⣿⣿⣽⣿⣟⣿⡿⣿⣿⣿⣻⣿⣿⣿⣿⣿⣿⣾⣿⣿⣿⡿⣿⣿⢿⣻⣗⣯⣻⣽⡽⡧⡣⣫⢾⡸⡌⡪⠪⠪⡘⡜⡐⠠⠨⠐⢄⠅⠅⢌⠐⡈⡐⠠⠐⡀⠂⡀
⣿⣳⣻⣿⢿⣻⣟⣿⣯⣿⢿⣟⣿⡾⣿⡾⣿⡾⣟⣷⣿⣯⣿⣟⣿⣿⣽⡿⣷⣿⣿⣟⣯⣿⣯⣷⣿⣟⣯⣿⡿⣿⢾⡿⣽⣷⣿⢿⣿⢿⣷⣿⣿⢿⣿⣻⣿⣽⣾⣿⣿⣿⣿⣿⣿⣿⣿⡿⣾⡷⣵⣯⢿⣝⢜⣞⢗⡽⡐⡌⡪⠪⡘⡜⣬⣨⠊⠜⢠⠡⢁⢂⢐⢀⢂⠁⡂⠄⡁⡂
⣿⣽⣞⣟⣿⣻⣿⣽⣾⣿⣻⣿⣯⣿⡿⣿⣻⣿⡿⣿⣷⡿⣷⣿⢿⣷⣿⡿⣿⣻⣾⣿⢿⣻⣽⡿⣝⢏⡏⡗⡝⡕⡏⠯⡛⡞⣽⣻⢽⡻⣟⢷⡻⡯⣿⢿⣿⣿⣿⣿⣿⣿⣾⣿⣿⣿⣷⢿⣽⣽⢼⣾⣗⣯⣗⢷⢝⡾⣕⣎⢌⢎⣮⣫⣞⡮⡊⠜⠨⠨⢀⠂⡐⠠⠐⠀⠂⠄⠂⡀
⣿⢷⡯⡾⣷⡿⣷⡿⣷⣿⣻⣷⡿⣷⣿⡿⣟⣯⣿⣿⢷⣿⣿⢿⡿⣿⣾⣿⣿⡿⣟⣿⣿⢿⡫⡞⠕⠣⡑⠅⠕⡨⡈⠪⡨⠨⡂⠪⡑⡩⡘⡌⡪⠪⠪⠫⡳⡻⣽⢿⣷⣿⣿⣿⣿⣯⣿⡿⣽⣟⢮⣟⣯⣿⣞⡵⣻⢮⢗⣗⣗⣽⣺⢺⢪⠸⠨⠨⠨⠈⠄⢂⠄⠡⠈⡈⠄⠡⠐⠀
⡟⣟⣿⡿⣟⣿⣟⣿⢿⣽⡿⣷⣿⣿⣯⣿⣿⡿⣿⣽⣿⣿⣻⣿⣿⢿⣷⣿⣷⣿⣿⢿⢝⠕⡡⠂⠅⠕⡐⠡⡁⠢⠨⠨⡐⠡⠊⠌⢌⠢⡑⠄⠕⡑⣑⢑⠔⢌⠌⡝⢽⣻⢿⣿⣻⣿⣿⣯⣷⣿⢵⣿⣿⣾⣷⣯⣳⢯⣻⣪⣞⢮⠪⠪⡘⠬⠨⡈⠌⡈⢄⠧⠊⠠⢁⠀⠄⠡⢈⠆
⣿⡼⣜⡝⣟⢿⣯⣿⡿⣟⣿⡿⣷⣿⣽⣿⣾⣿⣿⣻⣽⣾⣿⣿⣾⣿⣿⣷⡿⣟⠞⢍⠢⠨⡐⠡⠡⢑⠠⢁⠂⡡⢈⠢⠨⠨⢈⠊⠄⡑⠨⢐⠁⡊⠔⡐⠌⢄⢑⠌⠔⡨⢙⢟⣿⣿⣿⣯⣿⣿⡳⣿⣯⣿⣿⡷⣯⡳⣣⣗⢵⡱⣑⡑⢕⠎⠌⢄⠑⡨⢮⢇⠡⢈⠠⣐⢌⠐⠄⢂
⣿⣯⣷⡿⣜⣕⢗⡻⡿⣿⢿⣿⢿⣽⣿⣾⣿⣾⢿⣻⣿⡿⣿⣾⣿⣽⣾⢿⠝⢅⠕⡡⠊⠌⠄⢅⢑⠐⡈⡀⢂⠐⠠⠂⠡⠨⠀⠌⡐⠠⠑⡐⠐⡈⡐⠨⠨⢐⠠⢈⢂⠂⠅⡂⠝⣽⣿⣿⣽⣿⡽⣽⣿⣿⣿⣿⣣⡯⣳⡳⣻⡺⡑⢅⠭⠅⡕⡁⡂⠪⡱⠱⢈⢒⢑⢃⠅⡅⡁⢄
⣿⢷⣿⣟⣿⢾⣵⣽⣺⡪⣟⢿⢿⣟⣷⣿⣾⣿⣿⣿⢿⣿⢿⣻⣾⣿⠫⡣⠡⡑⢌⢐⠅⠅⠕⡐⡐⢐⢀⠂⡂⠌⢂⢁⠁⡂⠁⡂⠐⡈⢀⠂⠁⠄⠂⠡⠨⢀⠂⡐⠀⠌⢐⠠⠁⡊⢿⢿⣽⣿⡽⣺⣿⣿⣾⣿⣗⡯⡷⡯⡳⢏⠪⠨⢐⠕⡐⠔⡘⣌⣆⢧⠳⢵⢦⢗⠱⠐⠠⡺
⣿⣿⣾⣟⣾⡯⣿⣻⣿⣽⣺⣪⣫⡫⣟⣯⣿⣾⣿⣾⣿⣿⣿⣿⢿⠱⡑⢌⠪⡐⡡⢂⢊⠌⠌⠄⡂⡂⡂⠌⡐⠈⠄⡀⠂⠄⠁⠄⠂⡀⠂⡈⠐⠈⡀⠁⠌⡀⢂⠀⠂⡈⠠⢀⠡⠐⢈⢻⣿⣿⡯⣯⣿⣿⣿⣿⢾⢽⢝⢮⣪⡢⡣⡵⢐⠅⡢⡑⡹⡚⡘⡝⢌⢎⢏⠰⡁⢌⢐⣞
⣿⣿⣿⣯⣷⣿⣿⡿⣿⡯⣯⣷⣿⣿⣪⢞⢮⡻⣾⣯⣿⣷⣿⢿⢹⢘⢌⠢⡑⢔⠨⢂⠢⠡⠡⡁⠢⢐⠠⢁⠂⠅⠡⠀⠅⠨⠐⡀⠁⠄⠂⠠⠈⠠⠀⠌⠀⠄⠂⡀⢁⠀⠄⠠⠐⠈⡀⠂⣟⣿⣯⡺⣿⣿⣷⣿⡿⡭⣯⣳⣳⡳⣜⣞⢔⢁⡢⠂⣆⢣⢇⢣⡲⣕⢴⡡⠄⡅⡢⣪
⣿⣟⣿⣯⣿⣿⣿⣿⣿⣟⣷⡿⣟⣿⣽⣟⣗⣿⣞⢮⡻⡾⣟⢏⢢⠱⡐⢅⠪⡐⢅⢑⠌⢌⢂⢊⠌⠢⡈⡂⠅⢅⠡⠁⠅⠌⠄⢂⠡⠈⠄⠁⠄⠁⡐⢀⠁⠄⠂⠠⠀⠄⠂⠀⠂⠁⡀⠂⠪⣿⣷⢫⣿⣿⣿⣟⡯⣻⢕⡗⡷⡽⣵⡫⣏⣗⡽⣱⡳⡽⣝⡷⡭⠢⢕⠪⡰⡜⡎⡖
⣿⡿⣽⣿⢾⣝⡿⡾⣿⣽⣿⣿⣿⡿⣏⣟⢮⣟⣿⣟⡾⣝⣎⠪⠢⡑⢌⠢⡑⢌⠢⠡⡊⢔⢐⠡⡨⢨⢐⢐⠡⢂⠌⠌⠄⠅⠌⢔⠠⠁⠂⡁⠄⠁⠄⢂⠂⠐⠀⠂⠐⠀⠄⠁⡀⠁⡀⢈⠈⣿⣻⡪⡾⣟⢟⡟⡽⡪⡗⠧⣙⢽⣪⢞⡷⡳⣝⡵⡿⡽⣳⣻⣺⢸⡢⠑⡌⡎⣎⢇
⣿⣟⣿⡿⣯⢿⡽⣿⣿⡯⣟⣟⣿⣻⡳⡽⡵⣻⡯⣿⣻⡽⡢⡃⢇⠕⡡⠱⡨⠢⡑⡑⢌⢂⠢⡑⠌⡂⡢⢂⠕⡐⠌⠌⠌⠌⢌⢂⢊⠈⠄⠠⢀⠁⡈⠄⢈⠀⡁⠈⠄⠁⠠⠀⠠⠀⠠⠀⠐⡽⣟⢜⠸⡈⠪⠨⢂⠕⡘⠌⢌⢳⡳⡝⣎⢓⠜⡮⣯⢯⣗⡯⣞⢎⠗⢕⢧⣣⢇⢗
⣿⣟⣾⣿⣻⡯⣿⣽⣾⣿⣻⣞⣾⢗⡯⡯⣺⢝⡯⣗⡯⣗⢕⠸⡐⡱⢨⢑⢌⢊⢢⠡⡑⡐⢅⢊⠌⡢⠨⡂⢌⠢⠡⡑⡡⠡⡑⡐⡀⢂⠁⡐⠀⠄⠠⠀⠄⠠⠀⡈⠄⢈⠠⠀⠄⠐⠀⠈⡀⡪⡹⠠⡑⠌⢜⢈⠢⡂⡪⣘⢰⡱⣹⡪⡢⡢⢇⡯⣯⡻⡮⡯⡯⣣⢢⢕⣟⢾⡕⢵
⣟⣞⢿⢽⢷⣟⣿⣺⣿⣯⣷⡻⣞⡯⣞⡽⡵⣫⢟⡮⣻⣜⢔⢕⠱⡘⢔⠱⡨⠪⡐⢕⢌⢊⢢⢑⢌⢢⢑⢌⠢⡡⡃⢆⢊⠌⢔⠐⡀⢂⠐⡀⠅⠌⡂⠅⠂⡂⠁⠄⠨⠀⠄⠠⠀⠠⠀⢁⠀⢎⠪⠨⡪⢪⢪⠢⠣⡪⢪⢪⢣⢣⡳⣕⡵⣕⣷⣫⢷⢯⢯⢯⡫⣗⢽⡸⣺⢽⡎⡇
⣣⢳⡹⡪⣗⡯⣟⣯⣿⡷⣗⡯⣳⢯⡳⡽⣝⢞⡽⣺⢵⣳⡱⡰⡑⡕⡱⡱⡱⡱⡱⡱⡘⡜⢜⢌⢎⢢⠱⡰⡑⢬⢨⢢⢑⢅⢅⢂⠂⡂⠡⠠⠡⠑⠠⠁⡂⠂⠅⠌⠌⠨⠨⠐⠀⠠⠀⢰⢽⡵⡽⡸⡨⡊⡎⡪⡨⡪⡪⠪⡪⡪⣚⢮⡺⡕⣗⢹⢝⡽⣣⡣⡝⡼⡕⡽⡸⡯⡷⡽
⡕⣇⢧⣫⣚⢮⢳⢕⡯⣟⣗⢯⡳⣝⢮⡫⡮⣳⢽⢵⡳⡳⣕⢕⠕⡌⡆⡧⡳⡱⡱⡑⢕⢑⢅⢕⢐⠅⡕⢌⢪⠢⡣⡱⡱⡱⡐⠔⡐⠨⢈⢀⢂⠈⡀⠄⠐⠈⡀⠂⡁⠡⠡⠡⢁⠠⠀⢵⣫⡯⡯⡪⢪⠺⡸⡸⡘⢔⢅⠇⡕⡵⣝⡵⡝⡎⡕⡭⡕⡭⡪⡪⡊⡎⡎⡢⠪⡯⡯⣟
⢜⢜⡜⣜⢔⡳⣕⢯⢯⣳⢽⣪⢯⡳⣽⡪⡯⣎⣯⡳⡽⣹⢪⢧⡣⡱⡸⡪⣪⢪⢪⢸⢸⢨⢢⠢⡣⡱⡸⢸⢰⢱⣱⢵⣳⡳⡵⣕⢬⢨⢐⢐⠄⢅⢂⠂⠅⢅⠢⡑⡨⡘⢌⠪⡀⠠⡈⡺⡸⡪⡻⡜⡢⡣⣣⡪⡪⡪⡳⡱⢙⢮⣣⢫⢞⢼⢸⢕⢽⡪⡳⡘⡔⢅⢇⠪⠨⣻⢽⢽
⢹⡱⡹⡪⡳⡹⣸⡹⣕⡯⣯⢞⡮⣫⣞⢞⣺⢺⡺⣪⢳⢕⢽⢕⣗⢕⢵⢹⢜⢎⢇⢗⢕⢕⢕⢕⢕⢜⢜⢼⢼⢵⢯⣳⣳⣝⣞⢮⡳⣝⢮⡲⣕⢅⡆⡕⡩⠢⡑⡌⢆⠪⢢⢑⢌⡜⡄⠂⠌⢎⢎⢎⢇⢇⠇⡣⡱⠨⡂⢇⠹⡪⡮⣝⡕⡏⡮⡪⡧⣗⢕⢅⢇⢕⠜⠕⠡⡹⣹⢽
⢵⢳⡳⡣⡇⡇⣇⡞⣮⣺⣳⣻⣺⡳⡵⣫⢞⡵⣝⡎⣗⢽⡹⡕⣕⢇⡗⣝⢎⢧⢫⢎⢇⢗⢕⢵⢵⢽⢽⢽⢽⢽⢽⣺⣺⡪⡮⡳⣝⢮⢧⡳⣕⢗⢵⢝⢎⢗⢵⢕⢵⡹⡜⡎⡕⡎⠄⢌⢐⠱⡨⢺⠘⢌⢊⠢⡃⠕⢌⠄⢸⢘⢎⢮⡺⢜⢆⢝⣽⡳⡝⡜⡜⡔⣑⢁⢐⢐⢈⢌
⡜⡵⣫⢇⢧⡳⡵⣝⡮⣞⢮⡲⣳⢽⢝⣮⣻⡪⣞⢞⡜⡮⡎⡧⡣⣳⢽⢜⢮⡣⣗⡵⣝⡮⡯⣫⢗⡯⡯⡯⡯⣯⣳⣳⡳⣝⢮⢫⢎⢗⢵⡹⣜⢝⢎⢗⡝⣕⢕⡕⣇⢧⢣⢣⢣⠃⠅⡂⡂⠕⡈⡢⢑⢡⠨⡊⡎⢕⢐⠅⢢⠡⡑⡘⣎⢇⠣⡑⢗⠏⢇⠣⠣⡑⢌⢢⢑⢌⢆⢎
⡪⡪⡪⢭⡳⢽⢕⢧⢯⢞⡵⡫⣗⣯⡻⣮⣺⣺⢾⣷⢝⢜⢇⣗⢝⢼⣝⢽⢕⡯⣳⢝⣞⢮⣻⡺⣽⡺⡽⡽⣝⢮⢞⡮⣞⢮⢎⡗⡭⡳⡱⣕⢕⢧⢫⢎⢞⡜⣕⢝⡜⡜⡜⡜⡜⡌⠔⡰⠨⢊⠔⠨⡢⢡⠣⡢⠱⡐⢔⢐⠰⡑⢕⠔⢕⡥⢑⠠⡱⡠⠁⠌⠨⡘⡜⣜⢔⢽⢸⡱
⡇⡇⡏⡎⡎⡇⡏⡮⡪⣟⢮⡻⣵⣳⣻⣵⣳⣯⣿⣾⢣⣏⢧⢳⡹⡪⢮⣫⡳⡽⡵⣻⡪⡯⣞⢮⣳⢽⢽⢝⡮⡯⣳⢝⡮⡳⡵⡹⡪⡳⡹⣸⢱⢝⢎⢧⢳⢹⡸⡜⡜⡎⢎⢪⢪⠪⡈⡢⡹⣆⢪⢸⢮⣒⡗⢌⠧⡪⡪⡢⠈⡎⢌⠌⢎⡮⡘⡔⣑⢐⢁⠂⡡⣚⢮⢺⢜⢕⡗⣕
⢜⣜⢮⡪⡺⡜⡼⣸⡹⣜⡳⣝⣞⢼⣺⣪⣟⡽⡻⡽⡺⣺⣗⢗⣝⢮⢣⣗⢽⣪⣻⡪⡯⣫⣞⢗⣗⢯⣳⡫⣞⡽⣪⢟⣞⡝⣎⢧⢳⡱⡝⣆⢧⢣⢣⡣⣫⢪⡪⡪⡪⡪⢪⢊⢆⡃⡪⣸⢮⣣⢳⢝⣽⣒⢯⢘⢌⠪⢜⢐⠠⣩⣢⢳⠳⡕⡍⡊⡒⡑⡑⡑⠌⠜⡘⠱⠱⢕⢽⢸
⣗⢵⡳⣹⢸⢜⢎⢷⢝⡮⣺⢵⡳⡝⣞⡼⡺⡪⡳⡝⣜⢯⣯⡳⡕⣗⢵⡳⣝⢮⡺⣺⢽⢵⣳⡫⣞⣵⡳⣝⣗⡽⡽⣕⣗⢽⡪⡎⡮⡺⡸⡪⣪⢪⢣⡣⡳⡱⡕⡕⢕⠜⡌⢆⢕⣵⡯⣯⣳⡼⣔⢖⡳⡵⡹⡆⢆⠪⡸⡲⡸⢘⠨⢐⠨⣪⡂⠢⡑⡡⠐⠨⡨⡈⣐⠡⠡⠈⠠⠁
⢗⡳⣝⢞⣵⢝⡗⣯⣳⣫⢗⣗⢽⣝⣞⢮⢫⡪⣫⢧⣳⡻⡮⡯⣺⢺⢮⡺⣕⢯⡺⡵⣫⢗⣗⢽⡳⣵⡫⣗⣗⢽⣺⢵⢽⢕⡇⣏⢎⡇⡏⡎⡎⣎⢮⢺⢸⢱⠱⡘⡌⡪⠨⢪⣻⣻⢛⢟⠫⡫⣓⢕⢽⢜⣺⣝⠆⡃⡃⠕⡐⠡⡈⠂⠅⡣⡣⢑⠨⢬⢆⠁⠀⠂⡀⡈⠄⢌⡰⡠
⣟⣞⠽⡽⣾⣻⣺⢮⡪⣺⡽⣪⡳⣕⢿⣳⢽⣮⣟⡧⣗⣟⢎⢎⠮⡎⢇⡳⣕⢗⣝⢮⣳⡫⣞⢽⡺⣕⢯⣳⢳⣫⣞⢽⢵⣫⢞⢜⡜⣜⢜⢎⢎⢎⢎⢮⢪⠪⡪⡘⢔⠡⡑⠁⠀⠀⠠⠀⠂⠠⠀⠐⠈⠀⠀⠠⠁⠠⠀⠌⠠⠑⢀⠡⠐⢸⢱⢠⢏⠃⡀⠐⠀⠁⢂⠺⣹⢳⠹⠩
⡷⣣⢯⣞⡼⡷⣿⣽⡎⣗⢯⡳⡝⣎⣟⣽⢽⣺⡷⣽⡺⣮⢣⡫⣣⡣⣧⡳⡵⣝⢼⢕⢗⡽⣪⢗⢯⡺⣝⢮⢯⡺⣪⢯⢳⡳⣝⢜⢜⢜⢜⢜⢜⢜⢕⢕⢕⠱⡐⢅⠕⠨⠐⠀⠐⠀⠀⡀⠀⡀⠠⠀⠀⠄⠂⠀⠀⠀⠀⠀⠄⠁⠔⡨⡐⠸⡸⡀⢌⠪⡠⡐⡄⡪⠰⢑⠈⠤⢒⠠
⡯⡯⣳⡳⡽⣽⡿⣯⣷⡯⣗⢵⢹⢢⢳⡵⣯⢷⣻⢮⣻⣞⡯⣿⣳⡿⣷⣻⣟⣮⣳⢹⢵⢝⢮⣫⡳⣝⢮⢯⡺⣪⢗⢽⢕⡯⣺⢸⢱⢱⢱⢣⢳⢱⢱⠱⡨⢊⢌⢂⢊⠌⠐⠀⠄⠀⢀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠀⠀⠠⠁⠌⡐⠌⡈⢎⢂⠕⢐⢈⠠⡐⡠⠡⡠⢡⠡⡠⡀
⢳⢱⢕⢯⡫⡞⣿⣻⢾⣽⡣⣗⢵⢱⠹⡯⣟⣿⢽⣻⣽⣞⣯⣿⣺⡯⣷⣟⡾⣗⡷⡝⣎⢏⡧⣳⢝⢮⡳⡳⣝⢮⡫⣗⢯⣞⡕⡇⡇⡇⡣⡱⠡⡣⢡⠱⠨⡂⠢⢂⠂⡐⠀⠐⠀⠈⠀⠀⠀⠂⠀⠂⠁⠀⠀⠈⠀⠀⠄⠂⠐⠀⢑⢆⢇⡇⣇⢇⢇⢇⢇⢇⡳⡸⡱⡱⡱⣱⢱⢱
⣣⣳⣱⡳⣕⣯⡷⣟⣿⣞⡯⣪⢣⢳⢱⡻⡯⡿⡽⣻⡺⡽⣺⡳⡽⣝⢵⡳⡽⣕⢯⡺⡪⣳⢹⡪⣏⢗⡽⣹⡪⣗⡽⣪⣗⢵⢝⡜⡜⢌⢪⢨⠪⡨⡂⡣⠑⠌⠌⠄⠂⠠⠀⢀⠈⠀⠁⠈⢀⠐⠀⡀⠀⠄⠈⠀⠀⠠⠀⠀⠂⠈⠸⡸⡱⡕⣇⢯⢪⡣⡳⡕⡕⣇⢗⢝⢜⢼⢸⢱
⣷⣻⣞⣟⣯⡷⡿⡯⡷⣻⢺⢜⡪⣪⡪⣞⣝⢮⢯⣺⡪⣟⢮⡺⣝⢮⡳⣝⢞⢎⡗⠕⠈⡎⡧⡫⡮⡳⣝⢮⡫⣞⢮⡳⣕⢯⡣⡣⡪⡊⢆⢕⢑⠌⠢⠨⠨⢈⠐⠀⠌⠠⠀⢀⠀⠈⢀⠈⠀⠀⠄⠀⠂⠀⠂⠀⠌⠀⠀⠁⠀⠂⠁⢎⢎⢎⠮⡪⡣⡳⣱⢹⢜⢜⡜⡎⡇⡇⡗⡕
⣟⣗⢯⢯⡺⣝⣝⢮⢯⢮⡳⣣⢯⡺⣜⢮⢮⢳⡳⡵⣝⢮⢳⢝⣎⢧⣫⢺⡪⣳⡙⠠⠁⡪⢸⢸⢪⡳⡕⡧⡫⢮⢳⡹⡪⣇⢗⢕⢌⠪⡂⠕⡠⠡⠡⢁⠁⠄⠀⠅⡈⠀⠄⠀⡀⠁⠀⠀⠈⠀⠀⠄⠀⠐⠀⠁⠀⠀⠁⠀⠁⠀⠂⢹⢸⢬⢘⢜⢜⢜⢜⢼⢸⢱⢱⡱⢕⢕⡕⡕
⢷⢕⢯⡺⣪⢧⡳⣝⢮⡳⣝⢮⡺⣪⢮⡳⣝⣕⢗⢵⢳⡹⡪⡧⡳⣕⣕⢧⡫⣎⠊⠄⠂⢪⢘⢔⢑⢕⢕⢕⢝⢜⠜⡌⢎⠎⡎⡇⡊⠌⠄⠅⠂⡁⠁⡀⠄⠂⠁⠠⠀⠠⠀⠄⠀⠠⠀⠁⢀⠐⠀⠠⠈⠀⠐⠀⠈⠀⠈⠀⠈⠀⠠⠀⡇⡇⡏⣎⢎⢎⢎⢪⠪⡪⡣⡪⡣⡣⡣⣣
⡳⣝⢵⢝⢮⡳⣝⢮⡳⣝⢎⣗⢝⣎⢧⡳⣕⢮⡫⡳⡳⡹⣕⡝⡮⡪⡮⣪⡺⡘⡈⠐⢈⠠⢃⠪⡢⡑⢌⢪⠨⠢⡑⠌⡂⡑⠸⠐⠀⡁⢈⠀⢁⠀⠄⠀⡀⠀⠄⠠⠀⠠⠀⢀⠈⠀⠠⠈⠀⢀⠠⠀⠀⠄⠂⠀⠀⠁⠀⠐⠀⠐⠀⠀⢪⢪⢪⢪⢪⢪⢒⢥⢣⠱⡘⡘⠜⡜⡎⢖
⡺⣪⡫⡽⣱⢝⣎⢧⡫⡮⡳⡕⣗⢕⢧⡳⡕⡧⡫⡮⣫⡺⡜⣎⢗⡝⡮⡊⡆⠂⠄⠁⠄⠠⢁⠣⡂⢎⠢⡑⢌⢊⠄⢅⢂⠐⡀⠡⠐⠀⠄⠐⠀⢀⠠⠀⠀⡀⠄⠀⠠⠀⠠⠀⠀⠐⠀⡀⠂⠀⢀⠠⠀⠄⠀⠠⠐⠈⠀⠀⠄⠀⠠⠀⢱⢱⢱⢱⢱⠱⡱⡱⡱⡱⣘⢌⢌⢂⢊⠪
⢯⢺⡪⣫⢮⢳⢕⢗⡝⡮⡳⡝⣎⢏⢧⢳⡹⣪⡫⡺⣜⠮⣝⢼⡱⡙⡔⠕⠡⠐⢈⠠⠁⠐⠀⢂⠊⢄⠕⡈⡂⡢⢑⢐⠀⡂⠐⠠⠈⡀⠂⠀⠂⠀⠀⢀⠀⡀⠀⠐⠀⠀⠂⠀⠈⠀⡀⠀⡀⠐⠀⠀⡀⠄⠈⠀⠄⠠⠐⠀⠐⠈⢀⠐⠨⢪⢪⢪⢒⢍⢎⢪⢸⢘⠜⡔⡕⣌⠢⡡
⣗⢵⢝⢮⣪⢳⢝⢵⡹⣪⡳⡝⡮⡝⣎⢗⣝⡜⡮⡫⣎⢯⢺⢜⠜⠨⢐⢈⠐⢈⠠⠀⠌⢀⠁⠄⠨⠐⠨⢐⠨⡐⡐⢐⠀⠂⠁⠂⠁⠀⠀⠂⠀⠂⠁⠀⡀⠀⡀⠂⠈⠀⠀⠂⠈⠠⠀⠠⠀⠀⠠⠀⠀⠀⡀⠁⠀⡀⠀⡈⠀⢁⠠⠐⠀⠌⠸⡸⡸⢸⢘⢜⢌⢎⢪⢊⢎⢲⠱⡅
⡳⡵⡝⡮⣪⢳⡹⣕⢽⡸⡪⡮⡳⡹⣜⢵⡱⡵⡝⡞⡜⠎⠑⠐⡈⠨⠀⠄⡈⠀⠄⠂⠐⢀⠐⡈⠀⠌⠈⠐⠀⠂⠠⠀⠄⠂⠁⠀⠂⠁⠈⢀⠈⠀⠄⠁⠀⡀⠀⠠⠀⠂⠁⠀⡀⠐⠀⠈⠀⠀⠄⠀⠈⠀⠀⢀⠀⠀⠀⠀⡀⠀⡀⠀⠄⢀⠂⠨⢪⠪⡊⡎⡆⢇⢣⢱⢑⢅⢇⢕
⣸⢪⡺⡪⣎⢧⢳⡱⣕⢝⡎⣗⢝⡕⡧⡳⠕⢃⠃⠡⠐⠈⡈⠠⠐⠈⠐⡀⠄⠁⠄⠁⠌⢀⠐⠀⡀⠂⢁⠈⢀⠁⠄⠂⠀⠄⠂⠁⠠⠈⠀⠠⠀⠂⠀⠐⠀⠀⠐⠀⠄⠀⠐⠀⠀⠀⠐⠀⠈⠀⠀⡀⠁⠀⠐⠀⠀⠀⠁⢀⠀⠄⢀⠂⢈⠀⠠⠐⠀⢁⠃⢇⢇⢇⢇⢇⢇⢇⢎⢜
⣪⢣⡳⡹⡜⣎⢧⢫⢎⢧⡫⣎⠧⡋⢊⠠⠈⡀⠄⠁⡀⢁⠠⠐⠀⡁⢁⠠⠀⠡⠀⠡⠐⠠⠀⠂⠀⠂⠠⠐⠀⢀⠠⠀⠂⢀⠀⠄⠠⠀⡈⢀⠠⠐⠈⠀⠈⠀⢁⠠⠀⠁⠄⠂⠀⠁⠠⠀⠂⠀⠂⠀⢀⠈⠀⠀⠂⠁⠠⠀⢀⠂⠠⠐⠀⡐⠀⠂⡈⠀⠄⠂⡈⠊⠆⢇⢕⢜⢔⢕
⣪⢣⡳⡹⣪⢺⢜⢵⡹⣪⢚⠨⠀⠄⠠⠀⠄⠀⠄⠂⠀⠄⠠⠀⠂⠠⠀⠠⠀⢁⠈⡀⠂⡁⠠⠈⢀⠁⠄⠂⠈⠀⡀⠄⠂⠀⠄⠂⠀⠂⠀⡀⠀⡀⠠⠀⠁⢈⠀⢀⠀⠂⠀⠄⠀⠄⠠⠀⠠⠀⠐⠀⠠⠀⢈⠀⠐⠀⠐⢀⠠⠐⠀⠂⠁⡀⠄⢁⠠⠐⠀⠂⠠⠈⠐⡀⢐⠀⠅⠑
⡗⡵⡹⡪⣎⢧⡫⡺⠘⠠⢀⠐⠀⠐⠀⠄⠂⠀⠂⠀⠂⠐⠀⠐⠈⢀⠈⢀⠐⠀⡀⠄⠐⠀⠄⠂⠀⠄⠀⠂⠈⡀⢀⠠⠀⠁⡀⠐⠈⠀⠄⠀⠄⠀⡀⠄⠈⡀⠠⠀⡐⠀⠠⠐⠀⠠⠀⠄⠂⠀⠂⠁⢀⠈⢀⠀⡈⠀⢁⠀⠠⠐⠈⢀⠁⡀⠐⢀⠠⠐⠈⠀⠂⡈⠠⠀⠄⠂⠈⠄
➕➖✖️➗  ✨✨✨✨✨          ☀️☁️☔️❄️    ➖✖️➗ ✨✨           ✨✨   ✨   ➖✖️➗  ✨                  
"""
print(jie)
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", ]

WEB_DIRECTORY = "./js"
