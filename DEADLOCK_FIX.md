# Gradio Queue Deadlock and Hanging Fix

## Problem Summary

The Gradio interface was experiencing two critical issues:

1. **ASGI Application Errors** with this stack trace:

```
AttributeError: 'NoneType' object has no attribute 'wait'
  File "gradio/routes.py", line 709, in stop_stream
    await app.stop_event.wait()
```

## Root Causes

1. **Gradio 4.44.0 Internal Bug**: When streaming responses are cancelled (e.g., client disconnect), Gradio's cleanup code tries to access `app.stop_event` where `app` is None.

2. **Generator Early Return** (gradio_workflow.py:2086): The `run_queued_tasks` function had an early `return` statement after already yielding once:
   ```python
   if processing_event.is_set():
       log_message("[QUEUE] Worker already active...")
       return  # ← PROBLEM: returns after yielding!
   ```

   This created an incomplete generator that confused Gradio's streaming handler.

3. **Race Condition**: When multiple requests arrived or clients disconnected, the early return triggered the Gradio bug, causing ASGI errors and blocking the queue.

## The Fix

### Changed Lines: 2083-2103

**Before:**
```python
if processing_event.is_set():
    log_message("[QUEUE] Worker already active...")
    return  # Early return after yield = bad!

processing_event.set()
log_message("[QUEUE] Worker started.")

try:
    while True:
```

**After:**
```python
should_process_queue = not processing_event.is_set()

if not should_process_queue:
    log_message("[QUEUE] Worker already active...")
else:
    processing_event.set()
    log_message("[QUEUE] Worker started.")

try:
    while should_process_queue:  # Only loop if we're the worker
```

### Changed Lines: 2247-2269

**Before:**
```python
finally:
    processing_event.clear()
    # ... yield final status
```

**After:**
```python
finally:
    if should_process_queue:
        processing_event.clear()
        log_message("[QUEUE] Worker finished...")
    else:
        log_message("[QUEUE] Passive monitor finished...")

    # ... yield final status with error handling
    try:
        yield dict_to_tuple({...})
    except Exception as e:
        log_message(f"[ERROR] Finally yield failed: {e}")
```

## Why This Works

1. **No Early Returns**: The generator now always completes through the finally block, preventing Gradio confusion.

2. **Proper Worker Management**:
   - If a worker is already active, the new generator becomes a "passive monitor" that just yields the final status
   - Only the actual worker clears `processing_event`

3. **Graceful Error Handling**: The try-except around the finally yield catches Gradio errors without crashing.

## Testing

After applying this fix, the queue should:
- Accept multiple rapid requests without deadlocking
- Handle client disconnections gracefully
- Continue processing queued tasks even if a client disconnects
- No longer show `AttributeError: 'NoneType' object has no attribute 'wait'` errors

## Issue 2: Generate Tasks Hanging Forever

### Problem
When using workflows without Hua_Output nodes, the `generate_image` function would hang forever at `_wait_for_prompt_completion`, never returning results to the gallery.

### Root Cause
The code was waiting for ComfyUI's `/history/{client_id}` API to return a status field with "completed", but:
1. The history API doesn't reliably return status in this format
2. The original upstream repo doesn't use history API at all - it relies on custom output nodes writing temp files
3. Workflows without Hua output nodes would wait 420 seconds (7 minutes) then timeout

### The Fix: Intelligent Queue Polling (gradio_workflow.py:1820-1838)

**Added smart detection:**
```python
if image_result_ids or video_result_ids:
    # Has Hua nodes - use history API
    status_entry = _wait_for_prompt_completion(...)
else:
    # No Hua nodes - poll queue status directly
    while time.time() < deadline:
        resp = requests.get("http://127.0.0.1:8188/queue")
        queue_data = resp.json()
        # Queue items are lists: [number, prompt_id, {...}, class_type]
        in_running = any(item[1] == prompt_id for item in queue_data.get('queue_running', []))
        in_pending = any(item[1] == prompt_id for item in queue_data.get('queue_pending', []))
        if not in_running and not in_pending:
            break  # Done!
        time.sleep(0.5)
```

**Why This Works:**
- Workflows WITH Hua nodes: Still use history API (as those nodes write custom status)
- Workflows WITHOUT Hua nodes: Poll the `/queue` endpoint directly
- When prompt disappears from queue, it's finished - proceed to filesystem diff
- Much faster and more reliable than waiting for history status

### Additional Fix: Better History Detection (gradio_workflow.py:1172-1177)

Added fallback check for completed prompts without explicit status:
```python
if "outputs" in prompt_entry or "images" in prompt_entry:
    print(f"Prompt entry found with outputs but no explicit status - assuming complete.")
    return prompt_entry
```

## Complete Solution Summary

1. **Queue Worker Fix**: Eliminated early returns that confused Gradio's streaming
2. **History API Fix**: Skip broken history wait when no Hua nodes present
3. **Queue Polling**: Use reliable `/queue` endpoint to detect completion
4. **Fallback Detection**: Check for outputs field when status is missing
5. **Error Handling**: Graceful handling of client disconnections

## Testing

After applying this fix, the system should:
- Accept multiple rapid requests without deadlocking
- Handle client disconnections gracefully ✓
- Continue processing queued tasks even if a client disconnects ✓
- Display results in the gallery immediately after generation ✓
- Work with both Hua-enabled and standard ComfyUI workflows ✓

## Additional Notes

- The underlying Gradio 4.44.0 bug still exists, but we're avoiding the code path that triggers it
- If you still see issues, consider pinning to a different Gradio version or reporting upstream
- Monitor logs for "[ERROR] Finally yield failed" messages to detect client disconnection issues
- Workflows without Hua_Output nodes now use filesystem diff exclusively (like the original repo)
