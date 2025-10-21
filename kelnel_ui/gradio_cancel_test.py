import requests  # Used to send HTTP requests

# Default ComfyUI server URL (retained for reference)
# DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"  # Not used directly in this helper

def cancel_comfyui_task_action(comfyui_url_base):
    """Send an interrupt request to the ComfyUI server."""
    interrupt_url = f"{comfyui_url_base}/interrupt"
    status_message = ""
    try:
        # Use print for diagnostics because this module might be imported without a logger.
        print(f"Attempting to send interrupt request to: {interrupt_url}")
        response = requests.post(interrupt_url, timeout=5)  # short timeout keeps the UI responsive
        if response.status_code == 200:
            status_message = f"Interrupt request sent to {interrupt_url}."
            print(status_message)
        else:
            status_message = f"Failed to send interrupt request. Status: {response.status_code}. Response: {response.text}"
            print(status_message)
    except requests.exceptions.ConnectionError:
        status_message = f"Failed to connect to ComfyUI server ({comfyui_url_base}). Ensure it is running and the address is correct."
        print(status_message)
    except requests.exceptions.Timeout:
        status_message = f"Timeout sending interrupt request to {interrupt_url}."
        print(status_message)
    except Exception as e:
        status_message = f"Error while sending interrupt request: {str(e)}"
        print(status_message)
    return status_message

# The original Gradio demo and `if __name__ == "__main__":` block were removed
# because gradio_workflow.py simply imports and uses cancel_comfyui_task_action.
# Restore the previous Blocks example if you need to test this helper on its own.
