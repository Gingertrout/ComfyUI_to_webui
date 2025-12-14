"""
Civitai Model Browser Feature

Allows searching and downloading models from Civitai.com
"""

import os
import requests
import gradio as gr
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

# Try to import folder_paths from ComfyUI
try:
    import folder_paths
    COMFYUI_MODELS_DIR = Path(folder_paths.models_dir)
except ImportError:
    # Fallback if not running in ComfyUI context
    COMFYUI_MODELS_DIR = Path(__file__).parent.parent.parent.parent / "models"

from ..utils.settings import get_setting, set_setting

# Civitai API Configuration
CIVITAI_BASE_URL = "https://civitai.com/api/v1"
CIVITAI_SORT_MAP = {
    "Highest Rated": "Highest Rated",
    "Most Downloaded": "Most Downloaded",
    "Newest": "Newest",
}
CIVITAI_NSFW_MAP = {
    "Hide": "false",
    "Show": "true",
    "Only": "only",
}

# Model type to directory mapping
MODEL_TYPE_DIRS = {
    "Checkpoint": "checkpoints",
    "LORA": "loras",
    "LoCon": "loras",
    "TextualInversion": "embeddings",
    "VAE": "vae",
    "Controlnet": "controlnet",
}


class CivitaiBrowser:
    """Civitai model browser and downloader"""

    def __init__(self):
        self.results_cache: List[Dict] = []
        self.selected_model: Optional[Dict] = None
        self.selected_file: Optional[Dict] = None

    def get_api_key(self, override_key: Optional[str] = None) -> str:
        """Get Civitai API key from override or settings"""
        if override_key and override_key.strip():
            return override_key.strip()
        return get_setting("civitai_api_key", "")

    def save_api_key(self, api_key: str) -> Tuple[str, bool]:
        """
        Save Civitai API key to settings

        Returns:
            Tuple of (status_message, visible)
        """
        status = set_setting("civitai_api_key", api_key.strip())
        message = "🔐 Civitai API key saved." if api_key.strip() else "🔓 Cleared stored Civitai API key."
        return f"{message} ({status})", True

    def search_models(
        self,
        query: str,
        model_type: str,
        sort_label: str,
        page: int,
        per_page: int,
        nsfw_setting: str,
        api_key_override: Optional[str] = None
    ) -> Tuple[str, List, List[str]]:
        """
        Search Civitai models

        Returns:
            Tuple of (status_message, results_cache, choices_for_dropdown)
        """
        api_key = self.get_api_key(api_key_override)

        try:
            page = max(1, int(page or 1))
            per_page = max(1, min(int(per_page or 20), 50))
        except (TypeError, ValueError):
            page = 1
            per_page = 20

        params = {"page": page, "perPage": per_page}
        if query:
            params["query"] = query.strip()
        if model_type:
            params["types"] = model_type.strip()

        sort_value = CIVITAI_SORT_MAP.get(sort_label, "")
        if sort_value:
            params["sort"] = sort_value

        nsfw_value = CIVITAI_NSFW_MAP.get(nsfw_setting, "false")
        if nsfw_value:
            params["nsfw"] = nsfw_value

        try:
            headers = {"User-Agent": "ComfyUI-to-WebUI Civitai Client"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            response = requests.get(
                f"{CIVITAI_BASE_URL}/models",
                params=params,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            items = data.get("items", [])
            self.results_cache = items

            if not items:
                return "ℹ️ No results found.", [], []

            # Create dropdown choices
            choices = []
            for idx, model in enumerate(items):
                name = model.get("name", "Unnamed")
                model_type = model.get("type", "Unknown")
                stats = model.get("stats", {})
                downloads = stats.get("downloadCount", 0)
                choices.append(f"[{idx}] {name} ({model_type}) - {downloads:,} downloads")

            message = f"✅ Found {len(items)} results (page {page})"
            return message, items, choices

        except requests.RequestException as e:
            return f"❌ Search failed: {e}", [], []

    def select_model(self, selected_label: Optional[str]) -> Tuple[str, List, List[str], List[str], str]:
        """
        Handle model selection from dropdown

        Returns:
            Tuple of (model_details, preview_gallery, version_choices, file_choices, target_dir)
        """
        if not selected_label or not self.results_cache:
            return "", [], [], [], ""

        try:
            # Extract index from label like "[0] Model Name"
            idx = int(selected_label.split("]")[0].split("[")[1])
            model = self.results_cache[idx]
            self.selected_model = model
        except (IndexError, ValueError, KeyError):
            return "❌ Invalid selection", [], [], [], ""

        # Format model details
        details = self._format_model_details(model)

        # Parse preview images
        preview_gallery = []
        model_versions = model.get("modelVersions", [])
        if model_versions:
            images = model_versions[0].get("images", [])
            for img in images[:10]:
                if isinstance(img, dict):
                    url = img.get("url") or img.get("originalUrl")
                    if url:
                        preview_gallery.append(url)

        # Create version dropdown choices
        version_choices = []
        for idx, ver in enumerate(model_versions):
            ver_name = ver.get("name", f"Version {idx}")
            created_at = ver.get("createdAt", "")[:10]
            version_choices.append(f"[{idx}] {ver_name} ({created_at})")

        # Auto-select first version and get files
        file_choices = []
        target_dir = ""
        if model_versions:
            files = model_versions[0].get("files", [])
            for idx, file_info in enumerate(files):
                filename = file_info.get("name", "Unknown")
                size_kb = file_info.get("sizeKB", 0)
                size_mb = size_kb / 1024
                file_choices.append(f"[{idx}] {filename} ({size_mb:.1f} MB)")

            # Suggest target directory
            model_type = model.get("type")
            target_dir = self._suggest_target_directory(model_type)

        return details, preview_gallery, version_choices, file_choices, target_dir

    def select_version(self, version_label: Optional[str]) -> Tuple[List[str], str]:
        """
        Handle version selection

        Returns:
            Tuple of (file_choices, target_dir)
        """
        if not version_label or not self.selected_model:
            return [], ""

        try:
            idx = int(version_label.split("]")[0].split("[")[1])
            model_versions = self.selected_model.get("modelVersions", [])
            version = model_versions[idx]
        except (IndexError, ValueError, KeyError):
            return [], ""

        files = version.get("files", [])
        file_choices = []
        for idx, file_info in enumerate(files):
            filename = file_info.get("name", "Unknown")
            size_kb = file_info.get("sizeKB", 0)
            size_mb = size_kb / 1024
            file_choices.append(f"[{idx}] {filename} ({size_mb:.1f} MB)")

        model_type = self.selected_model.get("type")
        target_dir = self._suggest_target_directory(model_type)

        return file_choices, target_dir

    def download_file(
        self,
        version_label: Optional[str],
        file_label: Optional[str],
        target_dir: str,
        api_key_override: Optional[str] = None
    ) -> str:
        """
        Download selected file

        Returns:
            Status message
        """
        if not self.selected_model or not version_label or not file_label:
            return "❌ Please select a model, version, and file first"

        if not target_dir or not target_dir.strip():
            return "❌ Please specify a target directory"

        try:
            # Parse version index
            ver_idx = int(version_label.split("]")[0].split("[")[1])
            model_versions = self.selected_model.get("modelVersions", [])
            version = model_versions[ver_idx]

            # Parse file index
            file_idx = int(file_label.split("]")[0].split("[")[1])
            files = version.get("files", [])
            file_info = files[file_idx]

            # Get download URL
            download_url = file_info.get("downloadUrl")
            if not download_url:
                return "❌ No download URL found for this file"

            filename = file_info.get("name", "download.safetensors")

            # Create target directory
            target_path = Path(target_dir)
            target_path.mkdir(parents=True, exist_ok=True)

            output_file = target_path / filename

            # Download with progress
            api_key = self.get_api_key(api_key_override)
            headers = {"User-Agent": "ComfyUI-to-WebUI Civitai Client"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            print(f"📥 Downloading {filename} to {output_file}...")

            response = requests.get(download_url, headers=headers, stream=True, timeout=60)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            with open(output_file, 'wb') as f:
                downloaded = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            print(f"  Progress: {percent:.1f}%", end='\r')

            print(f"\n✅ Downloaded {filename} successfully!")
            return f"✅ Downloaded {filename} to {output_file}"

        except Exception as e:
            return f"❌ Download failed: {e}"

    def _format_model_details(self, model: Dict) -> str:
        """Format model details as markdown"""
        if not model:
            return ""

        stats = model.get("stats", {})
        downloads = stats.get("downloadCount", 0)
        rating = stats.get("rating")
        tags = model.get("tags", [])

        lines = [f"**{model.get('name', 'Unnamed model')}**"]
        lines.append("")

        if model.get("type"):
            lines.append(f"**Type:** {model['type']}")
        if downloads:
            lines.append(f"**Downloads:** {downloads:,}")
        if rating:
            try:
                lines.append(f"**Rating:** {float(rating):.2f}")
            except (TypeError, ValueError):
                lines.append(f"**Rating:** {rating}")
        if tags:
            lines.append(f"**Tags:** {', '.join(tags[:10])}")

        description = model.get("description", "")
        if description:
            snippet = description[:600]
            if len(description) > 600:
                snippet += "…"
            lines.append("")
            lines.append(snippet)

        return "\n".join(lines)

    def _suggest_target_directory(self, model_type: Optional[str]) -> str:
        """Suggest target directory based on model type"""
        if not model_type:
            return str(COMFYUI_MODELS_DIR / "misc")

        subdir = MODEL_TYPE_DIRS.get(model_type, model_type.lower().replace(" ", "_"))
        return str(COMFYUI_MODELS_DIR / subdir)


# Global instance
_browser = CivitaiBrowser()


# Public functions for Gradio callbacks
def save_api_key(api_key: str):
    """Save Civitai API key"""
    message, visible = _browser.save_api_key(api_key)
    return gr.update(value=message, visible=visible)


def search_models(query, model_type, sort_label, page, per_page, nsfw_setting, api_key_override):
    """Search Civitai models"""
    status, results, choices = _browser.search_models(
        query, model_type, sort_label, page, per_page, nsfw_setting, api_key_override
    )
    return (
        gr.update(value=status, visible=True),  # search_status
        results,  # results_state
        gr.update(choices=choices, value=None),  # results_dropdown
    )


def select_model(selected_label, results_state):
    """Handle model selection"""
    details, gallery, version_choices, file_choices, target_dir = _browser.select_model(selected_label)
    return (
        gr.update(value=details, visible=bool(details)),  # model_details
        gallery,  # preview_gallery
        gr.update(choices=version_choices, value=version_choices[0] if version_choices else None, visible=True),  # version_dropdown
        gr.update(choices=file_choices, value=file_choices[0] if file_choices else None, visible=True),  # file_dropdown
        target_dir,  # target_dir
    )


def select_version(version_label, selected_model_state):
    """Handle version selection"""
    file_choices, target_dir = _browser.select_version(version_label)
    return (
        gr.update(choices=file_choices, value=file_choices[0] if file_choices else None),  # file_dropdown
        target_dir,  # target_dir
    )


def download_file(version_label, file_label, target_dir, api_key_override):
    """Download selected file"""
    return _browser.download_file(version_label, file_label, target_dir, api_key_override)
