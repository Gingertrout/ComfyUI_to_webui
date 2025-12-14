"""
Configuration settings for ComfyUI_to_webui V2

This module contains all constants, URLs, and default settings for the application.
"""

from dataclasses import dataclass
from typing import Set
import os


# ============================================================================
# ComfyUI Server Configuration
# ============================================================================

COMFYUI_BASE_URL = "http://127.0.0.1:8188"
COMFYUI_WS_URL = "ws://127.0.0.1:8188/ws"


# ============================================================================
# API Endpoints
# ============================================================================

class ComfyUIEndpoints:
    """ComfyUI API endpoints"""
    PROMPT = "/prompt"
    QUEUE = "/queue"
    HISTORY = "/history"
    OBJECT_INFO = "/object_info"
    INTERRUPT = "/interrupt"
    SYSTEM_STATS = "/system_stats"

    @classmethod
    def get_history_url(cls, client_id: str) -> str:
        return f"{cls.HISTORY}/{client_id}"


# ============================================================================
# Timeout & Polling Configuration
# ============================================================================

@dataclass
class TimeoutConfig:
    """Timeout and polling interval configuration"""
    # Prompt execution timeout (seconds)
    prompt_execution: float = 300.0

    # History API polling interval (seconds)
    history_poll_interval: float = 0.75

    # Queue API polling interval (seconds)
    queue_poll_interval: float = 0.5

    # HTTP request timeout (seconds)
    http_request: float = 30.0

    # WebSocket connection timeout (seconds)
    websocket: float = 10.0

    # Max retries for failed requests
    max_retries: int = 5

    # Retry delay for failed requests (seconds)
    retry_delay: float = 10.0


# Default timeout configuration instance
DEFAULT_TIMEOUTS = TimeoutConfig()


# ============================================================================
# Node Type Classification
# ============================================================================

# Output node types (for result retrieval)
OUTPUT_NODE_TYPES: Set[str] = {
    "SaveImage",
    "PreviewImage",
    "VHS_VideoCombine",
    "SaveAnimatedWEBP",
    "SaveAnimatedPNG",
}

# Image input node types
IMAGE_INPUT_NODE_TYPES: Set[str] = {
    "LoadImage",
    "LoadAndResizeImage",
    "ImageInput",
}

# Video input node types
VIDEO_INPUT_NODE_TYPES: Set[str] = {
    "VHS_LoadVideo",
    "LoadVideo",
    "VideoInput",
}

# Sampler node types (for grouping in UI)
SAMPLER_NODE_TYPES: Set[str] = {
    "KSampler",
    "KSamplerAdvanced",
    "KSamplerSDXL",
    "KSamplerLite",
    "KPyramidSampler",
    "SamplerCustom",
}

# LoRA loader node types
LORA_NODE_TYPES: Set[str] = {
    "LoraLoader",
    "LoraLoaderModelOnly",
    "PowerLoraLoader",  # rgthree multi-lora
}

# Checkpoint/model loader node types
CHECKPOINT_NODE_TYPES: Set[str] = {
    "CheckpointLoaderSimple",
    "CheckpointLoader",
}

# UNET loader node types
UNET_NODE_TYPES: Set[str] = {
    "UNETLoader",
    "UnetLoader",
}


# ============================================================================
# ComfyUI Type Definitions
# ============================================================================

# Primitive types that can be edited via UI
PRIMITIVE_TYPES: Set[str] = {
    "INT",
    "INTEGER",
    "FLOAT",
    "DOUBLE",
    "STRING",
    "BOOLEAN",
    "BOOL",
}

# Complex types that are typically connected (non-editable)
COMPLEX_TYPES: Set[str] = {
    "MODEL",
    "CLIP",
    "VAE",
    "CONDITIONING",
    "LATENT",
    "IMAGE",
    "MASK",
    "CONTROL_NET",
    "STYLE_MODEL",
    "GLIGEN",
}


# ============================================================================
# Gradio Configuration
# ============================================================================

# Default Gradio server ports to try (will use first available)
GRADIO_PORTS = [7861, 7862, 7863, 7864, 7865, 7866, 7867, 7868, 7869, 7870]

# Default Gradio theme
GRADIO_THEME = "default"

# Maximum image dimensions for display
MAX_DISPLAY_WIDTH = 1920
MAX_DISPLAY_HEIGHT = 1920


# ============================================================================
# File System Configuration
# ============================================================================

# Workflow state cache location
STATE_CACHE_DIR = os.path.expanduser("~/.comfyui_to_webui_v2")
STATE_CACHE_FILE = os.path.join(STATE_CACHE_DIR, "workflow_state_cache.json")

# Ensure state cache directory exists
os.makedirs(STATE_CACHE_DIR, exist_ok=True)


# ============================================================================
# UI Configuration
# ============================================================================

# Component grouping preferences
@dataclass
class UIConfig:
    """UI generation configuration"""
    # Show linked inputs as read-only (vs hiding completely)
    show_linked_inputs: bool = False

    # Use sliders vs number inputs for INT/FLOAT
    prefer_sliders: bool = True

    # Slider threshold for INT (use slider if range <= this value)
    int_slider_threshold: int = 1000

    # Slider threshold for FLOAT (use slider if range <= this value)
    float_slider_threshold: float = 100.0

    # Default multiline threshold for STRING inputs
    multiline_threshold: int = 50  # Use multiline if default length > this

    # Group components by node type
    group_by_node_type: bool = True

    # Collapse accordions by default
    collapse_by_default: bool = True


# Default UI configuration instance
DEFAULT_UI_CONFIG = UIConfig()


# ============================================================================
# Logging Configuration
# ============================================================================

# Log message format
LOG_FORMAT = "[{timestamp}] [{level}] {message}"

# Log levels
class LogLevel:
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# ============================================================================
# Version Information
# ============================================================================

VERSION = "2.0.0-alpha"
PROJECT_NAME = "ComfyUI_to_webui V2"
PROJECT_DESCRIPTION = "Dynamic Gradio interface for ComfyUI workflows"
