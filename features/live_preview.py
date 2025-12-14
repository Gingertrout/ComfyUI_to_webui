import gradio as gr
import json
import threading
import time
from PIL import Image
import io
import base64

try:
    import websocket  # websocket-client exposes this module
    if not hasattr(websocket, "create_connection"):
        _create_connection = None
        try:
            from websocket._core import create_connection as _create_connection  # websocket-client < 1.7 fallback
        except Exception:
            try:
                from websocket import client as _websocket_client
                _create_connection = getattr(_websocket_client, "create_connection", None)
            except Exception:
                _create_connection = None
        if _create_connection is None:
            raise ImportError("websocket module missing 'create_connection'")
        websocket.create_connection = _create_connection
    _WEBSOCKET_AVAILABLE = True
    _WEBSOCKET_IMPORT_ERROR = None
    print(f"ComfyUI_to_webui preview: websocket module loaded from {getattr(websocket, '__file__', 'unknown')}")
except Exception as e:
    websocket = None
    _WEBSOCKET_AVAILABLE = False
    _WEBSOCKET_IMPORT_ERROR = e

# Default Configuration (can be overridden during class instantiation)
DEFAULT_COMFYUI_SERVER_ADDRESS = "127.0.0.1:8188"
DEFAULT_CLIENT_ID_PREFIX = "gradio_k_sampler_passive_previewer_cline_"

if websocket is not None:
    WebSocketTimeoutException = getattr(websocket, "WebSocketTimeoutException", Exception)
    WebSocketConnectionClosedException = getattr(websocket, "WebSocketConnectionClosedException", Exception)
    WebSocketException = getattr(websocket, "WebSocketException", Exception)
else:
    WebSocketTimeoutException = WebSocketConnectionClosedException = WebSocketException = Exception

