import os
from PIL import Image, ImageOps, ImageSequence
import numpy as np
import torch
# Import folder_paths helper
import folder_paths # type: ignore
from .hua_icons import icons

class Go_to_image:
    _color_channels = 3  # assume RGB channels
    @classmethod
    def INPUT_TYPES(s):  # describe node inputs
        input_dir = folder_paths.get_input_directory()  # locate the ComfyUI input folder
        files = sorted(os.listdir(input_dir))  # list available files, sorted alphabetically
        return {
            "required": {  # mandatory inputs
                "image": (files, {"image_upload": True}),  # file name with upload support
                "pos_text": ("STRING", {"multiline": True, "default": "positive text"}),  # positive prompt with default

                "images": ("IMAGE", ), 
                
            }
        }
        
    
    

    RETURN_TYPES = ("IMAGE", "MASK", "CONDITIONING")   # three outputs: image, mask, conditioning


    FUNCTION = "load_image"  # entrypoint used by ComfyUI

    CATEGORY = icons.get("hua_boy_one")  # category shown in the node tree

    def load_image(self, image):
        image_path = folder_paths.get_annotated_filepath(image)
        img = Image.open(image_path)
        output_images = []
        output_masks = []
        for i in ImageSequence.Iterator(img):
            i = ImageOps.exif_transpose(i)
            if i.mode == 'I':
                i = i.point(lambda i: i * (1 / 255))
            image = i.convert("RGB")
            image = np.array(image).astype(np.float32) / 255.0
            image = torch.from_numpy(image)[None,]
            if 'A' in i.getbands():
                mask = np.array(i.getchannel('A')).astype(np.float32) / 255.0
                mask = 1. - torch.from_numpy(mask)
            else:
                mask = torch.zeros((64,64), dtype=torch.float32, device="cpu")
            output_images.append(image)
            output_masks.append(mask.unsqueeze(0))

        if len(output_images) > 1:
            output_image = torch.cat(output_images, dim=0)
            output_mask = torch.cat(output_masks, dim=0)
        else:
            output_image = output_images[0]
            output_mask = output_masks[0]

        return (output_image, output_mask)



NODE_CLASS_MAPPINGS = {   
    "brucelee": Go_to_image  # exported class name
}

# A dictionary that contains the friendly/humanly readable titles for the nodes
NODE_DISPLAY_NAME_MAPPINGS = {    # Maps node class name to human-readable title
    "brucelee": "Mind Map"
}
