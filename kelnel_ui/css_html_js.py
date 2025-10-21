import os
import re

HACKER_CSS = """
.log-display-container {
    background-color: black !important;
    color: #00ff00 !important;
}
.log-display-container h4 {
    color: #00ff00 !important;
}
.log-display-container textarea {
    background-color: black !important;
    color: #00ff00 !important;
    /* border-color: #00ff00 !important; */
}

/* Adjust Gradio Tab spacing */
.tabs > .tab-nav { /* Tab button navbar */
    margin-bottom: 0px !important; /* Remove bottom margin */
    border-bottom: none !important; /* Remove bottom border if present */
}

.tabitem { /* Tab content area */
    padding-top: 0px !important; /* Reduce top padding */
    margin-top: 0px !important; /* Ensure no top margin */
}

/* Hide ComfyUI node badge toggle button to declutter toolbar */
button[aria-label*="badge" i],
button[title*="badge" i],
button[data-tooltip*="badge" i] {
    display: none !important;
}
"""

def get_sponsor_html():
    # Assume js/icon.js is relative to this file (css_html_js.py)
    # If css_html_js.py and gradio_workflow.py are in the same directory and js folder is here, this path works.
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    js_icon_path = os.path.join(current_script_dir, 'js', 'icon.js')
    base64_data = None
    default_sponsor_info = """
<div style='text-align: center;'>
    <h3>Thank you for your support!</h3>
    <p>Failed to load sponsor code image.</p>
    
</div>
"""
    try:
        with open(js_icon_path, 'r', encoding='utf-8') as f:
            js_content = f.read()
            match = re.search(r'loadImage\("(data:image/[^;]+;base64,[^"]+)"\)', js_content)
            if match:
                base64_data = match.group(1)
            else:
                print(f"Warning: No matching Base64 data found in {js_icon_path}.")

    except FileNotFoundError:
        print(f"Error: Sponsor code image file not found: {js_icon_path}")
    except Exception as e:
        print(f"Error reading or parsing sponsor code file ({js_icon_path}): {e}")

    if base64_data:
        sponsor_info = f"""
<div style='text-align: center;'>
    <h3>Thank you for your support!</h3>
    <p>Please use the code below to sponsor:</p>
    <img src='{base64_data}' alt='Sponsor Code' width='512' height='512'>
</div>
"""
    else:
        sponsor_info = default_sponsor_info
    return sponsor_info

# Placeholder: add additional JavaScript variables or helpers here if needed
# For example:
# MY_JS_CODE = """
# console.log("Hello from JS!");
# """
