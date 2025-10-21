import subprocess
import importlib
import sys
import os
import platform  # keep near the top because lower sections rely on it
import json
import re
import folder_paths
import server
from aiohttp import web

# --- Dependency bootstrap ---
# Map PyPI package names to the module names they expose (if they differ)
package_to_module_map = {
    "python-barcode": "barcode",
    "Pillow": "PIL",
    "imageio[ffmpeg]": "imageio",
    "websocket-client": "websocket",  # alias used by websocket-client
    # Extend this map as needed for additional packages
}

# Resolve file-system roots
current_dir = os.path.dirname(os.path.realpath(__file__))
# Assume custom_nodes lives directly under the ComfyUI root
comfyui_root = os.path.abspath(os.path.join(current_dir, '..', '..'))

# --- Work out which Python executable to use across platforms ---
python_exe_to_use = sys.executable  # default to the current interpreter
print(f"Default Python executable: {python_exe_to_use}")

# Check for the Windows embedded runtime
if platform.system() == "Windows":
    embed_python_exe_win = os.path.join(comfyui_root, 'python_embeded', 'python.exe')
    if os.path.exists(embed_python_exe_win):
        print(f"Found ComfyUI Windows embedded Python: {embed_python_exe_win}")
        python_exe_to_use = embed_python_exe_win
    else:
         print(f"Warning: ComfyUI Windows embedded python not found at '{embed_python_exe_win}'. Using system python '{sys.executable}'.")

# Check for the Linux/macOS virtual environment Python
elif platform.system() in ["Linux", "Darwin"]:  # Darwin is macOS
    venv_python_exe = os.path.join(comfyui_root, 'venv', 'bin', 'python')
    venv_python3_exe = os.path.join(comfyui_root, 'venv', 'bin', 'python3')  # some platforms prefer python3

    if os.path.exists(venv_python_exe):
        print(f"Found ComfyUI venv Python: {venv_python_exe}")
        python_exe_to_use = venv_python_exe
    elif os.path.exists(venv_python3_exe):
         print(f"Found ComfyUI venv Python3: {venv_python3_exe}")
         python_exe_to_use = venv_python3_exe
    else:
         print(f"Warning: ComfyUI venv python not found at '{venv_python_exe}' or '{venv_python3_exe}'. Using system python '{sys.executable}'.")
else:
    # Fallback for other operating systems or unusual layouts
    print(f"Warning: Could not detect specific ComfyUI Python environment for OS '{platform.system()}'. Using system python '{sys.executable}'.")

print(f"Using Python executable for pip: {python_exe_to_use}")
# --- End interpreter detection ---


