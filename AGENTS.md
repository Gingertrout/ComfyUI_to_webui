# Repository Guidelines

## Project Structure & Module Organization
The plugin entry point is `ComfyUI_to_webui/gradio_workflow.py`, which builds the Gradio interface when imported by ComfyUI. Helper nodes live under `node/` (e.g., `deepseek_api.py` and the media exporters) while UI scaffolding resides in `kelnel_ui/` with assets under `js/`, `fonts/`, and `locales/`. Sample configurations in `Sample_preview/` double as smoke-test graphs. Keep `plugin_settings.json` for local experiments only; never commit secrets.

## Build, Test, and Development Commands
Use the same Python interpreter that runs ComfyUI. From the ComfyUI root run `python -m pip install -r custom_nodes/ComfyUI_to_webui/requirements.txt` to sync runtime dependencies. During iterative work execute `python -m ComfyUI_to_webui.gradio_workflow` from the ComfyUI root to launch the Gradio panel on port 7861 for quick checks; stop with Ctrl+C. When embedded in ComfyUI, restart the host server after copying workflow or node changes.

## Coding Style & Naming Conventions
Python files follow four-space indentation, snake_case functions, and CamelCase classes. Mirror existing lightweight `print` diagnostics during load and explain non-obvious threading with brief comments. Localized strings belong in `locales/`; exportable assets go through `kelnel_ui/css_html_js.py`. JavaScript utilities in `js/` should stay ES module compatible and keep icon exports named `*_ICON`.

## Testing Guidelines
There is no automated suite yet; rely on workflow-driven checks. Use the graphs in `Sample_preview/` to exercise queue churn, video export, and API tooling, and verify that new nodes appear under the Gradio controls. Before opening a PR confirm that ComfyUI logs auto-detect the plugin, image previews refresh, and any new settings survive a restart by persisting through `plugin_settings.json`.

## Commit & Pull Request Guidelines
Recent commits favor concise, single-line summaries (often imperative, occasionally bilingual). Reference the touched module (for example `deepseek_api` or `kelnel_ui`) to ease triage. For pull requests include a short problem statement, testing notes, screenshots or GIFs for UI work, and links to relevant issues or workflows. Call out migration steps (such as new requirements or renamed settings) in bold within the description so release notes remain accurate.

## Configuration Notes
API keys for Civitai and other services should be loaded at runtime, never hard-coded or committed. If you alter default ports or queue limits, update the explanation near the top of `gradio_workflow.py` and document fallback behavior in the PR so operators know what to expect.
