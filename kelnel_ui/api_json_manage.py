import gradio as gr
import os
import json
import glob
import folder_paths
from datetime import datetime

# Directory where API JSON files are stored
API_JSON_DIR = folder_paths.get_output_directory()
MAX_API_JSON_CHOICES = 500

def get_api_json_files():
    """Get API JSON file list with last modified time."""
    detailed_entries = []
    try:
        if not os.path.exists(API_JSON_DIR):
            print(f"Warning: API JSON directory {API_JSON_DIR} not found.")
            return detailed_entries

        json_pattern = os.path.join(API_JSON_DIR, "**", "*.json")
        for abs_path in glob.glob(json_pattern, recursive=True):
            if not os.path.isfile(abs_path):
                continue
            rel_path = os.path.relpath(abs_path, API_JSON_DIR)
            try:
                mtime = os.path.getmtime(abs_path)
                last_modified_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
            except (OSError, ValueError):
                mtime = 0.0
                last_modified_str = "N/A"
            try:
                size_kb = os.path.getsize(abs_path) / 1024
            except OSError:
                size_kb = 0.0
            detailed_entries.append((rel_path, last_modified_str, f"{size_kb:.2f} KB", mtime))

        if not detailed_entries:
            return []

        detailed_entries.sort(key=lambda item: (-item[3], item[0]))
        if len(detailed_entries) > MAX_API_JSON_CHOICES:
            print(f"Info: Limiting API JSON manager list to the {MAX_API_JSON_CHOICES} most recent files out of {len(detailed_entries)} discovered.")
        trimmed = detailed_entries[:MAX_API_JSON_CHOICES]
        return [(path, modified, size) for path, modified, size, _ in trimmed]
    except Exception as e:
        print(f"Error listing API JSON files: {e}")
        return []

def view_json_content(file_name):
    """Read and return the content of the specified JSON file."""
    if not file_name:
        return "Please select a file first."
    file_path = os.path.join(API_JSON_DIR, file_name)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = json.load(f)
        return json.dumps(content, indent=2, ensure_ascii=False)
    except FileNotFoundError:
        return f"Error: file {file_name} not found."
    except json.JSONDecodeError:
        return f"Error: file {file_name} is not valid JSON."
    except Exception as e:
        return f"Error reading file {file_name}: {e}"

def delete_json_file(file_name_to_delete, selected_file_in_list):
    """Delete the specified JSON file."""
    if not file_name_to_delete:
        gr.Warning("No file selected to delete.")
        return get_api_json_files(), "Please select a file to delete.", selected_file_in_list

    file_path = os.path.join(API_JSON_DIR, file_name_to_delete)
    try:
        os.remove(file_path)
        gr.Info(f"File {file_name_to_delete} deleted successfully.")
        # When the currently viewed file is deleted, clear the preview pane.
        new_content_display = "" if file_name_to_delete == selected_file_in_list else view_json_content(selected_file_in_list)
        # Refresh the file list and keep the previous selection whenever possible.
        new_file_list = get_api_json_files()
        new_selected_file = None
        if selected_file_in_list and selected_file_in_list != file_name_to_delete:
             # Ensure the previously selected file still exists in the updated list.
            if any(f[0] == selected_file_in_list for f in new_file_list):
                new_selected_file = selected_file_in_list

        return new_file_list, new_content_display, new_selected_file

    except FileNotFoundError:
        gr.Error(f"Delete failed: file {file_name_to_delete} not found.")
    except Exception as e:
        gr.Error(f"Error deleting file {file_name_to_delete}: {e}")
    # Return the existing state when deletion fails.
    return get_api_json_files(), view_json_content(selected_file_in_list), selected_file_in_list


