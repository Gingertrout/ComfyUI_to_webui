import gradio as gr
import time
import os
import uuid

# --- Dependencies and initialization ---
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("Warning: psutil not installed. System monitoring will be limited.")

NVML_AVAILABLE = False
NVML_INITIALIZED = False
nvml = None
gpu_handles = []
try:
    import pynvml
    nvml = pynvml
    pynvml.nvmlInit()
    NVML_INITIALIZED = True
    NVML_AVAILABLE = True
    device_count = pynvml.nvmlDeviceGetCount()
    if not device_count:
        NVML_AVAILABLE = False
        print("pynvml initialized, but no NVIDIA GPU detected.")
    else:
        for i in range(device_count):
            gpu_handles.append(pynvml.nvmlDeviceGetHandleByIndex(i))
except Exception as e: 
    NVML_AVAILABLE = False
    NVML_INITIALIZED = False
    print(f"pynvml initialization/import failed: {e}. NVIDIA GPU monitoring unavailable.")

# --- Data collection helpers ---
def get_real_cpu_info():
    if not PSUTIL_AVAILABLE: return {"usage": 0, "error": "psutil not available"}
    try: return {"usage": psutil.cpu_percent(interval=0.1)}
    except Exception as e: return {"usage": 0, "error": str(e)}

def get_real_ram_info():
    if not PSUTIL_AVAILABLE: return {"used_gb": 0, "total_gb": 0, "percent": 0, "error": "psutil not available"}
    try:
        mem = psutil.virtual_memory()
        return {"used_gb": round(mem.used/(1024**3),1), "total_gb": round(mem.total/(1024**3),1), "percent": mem.percent}
    except Exception as e: return {"used_gb": 0, "total_gb": 0, "percent": 0, "error": str(e)}

def get_real_gpu_info():
    if not NVML_AVAILABLE or not gpu_handles: # NVML_INITIALIZED implies NVML_AVAILABLE
        return {"gpus": [], "error": "NVML not available or no GPUs"}
    gpus_data = []
    try:
        for i, handle in enumerate(gpu_handles):
            raw_name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(raw_name, bytes):
                name = raw_name.decode('utf-8')
            else:
                name = raw_name # Already a string
            util = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            temp = "N/A"
            try:
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            except pynvml.NVMLError:
                pass 

            gpus_data.append({
                "name": name,
                "utilization": util,
                "vram_used_gb": round(mem.used / (1024**3), 1),
                "vram_total_gb": round(mem.total / (1024**3), 1),
                "temperature": temp
            })
        return {"gpus": gpus_data}
    except Exception as e:
        return {"gpus": [], "error": str(e)}