class ComfyUIPreviewer:
    def __init__(self, server_address=None, client_id_suffix="main_workflow", min_yield_interval=0.05):
        self.server_address = server_address or DEFAULT_COMFYUI_SERVER_ADDRESS
        # Ensure client_id is unique if multiple instances are used
        timestamp = int(time.time() * 1000) # Add timestamp for more uniqueness
        self.client_id = f"{DEFAULT_CLIENT_ID_PREFIX}{client_id_suffix}_{timestamp}"

        self.latest_preview_image = None
        self.image_update_event = threading.Event()
        self.active_prompt_info = {
            "current_executing_node": None,
            "is_worker_globally_active": False, # Will be set to True by start_worker
            "progress_value": None,  # Current step number
            "progress_max": None,    # Total steps
        }
        self.active_prompt_lock = threading.Lock()
        self.preview_worker_thread = None
        self.min_yield_interval = min_yield_interval
        self.websocket_available = _WEBSOCKET_AVAILABLE and websocket is not None
        self.websocket_import_error = _WEBSOCKET_IMPORT_ERROR
        if self.websocket_available:
            self.ws_connection_status = "Disconnected"
        else:
            reason = "Preview disabled: websocket-client not available"
            if self.websocket_import_error is not None:
                reason += f" ({self.websocket_import_error})"
            self.ws_connection_status = reason

    def _image_preview_worker(self):
        if not self.websocket_available or websocket is None:
            reason = "WebSocket preview disabled. Install the 'websocket-client' package to enable live previews."
            if self.websocket_import_error is not None:
                reason += f" ({self.websocket_import_error})"
            self.ws_connection_status = reason
            print(f"[{self.client_id}] {reason}")
            return

        ws_url = f"ws://{self.server_address}/ws?clientId={self.client_id}"
        ws = None

        print(f"[{self.client_id}] Preview worker thread started.")
        while self.active_prompt_info.get("is_worker_globally_active", True):
            try:
                self.ws_connection_status = f"Connecting to {ws_url}..."
                ws = websocket.create_connection(ws_url, timeout=10)
                self.ws_connection_status = "WebSocket connected"
                print(f"[{self.client_id}] WebSocket connection established to {ws_url}.")
                
                while self.active_prompt_info.get("is_worker_globally_active", True):
                    if not ws.connected:
                        self.ws_connection_status = "WebSocket disconnected"
                        print(f"[{self.client_id}] WebSocket disconnected. Breaking for reconnect.")
                        break
                    
                    try:
                        # Set a timeout for recv to allow checking is_worker_globally_active periodically
                        ws.settimeout(1.0) 
                        received_message = ws.recv()
                        ws.settimeout(None) # Reset timeout after successful receive
                    except WebSocketTimeoutException:
                        # Timeout is expected, just continue to check the loop condition
                        continue 
                    except WebSocketConnectionClosedException:
                        self.ws_connection_status = "WebSocket connection closed"
                        print(f"[{self.client_id}] WebSocket connection closed during active receive.")
                        break 
                    except Exception as e:
                        self.ws_connection_status = f"WebSocket error: {e}"
                        print(f"[{self.client_id}] WebSocket error during active receive: {e}")
                        break

                    pil_image_to_update = None
                    if isinstance(received_message, str):
                        try:
                            message_data = json.loads(received_message)
                            msg_type = message_data.get('type')
                            
                            with self.active_prompt_lock:
                                if msg_type == 'status': # ComfyUI status message
                                    data = message_data.get('data', {})
                                    # Potentially update some status if needed
                                    # print(f"[{self.client_id}] Status: {data}")
                                elif msg_type == 'executing':
                                    data = message_data.get('data', {})
                                    self.active_prompt_info["current_executing_node"] = data.get('node')
                                    if data.get('node') is None and data.get('prompt_id'): # Execution finished for this prompt
                                        self.active_prompt_info["current_executing_node"] = "Idle"
                                        # Reset progress when execution completes
                                        self.active_prompt_info["progress_value"] = None
                                        self.active_prompt_info["progress_max"] = None


                                elif msg_type == 'progress':
                                    data = message_data.get('data', {})
                                    # Capture progress information (current step / total steps)
                                    progress_value = data.get('value')
                                    progress_max = data.get('max')
                                    if progress_value is not None and progress_max is not None:
                                        self.active_prompt_info["progress_value"] = progress_value
                                        self.active_prompt_info["progress_max"] = progress_max

                                    preview_b64 = data.get('preview_image')
                                    if preview_b64:
                                        try:
                                            # Previews are often jpeg, remove data:image/jpeg;base64, if present
                                            if ',' in preview_b64:
                                                preview_b64 = preview_b64.split(',')[1]
                                            img_data = base64.b64decode(preview_b64)
                                            pil_image_to_update = Image.open(io.BytesIO(img_data))
                                        except Exception as e:
                                            print(f"[{self.client_id}] Error decoding base64 preview from progress: {e}")
                        except json.JSONDecodeError:
                            # print(f"[{self.client_id}] JSONDecodeError: {received_message}")
                            pass 
                    
                    elif isinstance(received_message, bytes): # Binary message (typically direct image data)
                        try:
                            # Assuming the binary message is an image (e.g., from a custom node)
                            # ComfyUI's default binary previews might have a 4-byte type and 4-byte event before image data
                            # ComfyUI's default binary previews (e.g., from KSampler)
                            # often have an 8-byte header:
                            # 4 bytes for message type (e.g., 1 for PREVIEW_IMAGE)
                            # 4 bytes for event type (e.g., 1 for UPDATE, 2 for DONE/FINAL)
                            # The actual image data follows this header.
                            if len(received_message) > 8:
                                image_bytes = received_message[8:] # Skip the 8-byte header
                                pil_image_to_update = Image.open(io.BytesIO(image_bytes))
                            else:
                                # Message too short to be a valid preview with header
                                print(f"[{self.client_id}] Received binary message too short to be a preview: {len(received_message)} bytes")
                        except Exception as e:
                            print(f"[{self.client_id}] Error processing binary preview: {e}. Data length: {len(received_message)}")
                            pass
                    
                    if pil_image_to_update:
                        self.latest_preview_image = pil_image_to_update
                        self.image_update_event.set()

            except WebSocketException as e:
                self.ws_connection_status = f"WebSocket connection error: {e}"
                print(f"[{self.client_id}] WebSocket connection error: {e}. Retrying in 5 seconds...")
            except ConnectionRefusedError:
                self.ws_connection_status = "Connection refused. ComfyUI server may be offline or address is incorrect."
                print(f"[{self.client_id}] Connection refused. Is ComfyUI server running at {self.server_address}? Retrying in 10 seconds...")
            except Exception as e:
                self.ws_connection_status = f"Preview worker encountered an unexpected error: {e}"
                print(f"[{self.client_id}] Unexpected error in preview worker: {e}. Retrying in 5 seconds...")
            finally:
                if ws:
                    ws.close()
                if self.active_prompt_info.get("is_worker_globally_active", True):
                    print(f"[{self.client_id}] WebSocket connection closed. Will attempt to reconnect if worker is still active.")
                    time.sleep(5) # Wait before retrying connection
                else:
                    self.ws_connection_status = "Preview worker stopped"
                    print(f"[{self.client_id}] WebSocket worker shutting down.")
        
        self.ws_connection_status = "Preview worker finished"
        print(f"[{self.client_id}] Passive preview worker thread finished.")

    def start_worker(self):
        if not self.websocket_available or websocket is None:
            reason = "Preview worker not started because websocket-client is unavailable."
            if self.websocket_import_error is not None:
                reason += f" ({self.websocket_import_error})"
            print(f"[{self.client_id}] {reason}")
            self.ws_connection_status = reason
            return
        if self.preview_worker_thread and self.preview_worker_thread.is_alive():
            print(f"[{self.client_id}] Preview worker already running.")
            return
        
        self.active_prompt_info["is_worker_globally_active"] = True
        self.preview_worker_thread = threading.Thread(target=self._image_preview_worker, daemon=True)
        self.preview_worker_thread.start()

    def stop_worker(self):
        print(f"[{self.client_id}] Attempting to stop preview worker...")
        self.active_prompt_info["is_worker_globally_active"] = False
        if self.preview_worker_thread and self.preview_worker_thread.is_alive():
            print(f"[{self.client_id}] Waiting for preview worker to finish...")
            self.preview_worker_thread.join(timeout=5)
            if self.preview_worker_thread.is_alive():
                print(f"[{self.client_id}] Preview worker did not finish in time.")
            else:
                print(f"[{self.client_id}] Preview worker finished.")
        else:
            print(f"[{self.client_id}] Preview worker was not running or already stopped.")
        self.ws_connection_status = "Preview worker stopped"

    def get_progress_info(self):
        """
        Returns the current progress information.
        Returns: dict with keys 'value' (current step), 'max' (total steps), or None values if no progress data.
        """
        with self.active_prompt_lock:
            return {
                "value": self.active_prompt_info.get("progress_value"),
                "max": self.active_prompt_info.get("progress_max")
            }


    def get_update_generator(self):
        """
        Returns a generator function for Gradio to continuously update the UI.
        """
        def generator():
            if not self.websocket_available or websocket is None:
                message = "Preview disabled: install the 'websocket-client' package to enable live updates."
                yield None, message
                return

            print(f"[{self.client_id}] Update generator started.")
            last_yield_time = time.time()

            while self.active_prompt_info.get("is_worker_globally_active", True) or self.latest_preview_image:
                # The loop continues as long as the worker is supposed to be active,
                # OR if there's a last image to display even after worker stops (e.g. final image).
                # However, for a live preview, we might want it to stop yielding when worker stops.
                # Let's stick to worker active status for loop continuation.
                if not self.active_prompt_info.get("is_worker_globally_active", True) and not self.image_update_event.is_set():
                    # If worker is stopped and no pending image update, break the generator
                    # print(f"[{self.client_id}] Worker stopped and no pending update, exiting generator.")
                    # yield self.latest_preview_image, f"Preview stopped. {self.ws_connection_status}" # Yield one last time
                    break

                new_image_received_in_this_cycle = False
                
                # Wait for an event or a timeout
                event_is_set = self.image_update_event.wait(timeout=self.min_yield_interval / 2)
                
                if event_is_set:
                    self.image_update_event.clear()
                    new_image_received_in_this_cycle = True

                current_time = time.time()
                if current_time - last_yield_time < self.min_yield_interval:
                    sleep_duration = self.min_yield_interval - (current_time - last_yield_time)
                    time.sleep(sleep_duration)
                
                current_node_value = self.active_prompt_info.get("current_executing_node")
                node_status_display = "Idle" if current_node_value is None else str(current_node_value)
                # If current_node_value is "Idle", keep the label as "Idle".
                # If current_node_value is a node identifier, display it as a string.
                # If current_node_value is None, treat the sampler as idle.

                status_parts = []
                if self.latest_preview_image:
                    timestamp_msg = f"Last update: {time.strftime('%H:%M:%S')}" if new_image_received_in_this_cycle else f"Last display: {time.strftime('%H:%M:%S')}"
                    status_parts.append(timestamp_msg)
                else:
                    status_parts.append("Waiting for preview...")

                status_parts.append(f"Node: {node_status_display}")
                status_parts.append(f"Connection: {self.ws_connection_status}")

                final_status_msg = " | ".join(status_parts)
                yield self.latest_preview_image, final_status_msg
                
                last_yield_time = time.time()
            
            print(f"[{self.client_id}] Update generator finished.")
            # Yield a final state when generator stops
            yield self.latest_preview_image, f"Preview stopped. {self.ws_connection_status}"

        return generator

