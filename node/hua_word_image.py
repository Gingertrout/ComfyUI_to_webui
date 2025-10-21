from collections import Counter
from PIL import Image
import re
from .hua_icons import icons
class Huaword:
    def __init__(self):
        pass
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text1": ("STRING", {"multiline": True, "dynamicPrompts": True, "tooltip": "Full string"}),
                "text2": ("STRING", {"multiline": True, "dynamicPrompts": True, "tooltip": "Specified string"}),
                "image1": ("IMAGE",),
                "image2": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    OUTPUT_TOOLTIPS = ("If the specified word appears, output image1; otherwise image2.",)
    FUNCTION = "test"
    OUTPUT_NODE = True
    CATEGORY = icons.get("hua_boy_one")

    def test(self, text1, text2, image1, image2):
        text2_words = set(word.lower() for word in text2.split())
        words = re.findall(r'\b\w+\b', text1.lower())
        word_counts = Counter(words)
        total_count = sum(word_counts[word] for word in text2_words)
        
        if total_count > 0:
            output_images = image1
        else:
            output_images = image2
        
        print(f"Target word '{text2}' appears {total_count} times in input text")
        return (output_images,)


# Float input helper node
class HuaFloatNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "float_value": ("FLOAT", {
                    "default": 0.0,
                    "min": -9999999999.0,
                    "max": 9999999999.0,
                    "step": 0.01,
                    "display": "number", # or "slider"
                    "tooltip": "Enter a float"
                }),
                "name": ("STRING", {"multiline": False, "default": "FloatInput", "tooltip": "Node name"}),
            }
        }

    RETURN_TYPES = ("FLOAT",)
    FUNCTION = "get_float"
    CATEGORY = icons.get("hua_boy_one")

    def get_float(self, float_value, name):  # name argument retained for compatibility
        return (float_value,)

# Integer input helper node
class HuaIntNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "int_value": ("INT", {
                    "default": 0,
                    "min": -9999999999,
                    "max": 9999999999,
                    "step": 1,
                    "display": "number", # or "slider"
                    "tooltip": "Enter an integer"
                }),
                "name": ("STRING", {"multiline": False, "default": "IntInput", "tooltip": "Node name"}),
            }
        }

    RETURN_TYPES = ("INT",)
    FUNCTION = "get_int"
    CATEGORY = icons.get("hua_boy_one")

    def get_int(self, int_value, name):  # name argument retained for compatibility
        return (int_value,)