def get_real_hdd_info():
    if not PSUTIL_AVAILABLE: return {"disks": [], "error": "psutil not available"}
    disks_info = []
    # Define common Linux/macOS filesystems to ignore
    # macOS specific: 'apfs' (often has multiple utility partitions), 'devfs'
    # Linux specific: 'tmpfs', 'squashfs', 'devtmpfs', 'overlay', 'autofs', 'fuse.gvfsd-fuse'
    # General virtual/system: 'proc', 'sysfs', 'cgroup', 'debugfs', 'pstore', 'efivarfs'
    # Network filesystems that might not be relevant for local disk space: 'nfs', 'cifs', 'smbfs'
    ignore_fstypes = ['tmpfs', 'squashfs', 'devtmpfs', 'overlay', 'autofs', 
                      'proc', 'sysfs', 'cgroup', 'debugfs', 'pstore', 'efivarfs', 
                      'fuse.gvfsd-fuse', 'devfs']
    # Define mountpoint prefixes to ignore, especially for Linux
    ignore_mountpoint_prefixes = []
    if os.name != 'nt': # Apply only on non-Windows (Linux, macOS, etc.)
        ignore_mountpoint_prefixes.extend(['/boot', '/snap', '/var/lib/docker', '/run/user'])

    try:
        for p in psutil.disk_partitions(all=False): # all=False to attempt to filter pseudo, duplicate, inaccessible FSes
            # Basic filtering applicable to all OS
            if not p.fstype or not os.path.exists(p.mountpoint) or 'cdrom' in p.opts:
                continue
            
            # OS-specific filtering
            if os.name == 'nt': # Windows-specific
                if 'removable' in p.opts and p.fstype.lower() not in ['ntfs', 'fat32', 'exfat']: # Keep removable if common fs
                    continue
            else: # Linux/macOS specific filtering
                if p.fstype.lower() in ignore_fstypes:
                    continue
                if any(p.mountpoint.startswith(prefix) for prefix in ignore_mountpoint_prefixes):
                    continue
                # Avoid very small partitions that are likely system-reserved or special purpose
                try:
                    usage_check = psutil.disk_usage(p.mountpoint)
                    if usage_check.total < (1 * 1024**3): # Less than 1GB, potentially ignorable
                        # More specific checks could be added here if needed
                        pass # For now, allow small partitions if not otherwise filtered
                except Exception:
                    continue # If we can't get usage, skip

            try:
                usage = psutil.disk_usage(p.mountpoint)
                # Ensure we only add partitions with a reported total size > 0 to avoid clutter
                if usage.total > 0:
                    disks_info.append({
                        "mountpoint": p.mountpoint,
                        "total_gb": round(usage.total / (1024**3), 1),
                        "used_gb": round(usage.used / (1024**3), 1),
                        "percent": usage.percent
                    })
                if len(disks_info) >= 2:  # Limit to 2 disks for display
                    break
            except Exception: # Catch errors during disk_usage or appending
                continue 
        return {"disks": disks_info}
    except Exception as e:
        return {"disks": [], "error": str(e)}

# --- HTML construction helpers ---
def create_compact_progress_display_html(unique_id_prefix, label_text, current_value, unit, max_value=100, bar_color="dodgerblue", label_color="black", error_msg=None):
    bar_id = f"{unique_id_prefix}-bar-{uuid.uuid4().hex[:8]}"
    text_id = f"{unique_id_prefix}-text-{uuid.uuid4().hex[:8]}"

    base_style = "margin-bottom: 4px; padding: 2px; border-radius: 3px; display: flex; align-items: center;"
    # Enforce a consistent label width (80px) so text stays right-aligned.
    label_style = f"font-size: 0.75em; color: #FFFFFF; background-color: transparent; padding: 2px 4px; border-radius: 2px; margin-right: 8px; white-space: nowrap; text-align: right; box-sizing: border-box; width: 80px;"
    bar_outer_style = "background-color: #202020; border-radius: 2px; overflow: hidden; height: 20px; flex-grow: 1;"
    bar_inner_style_template = "width: {0}%; background-color: {1}; height: 100%; text-align: center; color: white; line-height: 20px; font-size: 0.7em; transition: width 0.5s ease-in-out;"

    if error_msg:
        # Keep the error label aligned with the rest when a width is defined.
        # Note: setting label_style width also affects this error block.
        return f"""<div style="{base_style} background-color: #404040;">
            <span style="{label_style}">{label_text}:</span> 
            <p style="flex-grow: 1; color: #ffdddd; text-align: center;"><strong>Error</strong> <span style="font-size:0.8em; color: #ff8888;">({error_msg})</span></p>
        </div>""", None, None, 0, "Error"

    percentage_value = 0
    display_text = f"{current_value}{unit}"
    if unit == "%":
        try: percentage_value = float(current_value)
        except (ValueError, TypeError): percentage_value = 0
        display_text = f"{percentage_value:.1f}%"
    elif isinstance(current_value, (int, float)) and isinstance(max_value, (int, float)) and max_value > 0:
        try: percentage_value = (float(current_value) / max_value) * 100
        except (ValueError, TypeError): percentage_value = 0
    
    percentage_value = max(0, min(100, percentage_value))
    bar_inner_style = bar_inner_style_template.format(percentage_value, bar_color)

    # Prepare text for inside the bar
    # 'display_text' already contains the primary value string (e.g., "X.XG/Y.YG" or "N/A°C")
    # 'percentage_value' is the numeric percentage for the bar width
    
    text_inside_bar = f"{display_text} ({percentage_value:.1f}%)"
    if unit == "%": # If the original unit was '%', display_text is already "XX.X%"
        text_inside_bar = display_text # display_text is already formatted as "XX.X%"
    elif current_value == "N/A" and unit == "°C": # Special case for temperature N/A
         text_inside_bar = "N/A"
    elif current_value == "N/A": # General case for N/A value
         text_inside_bar = "N/A"
    elif unit == "°C": # For temperature with actual value
        text_inside_bar = f"{current_value}{unit} ({percentage_value:.1f}%)"


    html_structure = f"""
    <div style="{base_style}">
        <span style="{label_style}">{label_text}</span>
        <div style="{bar_outer_style}">
            <div id="{bar_id}" style="{bar_inner_style}">
                {text_inside_bar}
            </div>
        </div>
    </div>"""
    # The 'text_id' was for the strong tag next to the label, which is now removed.
    # We need to decide if 'text_id' is still needed or how to update the inner bar text via JS.
    # For now, 'text_id' will be returned as None or an adapted role.
    # The JS update logic will need to target bar_id's innerText.
    return html_structure, bar_id, text_id, percentage_value, text_inside_bar # Returning text_inside_bar for JS updates

