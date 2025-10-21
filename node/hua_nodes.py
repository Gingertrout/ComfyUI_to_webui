#---------------------------------------------------------------------------------------------------------------------#
# Node author: hua   Repository: https://github.com/kungful/ComfyUI_hua_boy.git
#---------------------------------------------------------------------------------------------------------------------#
import sys
from .hua_icons import icons
import typing as tg
import json
import os
import random
import numpy as np  # used for image array manipulation
from PIL import Image, ImageOps, ImageSequence, ImageFile
from PIL.PngImagePlugin import PngInfo
import folder_paths  # helper for resolving ComfyUI paths
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
# Corrected font path relative to this script's location
FONT_PATH = os.path.join(os.path.dirname(__file__), '..', 'fonts', 'SimHei.ttf')

def find_key_by_name(prompt, name):
    for key, value in prompt.items():
        if isinstance(value, dict) and value.get("_meta", {}).get("title") == name:
            return key
    return None

def check_seed_node(json_file):
    # Verify the file exists and is valid before toggling the seed indicator.
    if not json_file or not os.path.exists(os.path.join(OUTPUT_DIR, json_file)):
        print(f"JSON file is missing or invalid: {json_file}")
        return gr.update(visible=False)  # Hide the seed indicator when the file is invalid

    json_path = os.path.join(OUTPUT_DIR, json_file)
    try:
        with open(json_path, "r", encoding="utf-8") as file_json:
            prompt = json.load(file_json)
        seed_key = find_key_by_name(prompt, "🧙hua_gradio random seed")
        if seed_key is None:
            return gr.update(visible=False)
        else:
            return gr.update(visible=True)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error reading or parsing JSON file ({json_file}): {e}")
        return gr.update(visible=False)  # Hide the indicator when parsing fails

current_dir = os.path.dirname(os.path.abspath(__file__))  # directory hosting this module
print("hua plugin directory:", current_dir)
parent_dir = os.path.dirname(os.path.dirname(current_dir))  # parent of parent
sys.path.append(parent_dir)  # ensure parent is in sys.path
from comfy.cli_args import args
from .hua_icons import icons




class GradioTextBad:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "string": ("STRING", {"multiline": True, "dynamicPrompts": True, "tooltip": "The text to be encoded."}),
                "name": ("STRING", {"multiline": False, "default": "GradioTextBad", "tooltip": "Node name"}),
            }
        }
    RETURN_TYPES = ("STRING",)
    OUTPUT_TOOLTIPS = ("A conditioning containing the embedded text used to guide the diffusion model.",)
    FUNCTION = "encode"

    CATEGORY = icons.get("hua_boy_one")
    DESCRIPTION = "Encodes a text prompt using a CLIP model into an embedding that can be used to guide the diffusion model towards generating specific images."

    def encode(self, string, name):
        return (string,)

class GradioInputImage:
    @classmethod
    def INPUT_TYPES(s):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
        return {"required":
                    {"image": (sorted(files), {"image_upload": True}),
                     "name": ("STRING", {"multiline": False, "default": "GradioInputImage", "tooltip": "Node name"}),
                    },
                }

    OUTPUT_TOOLTIPS = ("This is a Gradio image input node",)
    FUNCTION = "load_image"
    OUTPUT_NODE = True
    CATEGORY = icons.get("hua_boy_one")
    RETURN_TYPES = ("IMAGE", "MASK")



    def load_image(self, image, name):
        image_path = folder_paths.get_annotated_filepath(image)
        print("load_image reading path:", image_path)

        img = node_helpers.pillow(Image.open, image_path)

        output_images = []  # list of processed image tensors
        output_masks = []  # list of corresponding masks
        w, h = None, None # image width/height placeholders

        excluded_formats = ['MPO']  # exclude 'MPO' only

        for i in ImageSequence.Iterator(img):
            i = node_helpers.pillow(ImageOps.exif_transpose, i)  # correct orientation via EXIF

            if i.mode == 'I': # if mode 'I', scale pixel values to [0,1]
                i = i.point(lambda i: i * (1 / 255))
            image = i.convert("RGB")  # convert to RGB

            if len(output_images) == 0: # first frame sets width/height
                w = image.size[0]
                h = image.size[1]

            if image.size[0] != w or image.size[1] != h: # skip frames with mismatched size
                continue

            image = np.array(image).astype(np.float32) / 255.0 # normalize to [0,1]
            image = torch.from_numpy(image)[None,] # to tensor
            if 'A' in i.getbands(): # alpha channel present
                mask = np.array(i.getchannel('A')).astype(np.float32) / 255.0 # normalize alpha
                mask = 1. - torch.from_numpy(mask) # invert mask
            else:
                mask = torch.zeros((64,64), dtype=torch.float32, device="cpu") # fallback mask
            output_images.append(image)
            output_masks.append(mask.unsqueeze(0))

        if len(output_images) > 1 and img.format not in excluded_formats:
            output_image = torch.cat(output_images, dim=0)
            output_mask = torch.cat(output_masks, dim=0)
        else:
            # Single frame
            output_image = output_images[0]
            output_mask = output_masks[0]

        return (output_image, output_mask)






