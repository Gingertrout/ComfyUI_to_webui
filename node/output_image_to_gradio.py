from datetime import datetime
import os
import numpy as np
from PIL import Image
import folder_paths
from .hua_icons import icons
import json # import json

OUTPUT_DIR = folder_paths.get_output_directory()
TEMP_DIR = folder_paths.get_temp_directory() # temp directory

# Output node that passes results to Gradio frontend
class Hua_Output:
    def __init__(self):
        self.output_dir = folder_paths.get_output_directory() # output dir
        self.type = "output"
        self.prefix_append = ""
        self.compress_level = 4 # PNG compression level

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "The images to save."}),
                "unique_id": ("STRING", {"default": "default_id", "multiline": False, "tooltip": "Unique ID for this execution provided by Gradio."}),
                "name": ("STRING", {"multiline": False, "default": "Hua_Output", "tooltip": "Node name"}),
            }
        }

    # RETURN_TYPES = ()  # no direct path payload returned to ComfyUI
    RETURN_TYPES = ()
    FUNCTION = "output_gradio"
    OUTPUT_NODE = True
    CATEGORY = icons.get("hua_boy_one")

    def output_gradio(self, images, unique_id, name):
        image_paths = []

        prefix_input = name if isinstance(name, str) else str(name)
        prefix_input = prefix_input.strip() if prefix_input else ""
        if not prefix_input or prefix_input.lower() == "none":
            prefix_input = "ComfyUI"
        filename_prefix = prefix_input + self.prefix_append

        if images is None or len(images) == 0:
            print(f"Hua_Output: received no images to save for execution {unique_id}.")
            os.makedirs(TEMP_DIR, exist_ok=True)
            temp_file_path = os.path.join(TEMP_DIR, f"{unique_id}.json")
            try:
                with open(temp_file_path, 'w', encoding='utf-8') as f:
                    json.dump({"error": "No images received", "generated_files": []}, f)
                print(f"Hua_Output: wrote empty result placeholder to {temp_file_path}")
            except Exception as e:
                print(f"Hua_Output: failed to write placeholder temp file ({temp_file_path}): {e}")
            return ()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        first_image = images[0]
        full_output_folder, _, _, subfolder, _ = folder_paths.get_save_image_path(
            filename_prefix, self.output_dir, first_image.shape[1], first_image.shape[0]
        )

        for (batch_number, image) in enumerate(images):
            i = 255. * image.cpu().numpy()
            img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
            file = f"output_{timestamp}_{batch_number:05}.png"
            image_path_gradio = os.path.join(full_output_folder, file)
            img.save(os.path.join(full_output_folder, file), compress_level=self.compress_level)
            print(f"output_gradio wrote image: {image_path_gradio}")
            image_paths.append(image_path_gradio)

        # Ensure temp dir exists
        os.makedirs(TEMP_DIR, exist_ok=True)
        
        # Write image path list to temp file
        temp_file_path = os.path.join(TEMP_DIR, f"{unique_id}.json")
        try:
            with open(temp_file_path, 'w', encoding='utf-8') as f:
                json.dump(image_paths, f)
            print(f"Image path list written to temp file: {temp_file_path}")
            print(f"Temp dir: {TEMP_DIR}")
            print(f"Image paths: {image_paths}")
            
            # Validate files exist
            for path in image_paths:
                if not os.path.exists(path):
                    print(f"Error: image file missing: {path}")
                else:
                    print(f"OK: image file exists: {path}")
                    
        except Exception as e:
            print(f"Failed to write temp file ({temp_file_path}): {e}")
            print(f"Temp dir writable: {os.access(TEMP_DIR, os.W_OK)}")

        # No direct path payload returned; Gradio front-end reads the temp JSON.
        return ()
