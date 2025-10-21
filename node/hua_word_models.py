from collections import Counter
from PIL import Image
import re
from .hua_icons import icons
class Modelhua:
    def __init__(self):
        pass
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text1": ("STRING", {"multiline": True, "dynamicPrompts": True, "tooltip": "Full string"}),
                "text2": ("STRING", {"multiline": True, "dynamicPrompts": True, "tooltip": "Specified string"}),
                "model1": ("MODEL",),
                "model2": ("MODEL",),
            },
        }

    RETURN_TYPES = ("MODEL",)
    OUTPUT_TOOLTIPS = ("If the specified word appears in the string, model1 is selected; otherwise model2.",)
    FUNCTION = "load_model_hua"
    OUTPUT_NODE = True
    CATEGORY = icons.get("hua_boy_one")

    def load_model_hua(self, text1, text2, model1, model2):
        text2_words = set(word.lower() for word in text2.split())
        words = re.findall(r'\b\w+\b', text1.lower())
        word_counts = Counter(words)
        total_count = sum(word_counts[word] for word in text2_words)
        
        if total_count > 0:
            model_options = model1
        else:
            model_options = model2
        
        print(f"Target word '{text2}' appears {total_count} times in input text")
        return (model_options,)

NODE_CLASS_MAPPINGS = {
    "small_note_model": Modelhua
} 

NODE_DISPLAY_NAME_MAPPINGS = {
    "small_note_model": "Boolean Model"
}