# ------------------------------------------------ Barcode utilities ------------------------------------------------ #
class Barcode_seed:

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff})}}

    RETURN_TYPES = ("INT", "STRING", )
    RETURN_NAMES = ("Seed", "Help Link", )
    FUNCTION = "hua_seed"
    OUTPUT_NODE = True
    CATEGORY = icons.get("hua_boy_one")

    @staticmethod
    def hua_seed(seed):
        show_help = "https://github.com/kungful/ComfyUI_hua_boy.git"
        return (seed, show_help,)

class BarcodeGeneratorNode:
    # ComfyUI nodes are stateless; each execution is independent. If you need
    # automatic incrementing across runs, feed the output back into the input or
    # manage state externally. This implementation simply accepts the provided
    # number, generates a barcode, and returns the value unchanged.

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prefix": ("STRING", {
                    "display_name": "Prefix (optional)",
                    "multiline": False,
                    "default": ""
                }),
                "input_number": ("INT", {
                    "display_name": "Starting Number",
                    "default": 0,
                    "min": 0,
                    "max": 0xffffffffffffffff
                }),
                 "font_size": ("INT", {
                    "display_name": "Text Size (px)",
                    "default": 25,
                    "min": 10,
                    "max": 200,
                    "step": 1
                }),
                    "barcode_height_scale": ("FLOAT", {
                        "display_name": "Barcode Height Scale",
                        "default": 0.5,
                        "min": 0.1,
                        "max": 3.0,
                        "step": 0.1
                    }),
                 "text_bottom_margin": ("INT", {
                    "display_name": "Text Bottom Margin (px)",
                    "default": 15,
                    "min": 5,
                    "max": 50,
                    "step": 1
                }),
                "barcode_text_spacing": ("INT", {
                    "display_name": "Barcode-Text Spacing (px)",
                    "default": 10,
                    "min": -80,
                    "max": 50,
                    "step": 1
                }),
                "horizontal_margin": ("FLOAT", {
                    "display_name": "Left/Right Margin Scale",
                    "default": 2.0,
                    "min": 0.0,
                    "max": 20.0,
                    "step": 0.5
                }),
                "top_margin": ("INT", {
                    "display_name": "Top Margin (px)",
                    "default": 5,
                    "min": 0,
                    "max": 100,
                    "step": 1
                }),
                "global_scale": ("FLOAT", {
                    "display_name": "Global Scale",
                    "default": 1.0,
                    "min": 0.1,
                    "max": 10.0,
                    "step": 0.1
                })
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("Barcode Image", "Size Mask", "Output Number")
    FUNCTION = "generate"
    CATEGORY = icons.get("hua_boy_one")  # shared category prefix

    # --- Helper for PIL version compatibility ---
    try:
        RESAMPLING_MODE = Image.Resampling.LANCZOS
    except AttributeError:
        # Fallback for older PIL versions
        RESAMPLING_MODE = Image.LANCZOS
    # --- End Helper ---

    def validate_number_input(self, num):
        """Validate number input range"""
        if num < 0:
            raise ValueError("Error: starting number cannot be negative")
        return num

    def draw_text(self, img, text, font_path, font_size, top_y):
        """Draw centered text at top_y with font fallback"""
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(font_path, font_size)
        except IOError:
            print(f"Warning: unable to load font {font_path}. Falling back to default font.")
            try:
                font = ImageFont.load_default()
            except IOError:
                print("Warning: failed to load default font; skipping text draw.")
                return img

        # Use textbbox when available for precise measurements
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
        except AttributeError: # Compatibility for older PIL without textbbox
             text_width, text_height = draw.textsize(text, font=font)


        img_width, _ = img.size
        x = (img_width - text_width) // 2
        y = top_y

        # Draw text
        draw.text((x, y), text, font=font, fill="black")

        return img

    def generate(self, prefix, input_number, font_size, barcode_height_scale, text_bottom_margin, barcode_text_spacing, horizontal_margin, top_margin, global_scale):
        # 1. Validate inputs
        try:
            current_number = self.validate_number_input(input_number)
            if global_scale <= 0:
                raise ValueError("Global scale must be > 0")
            next_number_str = str(input_number)
        except ValueError as e:
            print(f"Input error: {e}")
            error_img = Image.new("RGB", (300, 100), "white")
            draw = ImageDraw.Draw(error_img)
            draw.text((10, 10), f"Error: {e}", fill="red")
            image_np = np.array(error_img).astype(np.float32) / 255.0
            image_tensor = torch.from_numpy(image_np)[None,]
            mask = torch.ones((100, 300), dtype=torch.float32)
            return (image_tensor, mask, str(input_number))

        # 2. Build the barcode image itself
        try:
            code128 = barcode.get_barcode_class('code128')
            writer_options = {
                'module_height': 15.0 * barcode_height_scale,
                'write_text': False,
                'quiet_zone': horizontal_margin,
                'dpi': int(300 * global_scale)
            }
            barcode_pil_img = code128(next_number_str, writer=ImageWriter()).render(writer_options)
        except Exception as e:
            print(f"Barcode generation error: {e}")
            error_img = Image.new("RGB", (300, 100), "white")
            draw = ImageDraw.Draw(error_img)
            draw.text((10, 10), f"Barcode error: {e}", fill="red")
            image_np = np.array(error_img).astype(np.float32) / 255.0
            image_tensor = torch.from_numpy(image_np)[None,]
            mask = torch.ones((100, 300), dtype=torch.float32)
            return (image_tensor, mask, str(input_number))

        # 3. Determine canvas dimensions
        barcode_width, barcode_height = barcode_pil_img.size
        # Estimate text height
        try:
            font = ImageFont.truetype(FONT_PATH, font_size)
            combined_text = f"{prefix}{next_number_str}"
            bbox = ImageDraw.Draw(Image.new("RGB",(1,1))).textbbox((0,0), combined_text, font=font)
            text_actual_height = bbox[3] - bbox[1]
        except Exception:
            text_actual_height = font_size

        text_area_total_height = barcode_text_spacing + text_actual_height + text_bottom_margin

        min_width = 200
        min_height = 50

        canvas_width = max(barcode_width, min_width)
        canvas_height = max(top_margin + barcode_height + text_area_total_height, min_height)

        # 4. Create the canvas and paste the barcode at the top (centered)
        canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
        paste_x = (canvas_width - barcode_width) // 2
        paste_y = top_margin
        canvas.paste(barcode_pil_img, (paste_x, paste_y))

        # 5. Draw the combined text beneath the barcode
        combined_text_to_draw = f"{prefix}{input_number}"
        text_top_y = paste_y + barcode_height + barcode_text_spacing

        try:
            canvas_with_text = self.draw_text(canvas, combined_text_to_draw, FONT_PATH, font_size, text_top_y)

        except Exception as e:
            print(f"Error drawing text: {e}")
            canvas_with_text = canvas

        # 6. Apply global scaling
        original_width, original_height = canvas_with_text.size
        scaled_width = max(1, int(original_width * global_scale))
        scaled_height = max(1, int(original_height * global_scale))

        if global_scale != 1.0:
            try:
                print(f"Original size: {original_width}x{original_height}, scale: {global_scale}, resized: {scaled_width}x{scaled_height}")
                temp_canvas = Image.new("RGB", (original_width, original_height), "white")
                temp_canvas.paste(canvas_with_text, (0, 0))
                final_canvas = temp_canvas.resize((scaled_width, scaled_height), self.RESAMPLING_MODE)
            except Exception as e:
                print(f"Error resizing image: {e}")
                final_canvas = canvas_with_text
        else:
            final_canvas = canvas_with_text

        # 7. Convert to ComfyUI tensor format
        final_image_np = np.array(final_canvas).astype(np.float32) / 255.0
        final_image_tensor = torch.from_numpy(final_image_np)[None,]

        final_height, final_width = final_image_np.shape[:2]
        mask = torch.ones((final_height, final_width), dtype=torch.float32)

        return (final_image_tensor, mask, str(input_number))