def check_and_install_dependencies(requirements_file):
    print("--- Checking custom node dependencies ---")
    installed_packages = False
    try:
        with open(requirements_file, 'r') as file:
            for line in file:
                package_line = line.strip()
                if package_line and not package_line.startswith('#') and not package_line.startswith('--'):
                    # --- Extract the canonical package name ---
                    package_name_for_install = package_line  # keep full spec for pip install
                    package_name_for_import = package_line  # assume same name for import
                    # Strip version specifiers to isolate the bare name
                    for spec in ['==', '>=', '<=', '>', '<', '~=', '!=']:
                        if spec in package_name_for_import:
                            package_name_for_import = package_name_for_import.split(spec)[0].strip()
                            break  # stop after first match
                    # Remove extras (e.g. package[extra])
                    if '[' in package_name_for_import and ']' in package_name_for_import:
                        package_name_for_import = package_name_for_import.split('[', 1)[0].strip()
                    # --- End extraction ---

                    # Look up an import alias (e.g. Pillow -> PIL)
                    module_name = package_to_module_map.get(package_name_for_import, package_name_for_import)
                    try:
                        # Try to import the module directly
                        importlib.import_module(module_name)
                        # print(f"Dependency '{package_name_for_install}' (module: {module_name}) already installed.")
                    except ImportError:
                        print(f"Dependency '{package_name_for_install}' (module: {module_name}) not found. Installing...")
                        try:
                            # Install using the original spec (preserving version constraints)
                            subprocess.check_call([python_exe_to_use, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir", package_name_for_install])
                            print(f"Successfully installed '{package_name_for_install}'.")
                            importlib.invalidate_caches()  # ensure new modules are discoverable
                            importlib.import_module(module_name)  # verify the import now works
                            installed_packages = True
                        except subprocess.CalledProcessError as e_main:
                            print(f"## [WARN] ComfyUI_to_webui: Failed to install dependency '{package_name_for_install}' with standard method. Command failed: {e_main}. Attempting with --user.")
                            try:
                                # Try installing again with --user for environments without write access
                                subprocess.check_call([python_exe_to_use, "-m", "pip", "install", "--user", "--disable-pip-version-check", "--no-cache-dir", package_name_for_install])
                                print(f"Successfully installed '{package_name_for_install}' using --user.")
                                importlib.invalidate_caches()
                                importlib.import_module(module_name)
                                installed_packages = True
                            except subprocess.CalledProcessError as e_user:
                                print(f"## [ERROR] ComfyUI_to_webui: Failed to install dependency '{package_name_for_install}' even with --user. Command failed: {e_user}.")
                                print("Please try installing dependencies manually:")
                                print(f"1. Open a terminal or command prompt.")
                                print(f"2. (Optional) Navigate to ComfyUI root: cd \"{comfyui_root}\"")
                                print(f"3. Run: \"{python_exe_to_use}\" -m pip install {package_name_for_install}")
                                print(f"   Alternatively, try installing all requirements: \"{python_exe_to_use}\" -m pip install -r \"{requirements_file}\"")
                                print("   If issues persist, you can seek help at relevant ComfyUI support channels or the node's repository.")
                            except ImportError:
                                print(f"## [ERROR] ComfyUI_to_webui: Could not import module '{module_name}' for package '{package_name_for_install}' even after attempting --user install. Check if the package name correctly provides the module.")
                        except ImportError:
                             # Improve the message to make the root cause clearer
                             print(f"## [ERROR] ComfyUI_to_webui: Could not import module '{module_name}' after attempting to install package '{package_name_for_install}'. Check if the package name '{package_name_for_install}' correctly provides the module '{module_name}'.")
                        except Exception as e:
                            print(f"## [ERROR] ComfyUI_to_webui: An unexpected error occurred during installation of '{package_name_for_install}': {e}")
    except FileNotFoundError:
         print(f"Warning: requirements.txt not found at '{requirements_file}', skipping dependency check.")
    except Exception as e:
        print(f"ERROR: An unexpected error occurred while processing requirements: {e}")


    if installed_packages:
        print("--- ComfyUI_to_webui: Dependency installation attempt complete. You may need to restart ComfyUI if new packages were installed. ---")
    else:
        print("--- All dependencies seem to be installed. ---")


# Automatically check/install dependencies during module import
requirements_path = os.path.join(current_dir, "requirements.txt")
check_and_install_dependencies(requirements_path)

# --- End dependency bootstrap ---


from .node.hua_word_image import Huaword, HuaFloatNode, HuaIntNode  # Numeric variants 2/3/4 were removed
from .node.hua_word_models import Modelhua
# Removed GradioInputImage, GradioTextOk, GradioTextBad from gradio_workflow import
from .node.mind_map import Go_to_image
from .node.hua_nodes import GradioInputImage, GradioTextBad
from .gradio_workflow import GradioTextOk  # Imported from gradio_workflow.py (if the node class is present)
from .node.hua_nodes import Hua_gradio_Seed, Hua_gradio_jsonsave, Hua_gradio_resolution
from .node.hua_nodes import Hua_LoraLoader, Hua_LoraLoaderModelOnly, Hua_CheckpointLoaderSimple, Hua_UNETLoader
from .node.hua_nodes import BarcodeGeneratorNode, Barcode_seed
from .node.output_image_to_gradio import Hua_Output
from .node.output_video_to_gradio import Hua_Video_Output  # include video output node
from .node.deepseek_api import DeepseekNode

NODE_CLASS_MAPPINGS = {
    "Huaword": Huaword,  # not exposed to the front-end
    "Modelhua": Modelhua,  # not exposed to the front-end
    "GradioInputImage": GradioInputImage,
    "Hua_Output": Hua_Output,
    "Go_to_image": Go_to_image,  # not exposed to the front-end
    "GradioTextOk": GradioTextOk, 
    "GradioTextBad": GradioTextBad,
    "Hua_gradio_Seed": Hua_gradio_Seed,
    "Hua_gradio_resolution": Hua_gradio_resolution,
    "Hua_LoraLoader": Hua_LoraLoader,  # not exposed to the front-end
    "Hua_LoraLoaderModelOnly": Hua_LoraLoaderModelOnly, 
    "Hua_CheckpointLoaderSimple": Hua_CheckpointLoaderSimple,
    "Hua_UNETLoader": Hua_UNETLoader,
    "BarcodeGeneratorNode": BarcodeGeneratorNode,  # not exposed to the front-end
    "Barcode_seed": Barcode_seed,  # not exposed to the front-end
    "Hua_gradio_jsonsave": Hua_gradio_jsonsave,
    "Hua_Video_Output": Hua_Video_Output,
    "HuaFloatNode": HuaFloatNode, 
    "HuaIntNode": HuaIntNode, 
    "DeepseekNode": DeepseekNode,

}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Huaword": "🌵Boolean Image",
    "Modelhua": "🌴Boolean Model",


    "GradioInputImage": "☀️Gradio Frontend Input Image",
    "Hua_Output": "🌙Image Output to Gradio Frontend",
    "Go_to_image": "⭐Mind Map",
    "GradioTextOk": "💧Gradio Positive Prompt",
    "GradioTextBad": "🔥Gradio Negative Prompt",
    "Hua_gradio_Seed": "🧙hua_gradio Random Seed",
    "Hua_gradio_resolution": "📜hua_gradio Resolution",
    "Hua_LoraLoader": "🌊hua_gradio_Lora Loader",
    "Hua_LoraLoaderModelOnly": "🌊hua_gradio_Lora Model Only",
    "Hua_CheckpointLoaderSimple": "🌊hua_gradio Checkpoint Loader",
    "Hua_UNETLoader": "🌊hua_gradio_UNET Loader",
    "BarcodeGeneratorNode": "hua_Barcode Generator",
    "Barcode_seed": "hua_Barcode Seed",
    "Hua_gradio_jsonsave": "📁hua_gradio_json Save",
    "Hua_Video_Output": "🎬Video Output (Gradio)",
    "HuaFloatNode": "🔢Float Input (Hua)",
    "HuaIntNode": "🔢Integer Input (Hua)",
    "DeepseekNode": "✨ Deepseek chat (Hua)",

}

print("[ComfyUI_to_webui] Plugin initialized.")


# Previously local imports (server, web, json, os, folder_paths, re) now live at the top of the file
# --- API endpoint for saving workflow API JSON ---
API_ROUTE_PATH = "/comfyui_to_webui/save_api_json"

async def save_api_json_route(request):
    try:
        data = await request.json()
        filename_base = data.get("filename")
        api_data_str = data.get("api_data")

        if not filename_base or not api_data_str:
            return web.json_response({"detail": "Filename or API payload missing"}, status=400)

        # Sanitize the filename to avoid traversal and illegal characters
        safe_basename = os.path.basename(filename_base)
        # Allow only alphanumeric characters, underscores, and hyphens
        # Remove dots so we can append .json ourselves
        safe_filename_stem = re.sub(r'[^\w\-]', '', safe_basename) 
        if not safe_filename_stem:  # fall back when sanitising wipes the name
            safe_filename_stem = "untitled_workflow_api"

        output_dir = folder_paths.get_output_directory()
        os.makedirs(output_dir, exist_ok=True)

        final_filename_json = f"{safe_filename_stem}.json"
        file_path = os.path.join(output_dir, final_filename_json)
        
        # Handle collisions by appending a numeric suffix
        counter = 1
        temp_filename_stem = safe_filename_stem
        while os.path.exists(file_path):
            temp_filename_stem = f"{safe_filename_stem}_{counter}"
            final_filename_json = f"{temp_filename_stem}.json"
            file_path = os.path.join(output_dir, final_filename_json)
            counter += 1
            if counter > 100:  # guard against infinite loops
                return web.json_response({"detail": "Unable to generate a unique filename. Please try another name."}, status=500)

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(api_data_str)  # api_data_str is already formatted JSON
        
        print(f"[ComfyUI_to_webui] API JSON saved to: {file_path}")
        return web.json_response({
            "message": f"API JSON saved to {final_filename_json} (stored in the output directory)", 
            "filename": final_filename_json,
            "filepath": file_path
        })

    except json.JSONDecodeError:
        return web.json_response({"detail": "Invalid JSON request body"}, status=400)
    except Exception as e:
        error_message = f"Internal server error while saving API JSON: {str(e)}"
        print(f"[ComfyUI_to_webui] Error saving API JSON: {error_message}")
        return web.json_response({"detail": error_message}, status=500)

def _register_api_route():
    """Attach the API route to the PromptServer once it is available."""
    prompt_server = getattr(server.PromptServer, "instance", None)
    if prompt_server is None:
        return False

    # Prevent duplicate registrations when reloads happen.
    already_registered = getattr(prompt_server, "_comfyui_to_webui_api_registered", False)
    if already_registered:
        return True

    try:
        prompt_server.routes.post(API_ROUTE_PATH)(save_api_json_route)
        prompt_server._comfyui_to_webui_api_registered = True
        print(f"--- ComfyUI_to_webui: Registered API endpoint {API_ROUTE_PATH} ---")
        return True
    except Exception as exc:
        print(f"[ComfyUI_to_webui] Failed to register API endpoint {API_ROUTE_PATH}: {exc}")
        return False

def _ensure_route_registration():
    if _register_api_route():
        return

    # Defer registration until the PromptServer initializes.
    if getattr(server.PromptServer, "_comfyui_to_webui_route_hook_installed", False):
        return

    original_init = server.PromptServer.__init__

    def wrapped_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        _register_api_route()

    server.PromptServer.__init__ = wrapped_init
    server.PromptServer._comfyui_to_webui_route_hook_installed = True
    print(f"[ComfyUI_to_webui] PromptServer not ready; deferring registration of {API_ROUTE_PATH}.")

_ensure_route_registration()
# --- End API endpoint ---

WEB_DIRECTORY = "./js"

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
