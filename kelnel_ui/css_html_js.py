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

/* Constrain uploaded images - FORGE APPROACH (Maximum clearance) */

/* Upload Image accordion must contain everything with MAXIMUM space */
.accordion:has(#hua-image-input) {
    overflow: visible !important;
    margin-bottom: 3em !important;
    padding-bottom: 250px !important; /* MAXIMUM space for tools INSIDE accordion */
}

/* Upload container - constrain size, contain tools */
#hua-image-input {
    width: 100% !important;
    max-width: 100% !important;
    position: relative !important; /* Keep tools inside */
    display: block !important;
    min-height: 680px !important; /* Maximum room for image + tools */
}

/* Image and canvas elements - Forge's object-fit approach */
#hua-image-input img {
    max-height: 500px !important;
    max-width: 100% !important;
    width: auto !important;
    height: auto !important;
    object-fit: scale-down !important;
    display: block !important;
    margin: 0 auto !important;
}

#hua-image-input canvas {
    max-height: 500px !important;
    max-width: 100% !important;
    object-fit: scale-down !important;
    display: block !important;
    margin: 0 auto !important;
}

/* SVG layers */
#hua-image-input svg {
    max-height: 500px !important;
    max-width: 100% !important;
}

/* CRITICAL: Push accordions below DOWN with maximum margin */
.accordion:has(#hua-image-input) ~ * {
    position: relative !important;
    z-index: 1 !important;
    margin-top: 3em !important; /* Maximum space between Upload Image and next accordion */
}

/* Dropdown z-index - FORGE APPROACH (High priority for dropdowns) */
.gradio-dropdown ul.options,
.gradio-dropdown .options,
div[class*="dropdown"] ul.options,
div[class*="dropdown"] .options {
    z-index: 3000 !important;
    min-width: fit-content !important;
    max-width: inherit !important;
    white-space: nowrap !important;
    position: absolute !important;
}

/* Fix z-index layering - left pane above right pane so dropdowns can overlap */
.hua-pane-left {
    position: relative !important;
    z-index: 2 !important;
}

.hua-pane-right {
    position: relative !important;
    z-index: 1 !important;
}

/* Photopea button success state animations */
@keyframes success-flash {
    0% { background-color: var(--button-secondary-background-fill); }
    50% { background-color: #22c55e; }
    100% { background-color: var(--button-secondary-background-fill); }
}

@keyframes success-flash-primary {
    0% { background-color: var(--button-primary-background-fill); }
    50% { background-color: #22c55e; }
    100% { background-color: var(--button-primary-background-fill); }
}

.photopea-success {
    animation: success-flash 1.5s ease-in-out;
}

.photopea-success-primary {
    animation: success-flash-primary 1.5s ease-in-out;
}
"""

def get_image_constraint_js():
    """JavaScript to enforce image constraints - FORGE APPROACH (dynamic expansion)"""
    return """
<script>
(function() {
    // Forge approach: Only constrain images, let container expand naturally
    function constrainImages() {
        const container = document.querySelector('#hua-image-input');
        if (!container) return;

        // Constrain images and canvases only
        container.querySelectorAll('img').forEach(img => {
            img.style.maxHeight = '600px';
            img.style.maxWidth = '100%';
            img.style.objectFit = 'scale-down';
            img.style.display = 'block';
            img.style.margin = '0 auto';
        });

        container.querySelectorAll('canvas').forEach(canvas => {
            canvas.style.maxHeight = '600px';
            canvas.style.maxWidth = '100%';
            canvas.style.objectFit = 'scale-down';
            canvas.style.display = 'block';
            canvas.style.margin = '0 auto';
        });

        // Let container grow naturally - no max-height restriction
        container.style.overflow = 'visible';
    }

    // Run on load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => setTimeout(constrainImages, 100));
    } else {
        setTimeout(constrainImages, 100);
    }

    // Watch for new images
    const observer = new MutationObserver(() => setTimeout(constrainImages, 50));
    setTimeout(() => {
        const target = document.querySelector('#hua-image-input');
        if (target) observer.observe(target, { childList: true, subtree: true });
    }, 300);
})();
</script>
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
