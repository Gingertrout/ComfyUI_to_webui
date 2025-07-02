import os
import json
from openai import OpenAI
from .hua_icons import icons

class DeepseekNode:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "api_key": ("STRING", {"multiline": False}),
                "prompt": ("STRING", {"multiline": True}),
                "system_prompt": ("STRING", {
                    "multiline": True,
                    "default": "You are a helpful assistant"
                }),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            },
            "optional": {
                "temperature": ("FLOAT", {
                    "default": 0.7,
                    "min": 0.0,
                    "max": 2.0,
                    "step": 0.1,
                    "tooltip": "创造性，随机性"
                }),
            }
        }
    
    RETURN_TYPES = ("STRING",)
    FUNCTION = "execute"
    CATEGORY = icons.get("hua_boy_one")

    @classmethod
    def get_icon(cls):
        dir_path = os.path.dirname(os.path.realpath(__file__))
        icon_path = os.path.join(dir_path, "deepseek_icon.svg")
        if os.path.exists(icon_path):
            with open(icon_path, "r") as f:
                return f.read()
        return None

    def execute(self, api_key, prompt, seed, system_prompt="You are a helpful assistant", temperature=0.7):
        if not api_key:
            return ("Error: Please provide your API key",)
            
        try:
            client = OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com"
            )
            
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                stream=False
            )
            
            result = response.choices[0].message.content
            print(f"Deepseek API response: {result}")
            return (result,)
        except Exception as e:
            return (f"Error: {str(e)}",)