class Hua_gradio_Seed:

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            "name": ("STRING", {"multiline": False, "default": "Hua_gradio_Seed", "tooltip": "Node name"}),
            }}

    RETURN_TYPES = ("INT", "STRING", )
    RETURN_NAMES = ("Seed", "Help Link", )
    FUNCTION = "hua_seed"
    OUTPUT_NODE = True
    CATEGORY = icons.get("hua_boy_one")

    @staticmethod
    def hua_seed(seed, name):
        show_help = "https://github.com/kungful/ComfyUI_hua_boy.git"
        return (seed, show_help,)
#---------------------------------------------------------------------------------------------------------------------#
# GradioTextOk2, GradioTextOk3, GradioTextOk4 classes were here and are now removed.
#---------------------------------------------------------------------------------------------------------------------#
class Hua_gradio_Seed:

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            "name": ("STRING", {"multiline": False, "default": "Hua_gradio_Seed", "tooltip": "Node name"}),
            }}

    RETURN_TYPES = ("INT", "STRING", )
    RETURN_NAMES = ("seed", "show_help", )
    FUNCTION = "hua_seed"
    OUTPUT_NODE = True
    CATEGORY = icons.get("hua_boy_one")

    @staticmethod
    def hua_seed(seed, name):
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
                "name": ("STRING", {"multiline": False, "default": "Hua_gradio_resolution", "tooltip": "Node name"}),
            }
        }

    RETURN_TYPES = ("INT", "INT",)
    RETURN_NAMES = ("width", "height",)
    FUNCTION = "get_resolutions"

    CATEGORY = icons.get("hua_boy_one")

    def get_resolutions(self, custom_width, custom_height, name):
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
                "filename_prefix": ("STRING", {"default": "apijson", "tooltip": "The prefix for the file to save. This may include formatting information such as %date:yyyy-MM-dd% or %Empty Latent Image.width% to include values from nodes."}),
                "name": ("STRING", {"multiline": False, "default": "Hua_gradio_jsonsave", "tooltip": "Node name"}),
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
    DESCRIPTION = "Save the API-format workflow JSON into the input directory"

    def autosavejson(self, images, filename_prefix="apijson", name="Hua_gradio_jsonsave", prompt=None, extra_pnginfo=None):
        filename_prefix += self.prefix_append
        full_output_folder, filename, counter, subfolder, filename_prefix = folder_paths.get_save_image_path(filename_prefix, self.output_dir, images[0].shape[1], images[0].shape[0])
        results = list()
        # results = []
        counter = 0  # track how many images were processed
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

            print(f"Saved API workflow JSON to: {json_file_path}")
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
                "name": ("STRING", {"multiline": False, "default": "Hua_LoraLoader", "tooltip": "Node name"}),
            }
        }

    RETURN_TYPES = ("MODEL", "CLIP")
    OUTPUT_TOOLTIPS = ("The modified diffusion model.", "The modified CLIP model.")
    FUNCTION = "load_lora"

    CATEGORY = icons.get("hua_boy_one")
    DESCRIPTION = "LoRAs are used to modify diffusion and CLIP models, altering the way in which latents are denoised such as applying styles. Multiple LoRA nodes can be linked together."

    def load_lora(self, model, clip, lora_name, strength_model, strength_clip, name):
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
                              "name": ("STRING", {"multiline": False, "default": "Hua_LoraLoaderModelOnly", "tooltip": "Node name"}),
                              }}
    RETURN_TYPES = ("MODEL",)
    FUNCTION = "load_lora_model_only"
    CATEGORY = icons.get("hua_boy_one")
    def load_lora_model_only(self, model, lora_name, strength_model, name):
        # Forward the name parameter through to load_lora
        return (self.load_lora(model, None, lora_name, strength_model, 0, name)[0],)