# --- Gradio update stream ---
def update_floating_monitors_stream():
    # global NVML_INITIALIZED, NVML_AVAILABLE, gpu_handles, nvml # No longer needed for re-init
    # The NVML initialization is now expected to be done at the module level (on import)
    # and cleanup via atexit. This stream function should not attempt re-initialization.

    initial_html = "<div id='floating-monitors-content' class='floating-monitor-style-inner'>Loading system monitors...</div><script></script>"
    yield initial_html

    while True:
        all_html_parts = ["<div id='floating-monitors-content' class='floating-monitor-style-inner'>"]
        script_parts = ["<script> try { "]
        light_gray_label_color = "#aaaaaa"

        cpu_data = get_real_cpu_info()
        # For CPU, current_value is usage %, unit is "%". text_inside_bar will be "usage%".
        html, bid, tid, perc, dtxt = create_compact_progress_display_html("cpu", "CPU", cpu_data.get("usage",0), "%", bar_color="dodgerblue", label_color=light_gray_label_color, error_msg=cpu_data.get("error"))
        all_html_parts.append(html)
        if bid: script_parts.append(f"var barEl = document.getElementById('{bid}'); if(barEl) {{ barEl.style.width='{perc}%'; barEl.innerText='{dtxt}'; }} try {{var textEl = document.getElementById('{tid}'); if(textEl) textEl.innerText='';}}catch(e){{}}")

        ram_data = get_real_ram_info()
        # For RAM, current_value is used_gb, unit is "G / total_gbG", max_value is total_gb.
        # text_inside_bar will be "used_gbG / total_gbG (percent%)".
        ram_used_gb = ram_data.get('used_gb',0)
        ram_total_gb = ram_data.get('total_gb',0)
        ram_unit_detail = f"G / {ram_total_gb}G" if ram_total_gb > 0 else "G"
        html, bid, tid, perc, dtxt = create_compact_progress_display_html(
            "ram", "RAM", ram_used_gb, ram_unit_detail, 
            max_value=ram_total_gb if ram_total_gb > 0 else 1, # Avoid division by zero if total_gb is 0
            bar_color="mediumseagreen", label_color=light_gray_label_color, error_msg=ram_data.get("error")
        )
        all_html_parts.append(html)
        if bid: script_parts.append(f"var barEl = document.getElementById('{bid}'); if(barEl) {{ barEl.style.width='{perc}%'; barEl.innerText='{dtxt}'; }} try {{var textEl = document.getElementById('{tid}'); if(textEl) textEl.innerText='';}}catch(e){{}}")

        if not NVML_AVAILABLE:
            # GPU N/A: Display a bar with "GPU" label and "N/A" as its value.
            html, bid, tid, perc, dtxt = create_compact_progress_display_html(
                "gpu-na", "GPU", "N/A", "",  # current_value="N/A", unit=""
                max_value=1,  # Placeholder, as percentage will be 0
                bar_color="#777777",  # Grey color for N/A bar
                label_color=light_gray_label_color,
                error_msg=None # Ensure no error styling is applied
            )
            all_html_parts.append(html)
            if bid: script_parts.append(f"var barEl = document.getElementById('{bid}'); if(barEl) {{ barEl.style.width='{perc}%'; barEl.innerText='{dtxt}'; }} try {{var textEl = document.getElementById('{tid}'); if(textEl) textEl.innerText='';}}catch(e){{}}")

        else:
            gpu_data = get_real_gpu_info()
            if gpu_data.get("error") and not gpu_data.get("gpus"):
                 all_html_parts.append(f"<p style='font-size:0.75em; color:red;'>GPU Error: {gpu_data.get('error')}</p>")
            if not gpu_data.get("gpus") and not gpu_data.get("error"):
                 all_html_parts.append("<p style='font-size:0.75em; color:#555; margin-bottom:2px;'>No NVIDIA GPUs detected.</p>")

            for i, gpu in enumerate(gpu_data.get("gpus", [])):
                name_short = gpu.get('name','GPU').split(' ')[-1][:10] # This line is kept for potential future use or logging, but name_short is not used in label
                
                # GPU Util: current_value is utilization %, unit is "%". Bar shows "utilization%".
                html, bid, tid, perc, dtxt = create_compact_progress_display_html(f"gpu{i}-util", f"GPU {i} Util", gpu.get("utilization",0), "%", bar_color="tomato", label_color=light_gray_label_color)
                all_html_parts.append(html); 
                if bid: script_parts.append(f"var barEl = document.getElementById('{bid}'); if(barEl) {{ barEl.style.width='{perc}%'; barEl.innerText='{dtxt}'; }} try {{var textEl = document.getElementById('{tid}'); if(textEl) textEl.innerText='';}}catch(e){{}}")
                
                # GPU VRAM: current_value is vram_used_gb, unit is "G / vram_total_gbG", max_value is vram_total_gb.
                # Bar shows "vram_usedG / vram_totalG (percent%)".
                vram_used = gpu.get('vram_used_gb',0); vram_total = gpu.get('vram_total_gb',0)
                vram_unit_detail = f"G / {vram_total}G" if vram_total > 0 else "G"
                html, bid, tid, perc, dtxt = create_compact_progress_display_html(
                    f"gpu{i}-vram", f"GPU {i} VRAM", vram_used, vram_unit_detail,
                    max_value=vram_total if vram_total > 0 else 1,
                    bar_color="orange", label_color=light_gray_label_color
                )
                all_html_parts.append(html)
                if bid: script_parts.append(f"var barEl = document.getElementById('{bid}'); if(barEl) {{ barEl.style.width='{perc}%'; barEl.innerText='{dtxt}'; }} try {{var textEl = document.getElementById('{tid}'); if(textEl) textEl.innerText='';}}catch(e){{}}")

                # GPU Temp: current_value is temp_val, unit is "°C". Bar shows "temp°C (percent%)" or "N/A".
                temp_val = gpu.get("temperature","N/A"); temp_unit = "°C" # unit is always °C for logic in create_compact
                html, bid, tid, perc, dtxt = create_compact_progress_display_html(
                    f"gpu{i}-temp", f"GPU {i} Temp", temp_val, temp_unit, 
                    max_value=100, bar_color="lightcoral", label_color=light_gray_label_color
                )
                all_html_parts.append(html)
                if bid: script_parts.append(f"var barEl = document.getElementById('{bid}'); if(barEl) {{ barEl.style.width='{perc}%'; barEl.innerText='{dtxt}'; }} try {{var textEl = document.getElementById('{tid}'); if(textEl) textEl.innerText='';}}catch(e){{}}")
        
        hdd_data = get_real_hdd_info()
        if hdd_data.get("error"):
            all_html_parts.append(f"<p style='font-size:0.75em; color:red;'>Disk Error: {hdd_data.get('error')}</p>")
        if not hdd_data.get("disks") and not hdd_data.get("error"):
            all_html_parts.append("<p style='font-size:0.75em; color:#555; margin-bottom:2px;'>No disk information available.</p>")
        for i, disk in enumerate(hdd_data.get("disks", [])):
            # HDD: current_value is used_gb, unit is "G / total_gbG", max_value is total_gb.
            # Bar shows "used_gbG / total_gbG (percent%)".
            disk_label_short = f"Disk {disk.get('mountpoint','?')[0]}"
            disk_used_gb = disk.get('used_gb',0)
            disk_total_gb = disk.get('total_gb',0)
            disk_unit_detail = f"G / {disk_total_gb}G" if disk_total_gb > 0 else "G"
            html, bid, tid, perc, dtxt = create_compact_progress_display_html(
                f"hdd{i}", disk_label_short, disk_used_gb, disk_unit_detail,
                max_value=disk_total_gb if disk_total_gb > 0 else 1,
                bar_color="mediumpurple", label_color=light_gray_label_color
            )
            all_html_parts.append(html)
            if bid: script_parts.append(f"var barEl = document.getElementById('{bid}'); if(barEl) {{ barEl.style.width='{perc}%'; barEl.innerText='{dtxt}'; }} try {{var textEl = document.getElementById('{tid}'); if(textEl) textEl.innerText='';}}catch(e){{}}")

        all_html_parts.append("</div>")
        script_parts.append(" } catch(e) { console.error('Error updating monitor UI:', e); } </script>")
        final_html_payload = "".join(all_html_parts) + "".join(script_parts)
        yield final_html_payload
        time.sleep(1)