# --- Main block for testing the ComfyUIPreviewer class directly ---
if __name__ == "__main__":
    print("Starting standalone ComfyUIPreviewer test app......")
    
    # Instantiate the previewer for standalone test
    # Using a unique client_id_suffix for testing
    previewer_instance = ComfyUIPreviewer(client_id_suffix="standalone_test", min_yield_interval=0.1)
    
    with gr.Blocks(title="ComfyUI Passive Live Preview (Cline - Class Test)") as test_demo:
        gr.Markdown("# ComfyUI Passive Live Preview (class test)\nBuilt with care by Cline!")
        
        with gr.Row():
            with gr.Column(scale=3):
                gr.Markdown("### Live Preview")
                output_image = gr.Image(label="K-Sampler Preview", type="pil", interactive=False, height=768, show_label=False)
            with gr.Column(scale=1):
                gr.Markdown("### Status Information")
                status_text = gr.Textbox(label="Preview Status", interactive=False, lines=5)
                # Add a button to manually stop the worker for testing
                stop_button = gr.Button("Stop Preview Worker (test)")


        # Use demo.load to start the generator
        test_demo.load(
            fn=previewer_instance.get_update_generator(),
            inputs=[],
            outputs=[output_image, status_text]
            # Removed 'every' as fn is a generator
        )

        def handle_stop():
            previewer_instance.stop_worker()
            return "Preview worker stop requested."
        
        stop_button.click(fn=handle_stop, inputs=[], outputs=[status_text])

    # Start the preview worker thread
    previewer_instance.start_worker()
    
    print(f"Ensure the ComfyUI server is running at: {previewer_instance.server_address}")
    print(f"This test app will use client ID: {previewer_instance.client_id}")
    print("Run any ComfyUI workflow containing a KSampler (or other preview-enabled node).")
    
    try:
        test_demo.launch()
    except KeyboardInterrupt:
        print("KeyboardInterrupt caught, shutting down......")
    finally:
        print("Closing Gradio app, stopping preview worker......")
        previewer_instance.stop_worker()
        print("Standalone test app closed.")