# Hua_LoraLoaderModelOnly2, Hua_LoraLoaderModelOnly3, Hua_LoraLoaderModelOnly4 classes were here and are now removed.

class Hua_CheckpointLoaderSimple:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "ckpt_name": (folder_paths.get_filename_list("checkpoints"), {"tooltip": "The name of the checkpoint (model) to load."}),
                "name": ("STRING", {"multiline": False, "default": "Hua_CheckpointLoaderSimple", "tooltip": "Node name"}),
            }
        }
    RETURN_TYPES = ("MODEL", "CLIP", "VAE")
    OUTPUT_TOOLTIPS = ("The model used for denoising latents.",
                       "The CLIP model used for encoding text prompts.",
                       "The VAE model used for encoding and decoding images to and from latent space.")
    FUNCTION = "load_checkpoint"

    CATEGORY = icons.get("hua_boy_one")
    DESCRIPTION = "Loads a diffusion model checkpoint, diffusion models are used to denoise latents."

    def load_checkpoint(self, ckpt_name, name):
        ckpt_path = folder_paths.get_full_path_or_raise("checkpoints", ckpt_name)
        out = comfy.sd.load_checkpoint_guess_config(ckpt_path, output_vae=True, output_clip=True, embedding_directory=folder_paths.get_folder_paths("embeddings"))
        return out[:3]

class Hua_UNETLoader:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": { "unet_name": (folder_paths.get_filename_list("diffusion_models"), ),
                              "weight_dtype": (["default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"],),
                              "name": ("STRING", {"multiline": False, "default": "Hua_UNETLoader", "tooltip": "Node name"}),
                             }}
    RETURN_TYPES = ("MODEL",)
    FUNCTION = "load_unet"

    CATEGORY = icons.get("hua_boy_one")

    def load_unet(self, unet_name, weight_dtype, name):
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