custom_css = """
/* .monitor-relative-container {
    position: relative;
    padding: 10px; 
    border: 1px dashed #ccc; 
    min-height: 300px; 
} */

#log_area_relative_wrapper {
    position: relative;
    padding: 5px; /* keep space for the floating monitor overlay */
}

.floating-monitor-outer-wrapper {
    position: absolute;
    top: 5px;      /* offset 5px from the parent's top */
    right: 20px;     /* offset 20px from the parent's right edge */
    width: 80%;    /* occupy roughly 80% of the parent width */
    height: 70%;   /* occupy roughly 70% of the parent height */
    padding: 5px;
    # background-color: rgba(50, 50, 50, 0.8); /* optional semi-transparent dark background */
    /* border: 1px solid #ccc; */ /* border removed for a cleaner look */
    border-radius: 4px;
    z-index: 1000;  /* ensure it sits above the log text */
    /* box-shadow: 0px 2px 8px rgba(0,0,0,0.15); */ /* shadow intentionally removed */
    overflow-y: auto; /* show a vertical scrollbar when content overflows */
    overflow-x: hidden; /* avoid horizontal scrolling to keep layout tight */
}
.floating-monitor-style-inner p { /* style paragraphs inside the compact display */
    margin-top: 0;
}
"""

def cleanup_nvml():
    global NVML_INITIALIZED, nvml
    if NVML_INITIALIZED and nvml:
        try:
            nvml.nvmlShutdown()
            print("pynvml shutdown successfully.")
        except Exception as e:
            print(f"Error during pynvml shutdown: {e}")
    NVML_INITIALIZED = False

if __name__ == "__main__":
    print("System monitor module standalone test...")
    with gr.Blocks(title="System Resource Monitor Test", theme=gr.themes.Soft(), css=custom_css) as test_demo:
        gr.Markdown("# 💻 System Resource Monitor (Module Test)")
        with gr.Group(elem_id="log_area_relative_wrapper"):
            gr.Textbox(label="Simulated Log Output", lines=20, value=("Simulated log...\n" * 10), elem_classes="log-display-container")
            floating_monitor_html_output = gr.HTML(elem_classes="floating-monitor-outer-wrapper")
        test_demo.load(fn=update_floating_monitors_stream,inputs=None,outputs=[floating_monitor_html_output])
    try: test_demo.launch()
    finally: cleanup_nvml()