def define_api_json_management_ui():
    """Define the Gradio UI for managing API JSON workflows.
    This function should be called within a gr.Blocks() or gr.Tab() context.
    """
    gr.Markdown("## API JSON Workflow Manager")
    gr.Markdown(f"Workflow JSON files are stored in: `{API_JSON_DIR}`")

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### File List")
            selected_json_file_radio = gr.Radio(
                label="Select workflow file",
                choices=[f[0] for f in get_api_json_files()],
                value=None
            )
            refresh_files_button = gr.Button("🔄 Refresh file list")
            gr.Markdown("---")
            gr.Markdown("### File Operations")
            delete_button = gr.Button("🗑️ Delete selected file", variant="stop")

            file_details_display = gr.Markdown("Select a file to view its details and contents.")
            save_changes_button = gr.Button("💾 Save changes to selected file")

        with gr.Column(scale=2):
            gr.Markdown("### File Content Preview/Edit")
            json_content_display = gr.Code(label="JSON Content", language="json", lines=20, interactive=True) # Editable


    def save_json_content(file_name, json_string):
        if not file_name:
            gr.Warning("No file selected; cannot save.")
            return "No file selected; cannot save."
        
        file_path = os.path.join(API_JSON_DIR, file_name)
        try:
            # Parse to ensure the JSON is valid before writing to disk.
            parsed_json = json.loads(json_string)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(parsed_json, f, indent=2, ensure_ascii=False)
            gr.Info(f"File {file_name} saved successfully!")
            return json.dumps(parsed_json, indent=2, ensure_ascii=False)  # return the formatted string so the editor stays in sync
        except json.JSONDecodeError:
            gr.Error(f"Save failed: content is not valid JSON. Please check the syntax.")
            return json_string  # keep the raw string so the user can fix it
        except FileNotFoundError:  # should not happen because the name comes from the selection list
            gr.Error(f"Save failed: file {file_name} not found.")
            return json_string
        except Exception as e:
            gr.Error(f"Unknown error saving file {file_name}: {e}")
            return json_string

    def on_file_select_or_refresh(selected_file_name):
        if not selected_file_name:
            return "Please select a file.", "Select a file to view its details and contents."
        content = view_json_content(selected_file_name)
        all_files = get_api_json_files()
        details_str = "File details not found."
        for f_name, f_modified, f_size in all_files:
            if f_name == selected_file_name:
                details_str = f"**Filename:** {f_name}\n\n**Last Modified:** {f_modified}\n\n**Size:** {f_size}"
                break
        return content, details_str

    selected_json_file_radio.change(
        fn=on_file_select_or_refresh,
        inputs=[selected_json_file_radio],
        outputs=[json_content_display, file_details_display]
    )

    def refresh_list_and_selection(current_selection):
        new_choices_tuples = get_api_json_files()
        new_choices_names = [f[0] for f in new_choices_tuples]
        new_selection_value = None
        if current_selection and current_selection in new_choices_names:
            new_selection_value = current_selection
        elif new_choices_names:
            new_selection_value = new_choices_names[0]
        
        new_content, new_details = "", "Select a file to view its details and contents."
        if new_selection_value:
            new_content, new_details = on_file_select_or_refresh(new_selection_value)
        return gr.update(choices=new_choices_names, value=new_selection_value), new_content, new_details

    refresh_files_button.click(
        fn=refresh_list_and_selection,
        inputs=[selected_json_file_radio],
        outputs=[selected_json_file_radio, json_content_display, file_details_display]
    )

    def handle_delete_and_refresh(file_to_delete, current_selected_in_list):
        # Bridge the delete helper to radio button updates.
        # delete_json_file returns (files_with_details, content_string, selected_file_name).
        # Convert that structure into the updates our Gradio controls expect.
        files_after_delete_tuples, new_content_str, new_selected_name = delete_json_file(file_to_delete, current_selected_in_list)
        
        new_radio_choices = [f[0] for f in files_after_delete_tuples]
        
        # Refresh the metadata pane.
        new_details_str = "Select a file to view its details and contents."
        if new_selected_name:
            for f_name, f_modified, f_size in files_after_delete_tuples:
                if f_name == new_selected_name:
                    new_details_str = f"**Filename:** {f_name}\n\n**Last Modified:** {f_modified}\n\n**Size:** {f_size}"
                    break
        elif not new_selected_name and new_content_str == "Please select a file first.":  # fall back to the default prompt
             pass

        return gr.update(choices=new_radio_choices, value=new_selected_name), new_content_str, new_details_str

    delete_button.click(
        fn=handle_delete_and_refresh,
        inputs=[selected_json_file_radio, selected_json_file_radio],
        outputs=[selected_json_file_radio, json_content_display, file_details_display]
    )
    # No chained .then() is required; handle_delete_and_refresh already returns the updates we need.

    save_changes_button.click(
        fn=save_json_content,
        inputs=[selected_json_file_radio, json_content_display],  # filename and edited content
        outputs=[json_content_display]  # replace the editor contents (e.g., with formatted JSON)
    )


# When executed directly, spin up an isolated Gradio app for manual testing.
if __name__ == "__main__":
    # Mock folder_paths for standalone testing if not in ComfyUI env
    class MockFolderPaths:
        def get_output_directory(self):
            # Create a dummy directory for testing
            test_dir = os.path.join(os.path.dirname(__file__), "test_api_json_output")
            os.makedirs(test_dir, exist_ok=True)
            # Add some dummy json files
            with open(os.path.join(test_dir, "test1.json"), "w") as f:
                json.dump({"name": "test1", "value": 123}, f)
            with open(os.path.join(test_dir, "test2.json"), "w") as f:
                json.dump({"name": "test2", "value": 456}, f)
            return test_dir

    if not hasattr(folder_paths, 'get_output_directory'):
        folder_paths = MockFolderPaths()
        API_JSON_DIR = folder_paths.get_output_directory()  # Reassign for local testing

    with gr.Blocks() as demo_test:  # Build a top-level Blocks app for manual testing
        define_api_json_management_ui()  # Invoke the UI builder
    demo_test.launch()
