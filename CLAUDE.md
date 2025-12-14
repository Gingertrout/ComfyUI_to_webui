# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---
**⚠️ IMPORTANT: V1 vs V2 Documentation**

This CLAUDE.md file primarily documents the **V1 architecture** (preserved in `v1-archive` branch). The current `v2-dynamic-rewrite` branch features a **refactored modular architecture** with different file organization:

**V2 Structure:**
- `gradio_app.py` - Main application (refactored from v1's gradio_workflow.py)
- `core/` - Core functionality modules (comfyui_client, execution_engine, workflow_analyzer, result_retriever, ui_generator)
- `features/` - Optional feature modules
- `ui/` - UI component definitions
- `utils/` - Utility functions and helpers
- `static/` - Static assets
- `config.py` - Configuration management

**V2 Goals:**
- Reduce dependency on custom Hua output nodes
- Improve modularity and testability
- Cleaner separation of concerns

Much of the v1 documentation below (queue system, polling strategies, etc.) still applies conceptually but file locations and implementation details differ. See `PHASE1_COMPLETE.md` and `PHASE3_COMPLETE.md` for v2 development milestones.

---

## Project Overview (V1)

ComfyUI_to_webui is a **Gradio-based web UI wrapper for ComfyUI workflows**. It runs as a ComfyUI custom node plugin that exposes workflow inputs/outputs through a Gradio interface (port 7861), managing queuing, dynamic component generation, and live previews without modifying ComfyUI core.

## Critical Architecture Patterns

### Queue System (Thread-Safe Design)

The queue system uses **single-threaded processing** with careful state management:

```python
# Global state (gradio_workflow.py)
task_queue = deque()              # Pending tasks
queue_lock = Lock()               # Task queue mutex
processing_event = Event()        # True while worker active
executor = ThreadPoolExecutor(max_workers=1)  # Single worker
```

**Key Pattern:** First UI request becomes the worker; subsequent requests are "passive monitors" that add tasks but don't process. The `should_process_queue` flag prevents multiple workers and ensures generators complete through finally blocks.

**IMPORTANT:** Never use early `return` in generator functions after yielding - this triggers Gradio 4.44.0 deadlock bugs. Always use control flow flags and complete through finally blocks.

### Intelligent Queue Polling (Critical Fix)

Two different strategies based on workflow type (gradio_workflow.py:1820-1838):

1. **Workflows WITH Hua output nodes**: Poll history API (`/history/{client_id}`)
2. **Workflows WITHOUT Hua nodes**: Poll queue API (`/queue`) directly

```python
if image_result_ids or video_result_ids:
    # Has Hua nodes - use history API
    status_entry = _wait_for_prompt_completion(...)
else:
    # No Hua nodes - poll /queue endpoint
    # Wait until prompt_id disappears from queue_running/queue_pending
```

**Why:** ComfyUI history API doesn't reliably return status for standard workflows. Direct queue polling detects completion when prompt_id disappears.

**Queue Item Structure:** Items are lists `[number, prompt_id, {...}, class_type]`, NOT dictionaries.

### Dynamic Component Discovery

Workflow nodes are discovered by `class_type` matching (e.g., `GradioTextOk`, `Hua_LoraLoader`). The system:
- Loads workflow JSON on selection
- Scans for known node types
- Shows/hides UI controls via `gr.update(visible=True/False)`
- Limits: MAX_DYNAMIC_COMPONENTS=10, MAX_KSAMPLER_CONTROLS=4

### Hua Output Nodes (Custom Node Pattern)

`Hua_Output` and `Hua_Video_Output` nodes write results to temp JSON files:
- Saves images to ComfyUI output directory
- Writes paths to `{unique_id}.json` in temp directory
- Gradio reads these files to detect completion
- Files auto-cleaned after 1 hour

This **decouples** ComfyUI execution from Gradio result retrieval.

### Photopea Integration & Dimension Handling (CRITICAL)

**Problem:** Photopea exports and workflow conversions can create incorrect dimensions that cause VRAM overflow.

**Root Causes Fixed:**
1. **Batch Size Corruption**: During workflow-to-prompt conversion, `EmptyLatentImage.batch_size` was set to 1024 instead of 1, creating 1024 latent images and exhausting VRAM
2. **Linked Dimensions**: `EmptyLatentImage` dimensions were linked to `LoadAndResizeImage` outputs, which didn't respect resize parameters
3. **Conflicting Sources**: Dimensions from workflow JSON, UI inputs, and dynamic settings conflicted

**Solution Pattern (gradio_workflow.py:1823-1895):**

```python
# Dimension Priority: UI inputs > workflow settings > default (768x768)
target_width = None
target_height = None

# 1. Check UI inputs (if user changed from default 512x512)
if ui_width != 512 or ui_height != 512:
    target_width = ui_width
    target_height = ui_height

# 2. Fall back to loader_settings (from workflow/Photopea)
if target_width is None and loader_settings:
    target_width = loader_settings[0]['width']
    target_height = loader_settings[0]['height']

# 3. Final fallback to default
if target_width is None:
    target_width = 768
    target_height = 768

# CRITICAL: Override both nodes with same dimensions
for node in load_and_resize_keys:
    node['inputs']['width'] = target_width
    node['inputs']['height'] = target_height
    node['inputs']['resize'] = True
    node['inputs']['keep_proportion'] = False

for node in empty_latent_keys:
    node['inputs']['width'] = target_width
    node['inputs']['height'] = target_height
    node['inputs']['batch_size'] = 1  # FIX: Always 1, not 1024!
```

**Key Implementation Details:**
- Always set `batch_size = 1` on EmptyLatentImage (line 1890)
- Break node links by directly setting values instead of using link arrays
- Disable `keep_proportion` to ensure exact dimensions
- Apply same dimensions to both `LoadAndResizeImage` and `EmptyLatentImage`
- Dynamic config runs BEFORE this fix, so we override it

**Testing:**
- Export image from Photopea at various resolutions (1280x1024, 512x768, etc.)
- Verify no VRAM overflow errors
- Check generated image matches expected dimensions
- Test with UI dimension overrides
- Verify batch_size stays at 1

## Key Files

| File | Purpose |
|------|---------|
| `gradio_workflow.py` | Main entry point - Gradio UI, queue system, workflow execution |
| `__init__.py` | Plugin registration, dependency bootstrap, custom node mappings |
| `DEADLOCK_FIX.md` | **CRITICAL READING** - Documents queue deadlock fixes and polling strategy |
| `node/output_image_to_gradio.py` | Hua_Output node - writes results to temp JSON |
| `node/hua_nodes.py` | Input nodes (prompts, images, seeds, resolution) |
| `kelnel_ui/ui_def.py` | Workflow helpers, settings management, workflow-to-prompt conversion |
| `kelnel_ui/k_Preview.py` | WebSocket client for live ComfyUI previews |
| `kelnel_ui/system_monitor.py` | CPU/GPU/RAM monitoring dashboard |
| `kelnel_ui/photopea_bindings.js` | Photopea integration - bidirectional image transfer |
| `kelnel_ui/photopea_loader.js` | Photopea iframe loader and event handlers |
| `kelnel_ui/photopea_utils.js` | Photopea utility functions (base64 conversion, etc.) |

## Common Development Tasks

### Running the Plugin

The plugin auto-starts when ComfyUI loads. It:
1. Checks/installs dependencies from `requirements.txt`
2. Registers custom nodes in `NODE_CLASS_MAPPINGS`
3. Launches Gradio server (tries ports 7861-7870)
4. Starts WebSocket preview worker thread

Access UI at: `http://127.0.0.1:7861`

### Testing Queue System Changes

**CRITICAL:** When modifying `run_queued_tasks()` or `generate_image()`:
1. Test with workflows that have Hua_Output nodes
2. Test with standard ComfyUI workflows (no Hua nodes)
3. Test rapid multiple requests (queue stacking)
4. Test client disconnection during generation
5. Monitor logs for `AttributeError: 'NoneType' object has no attribute 'wait'`

### Adding New Custom Nodes

1. Create node class in `node/` directory
2. Define `INPUT_TYPES`, `RETURN_TYPES`, `FUNCTION`
3. Register in `__init__.py`:
   ```python
   NODE_CLASS_MAPPINGS["YourNode"] = YourNodeClass
   NODE_DISPLAY_NAME_MAPPINGS["YourNode"] = "🎨 Display Name"
   ```
4. If it's an input node, add discovery logic to `resolve_workflow_components()` in `gradio_workflow.py`

### Adding Dynamic UI Components

Pattern (in `create_gradio_interface()`):
```python
with gr.Accordion("Your Component", visible=False) as your_accordion:
    your_control = gr.Textbox(...)

# In resolve_workflow_components():
def resolve_workflow_components(json_dropdown_value):
    # Scan workflow for your node type
    has_your_node = any(node['class_type'] == 'YourNode' for node in workflow.values())

    return gr.update(visible=has_your_node)  # Show/hide accordion
```

## Data Flow

```
User Input (Gradio)
  → run_queued_tasks() [enqueues task]
  → generate_image() [loads workflow, updates nodes, POSTs to /api/prompt]
  → ComfyUI executes workflow
  → Hua_Output writes results to temp JSON
  → Intelligent polling detects completion
  → Read temp JSON / history API / filesystem diff
  → Update gallery (Gradio)
```

## Thread Safety Rules

- **Always** acquire locks before modifying shared state:
  ```python
  with queue_lock:
      task_queue.append(task)

  with results_lock:
      accumulated_image_results.append(image)
  ```
- **Never** hold locks across I/O operations (HTTP requests, file reads)
- Use `Event` objects for worker coordination (`processing_event`, `interrupt_requested_event`)

## WebSocket Preview System

`ComfyUIPreviewer` (kelnel_ui/k_Preview.py):
- Connects to `ws://127.0.0.1:8188/ws?clientId={client_id}`
- Spawns worker thread receiving execution messages
- Yields preview images to Gradio at 0.1s intervals
- Thread-safe with Lock and Event primitives

**Connection Lifecycle:**
```python
start() → spawn_worker_thread() → websocket_recv_loop()
  → parse messages → extract preview → yield to UI
stop() → set stop_event → close connection
```

## Result Retrieval Priority

1. **Hua Output Nodes**: Read temp JSON files (fastest, most reliable)
2. **History API**: Query `/history/{client_id}` for outputs
3. **Filesystem Diff**: Compare output directory before/after (fallback)

All three methods are attempted; first success is used.

## Settings & Configuration

- **User Settings**: `ComfyUI/user/default/plugin_settings.json`
  ```json
  {
    "max_dynamic_components": 10,
    "theme_mode": "system",
    "civitai_api_key": "..."
  }
  ```
- **Constants**: MAX_DYNAMIC_COMPONENTS, MAX_KSAMPLER_CONTROLS (in `gradio_workflow.py`)
- **Ports**: Gradio tries 7861-7870, uses first available

## Known Issues & Workarounds

### Gradio 4.44.0 Streaming Bug

**Symptom:** `AttributeError: 'NoneType' object has no attribute 'wait'` in routes.py

**Cause:** Early return after yield in generator functions confuses Gradio's cleanup code

**Workaround:** Use `should_process_queue` flag pattern; always complete through finally block with try-except around yields

### History API Unreliability

**Symptom:** Workflows without Hua nodes hang for 420 seconds

**Cause:** History API doesn't reliably return completion status

**Workaround:** Intelligent polling - use queue API for workflows without Hua nodes

### Temp File Cleanup

**Current:** Age-based deletion (files older than 1 hour)

**Limitation:** Not smart about active executions; may delete files still being read

**Future:** Reference-counted cleanup or explicit deletion after retrieval

## Dependencies

```
gradio >= 3.0           # UI framework (4.44.0 has streaming bug, mitigated)
Pillow                  # Image processing
websocket-client        # Live preview WebSocket
requests                # HTTP API calls
psutil, pynvml          # System/GPU monitoring
imageio[ffmpeg]         # Video processing
```

Install: `pip install -r requirements.txt` (auto-attempted on plugin load)

## Code Style Patterns

- **Logging**: Use `log_message(f"[TAG] message")` with millisecond timestamps
- **Errors**: Try-except around I/O, log failures, continue gracefully
- **Updates**: `gr.update(value=..., visible=...)` for component changes
- **Streaming**: Yield tuples matching output component order
- **Locks**: Context managers (`with lock:`) for all shared state access

## Testing Checklist for Queue Changes

- [ ] Workflows with Hua_Output nodes complete successfully
- [ ] Standard ComfyUI workflows (no Hua nodes) complete successfully
- [ ] Multiple rapid requests queue properly without deadlock
- [ ] Client disconnection during generation doesn't crash worker
- [ ] Gallery updates immediately after generation
- [ ] No `AttributeError` in logs
- [ ] Queue status shows correct counts (pending/processing)
- [ ] Interrupt button stops current generation

## Important Technical Context

**READ BEFORE MAKING CHANGES:**
1. `DEADLOCK_FIX.md` - Documents critical queue system fixes
2. `README.md` - User-facing feature descriptions
3. Lines 2083-2301 in `gradio_workflow.py` - Queue worker implementation
4. Lines 1823-1895 in `gradio_workflow.py` - Photopea dimension handling and batch_size fix
5. Lines 1820-1838 in `gradio_workflow.py` - Intelligent polling logic (OUTDATED LINE NUMBERS - search for "Intelligent queue polling")
6. `node/output_image_to_gradio.py` - Hua output node pattern
7. `kelnel_ui/ui_def.py:283-414` - Workflow-to-prompt conversion (source of batch_size bug)

## Image Container Constraints (Forge-Inspired)

**Problem:** Gradio 4.44.0 ImageEditor components can overflow their containers, pushing editing tools and uploaded images outside their designated frames.

**Solution Pattern (kelnel_ui/css_html_js.py:36-120):**
1. **Fixed Height Enforcement**: Set explicit `height: 512px` on `#hua-image-input` with `!important` flags
2. **Nested Container Control**: Apply max-height to all child elements (`> *`, `.image-container`, etc.)
3. **Image Scaling**: Use `object-fit: scale-down` (Forge pattern) instead of `contain` with `max-height: 480px` to leave room for tools
4. **Tool Bar Constraints**: Limit toolbars to `max-height: 40px` with `flex-shrink: 0`
5. **Canvas Size Parameter**: Set `canvas_size: (512, 480)` in ImageEditor kwargs (gradio_workflow.py:2582)
6. **Dynamic JavaScript Enforcement**: MutationObserver watches for Gradio DOM changes and re-applies constraints (get_image_constraint_js())

**Key CSS Properties:**
- `overflow: hidden` on containers prevents spillage
- `box-sizing: border-box` ensures padding/borders included in height calculations
- `display: block; margin: auto` centers images within bounded space
- `position: relative` on tools prevents absolute positioning escape

**Testing:**
- Upload large images (>1024px) - should scale down to fit
- Test editing tools - should stay within 512px container
- Verify mask controls don't slide under right pane (z-index: 100 on left pane)

## Extension Points

**New Input Types:** Add node class + UI component + discovery logic
**New Output Types:** Extend Hua output node pattern + result retrieval
**New Model Types:** Add folder scan + dropdown + prompt update logic
**New Monitoring:** Add stream generator + Gradio component + demo.load event
