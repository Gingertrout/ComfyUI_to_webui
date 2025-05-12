import gradio as gr
import os
import json
import folder_paths
from datetime import datetime

# 获取 API JSON 文件所在的目录
API_JSON_DIR = folder_paths.get_output_directory()

def get_api_json_files():
    """获取 API JSON 文件列表及其最后修改时间"""
    files_with_details = []
    try:
        if not os.path.exists(API_JSON_DIR):
            print(f"警告: API JSON 目录 {API_JSON_DIR} 未找到。")
            return files_with_details

        json_files = [f for f in os.listdir(API_JSON_DIR) if f.endswith('.json') and os.path.isfile(os.path.join(API_JSON_DIR, f))]
        for file_name in json_files:
            file_path = os.path.join(API_JSON_DIR, file_name)
            try:
                # 获取文件最后修改时间
                mtime = os.path.getmtime(file_path)
                last_modified_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                # 获取文件大小
                size = os.path.getsize(file_path)
                files_with_details.append((file_name, last_modified_str, f"{size / 1024:.2f} KB"))
            except Exception as e:
                print(f"获取文件 {file_name} 详细信息时出错: {e}")
                files_with_details.append((file_name, "N/A", "N/A"))
        # 按文件名排序
        files_with_details.sort(key=lambda x: x[0])
        return files_with_details
    except Exception as e:
        print(f"获取 API JSON 文件列表时出错: {e}")
        return []

def view_json_content(file_name):
    """读取并返回指定 JSON 文件的内容"""
    if not file_name:
        return "请先选择一个文件。"
    file_path = os.path.join(API_JSON_DIR, file_name)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = json.load(f)
        return json.dumps(content, indent=2, ensure_ascii=False)
    except FileNotFoundError:
        return f"错误: 文件 {file_name} 未找到。"
    except json.JSONDecodeError:
        return f"错误: 文件 {file_name} 不是有效的 JSON 格式。"
    except Exception as e:
        return f"读取文件 {file_name} 时发生错误: {e}"

def delete_json_file(file_name_to_delete, selected_file_in_list):
    """删除指定的 JSON 文件"""
    if not file_name_to_delete:
        gr.Warning("没有选择要删除的文件。")
        return get_api_json_files(), "请先选择一个文件进行删除。", selected_file_in_list

    file_path = os.path.join(API_JSON_DIR, file_name_to_delete)
    try:
        os.remove(file_path)
        gr.Info(f"文件 {file_name_to_delete} 已成功删除。")
        # 如果删除的是当前查看的文件，清空内容显示
        new_content_display = "" if file_name_to_delete == selected_file_in_list else view_json_content(selected_file_in_list)
        # 更新文件列表，并尝试保持或清除选择
        new_file_list = get_api_json_files()
        new_selected_file = None
        if selected_file_in_list and selected_file_in_list != file_name_to_delete:
             # 检查原选中的文件是否还在新列表中
            if any(f[0] == selected_file_in_list for f in new_file_list):
                new_selected_file = selected_file_in_list

        return new_file_list, new_content_display, new_selected_file

    except FileNotFoundError:
        gr.Error(f"删除失败: 文件 {file_name_to_delete} 未找到。")
    except Exception as e:
        gr.Error(f"删除文件 {file_name_to_delete} 时发生错误: {e}")
    # 如果删除失败，返回当前状态
    return get_api_json_files(), view_json_content(selected_file_in_list), selected_file_in_list


def define_api_json_management_ui():
    """定义 API JSON 管理界面的 Gradio 组件。
    这个函数应该在一个 gr.Blocks() 上下文或者一个 gr.Tab() 上下文内部被调用。
    """
    gr.Markdown("## API JSON 工作流管理")
    gr.Markdown(f"工作流 JSON 文件存储在目录: `{API_JSON_DIR}`")

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 文件列表")
            selected_json_file_radio = gr.Radio(
                label="选择工作流文件",
                choices=[f[0] for f in get_api_json_files()],
                value=None
            )
            refresh_files_button = gr.Button("🔄 刷新文件列表")
            gr.Markdown("---")
            gr.Markdown("### 文件操作")
            delete_button = gr.Button("🗑️ 删除选定文件", variant="stop")

            file_details_display = gr.Markdown("选择一个文件以查看其详细信息和内容。")
            save_changes_button = gr.Button("💾 保存更改到选定文件")

        with gr.Column(scale=2):
            gr.Markdown("### 文件内容预览/编辑")
            json_content_display = gr.Code(label="JSON 内容", language="json", lines=20, interactive=True) # 允许编辑


    def save_json_content(file_name, json_string):
        if not file_name:
            gr.Warning("没有选择文件，无法保存。")
            return "没有选择文件，无法保存。"
        
        file_path = os.path.join(API_JSON_DIR, file_name)
        try:
            # 尝试解析JSON以确保其有效性
            parsed_json = json.loads(json_string)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(parsed_json, f, indent=2, ensure_ascii=False)
            gr.Info(f"文件 {file_name} 已成功保存！")
            return json.dumps(parsed_json, indent=2, ensure_ascii=False) # 返回格式化后的内容以更新显示
        except json.JSONDecodeError:
            gr.Error(f"保存失败: 内容不是有效的 JSON 格式。请检查语法。")
            return json_string # 返回原始字符串，以便用户修正
        except FileNotFoundError: # 理论上不应发生，因为文件名来自选择
            gr.Error(f"保存失败: 文件 {file_name} 未找到。")
            return json_string
        except Exception as e:
            gr.Error(f"保存文件 {file_name} 时发生未知错误: {e}")
            return json_string

    def on_file_select_or_refresh(selected_file_name):
        if not selected_file_name:
            return "请选择一个文件。", "选择一个文件以查看其详细信息和内容。"
        content = view_json_content(selected_file_name)
        all_files = get_api_json_files()
        details_str = "未找到文件详细信息。"
        for f_name, f_modified, f_size in all_files:
            if f_name == selected_file_name:
                details_str = f"**文件名:** {f_name}\n\n**最后修改:** {f_modified}\n\n**大小:** {f_size}"
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
        
        new_content, new_details = "", "选择一个文件以查看其详细信息和内容。"
        if new_selection_value:
            new_content, new_details = on_file_select_or_refresh(new_selection_value)
        return gr.update(choices=new_choices_names, value=new_selection_value), new_content, new_details

    refresh_files_button.click(
        fn=refresh_list_and_selection,
        inputs=[selected_json_file_radio],
        outputs=[selected_json_file_radio, json_content_display, file_details_display]
    )

    def handle_delete_and_refresh(file_to_delete, current_selected_in_list):
        # 调用原始的删除函数
        # delete_json_file 返回 (new_file_list_tuples, new_content_display_for_main_view, new_selected_file_name_for_main_view)
        # 但我们需要的是 Radio 的 choices (文件名列表) 和 value (选中的文件名)
        
        # 执行删除
        # 注意：delete_json_file 内部会调用 get_api_json_files() 返回的是元组列表
        # 我们需要将其转换为文件名列表给 Radio
        
        # 这里的逻辑需要调整，因为 delete_json_file 的返回值是 (files_with_details, new_content_display, new_selected_file)
        # files_with_details 是 [(name, modified, size), ...]
        # new_selected_file 是一个文件名字符串或 None
        
        # 我们直接调用 delete_json_file，然后用它的结果来更新UI
        # delete_json_file(file_name_to_delete, selected_file_in_list)
        # outputs=[selected_json_file_radio, json_content_display, selected_json_file_radio]
        # 第一个 selected_json_file_radio 应该是 gr.update(choices=new_names, value=new_selection)
        # 第二个 json_content_display 是内容
        # 第三个 selected_json_file_radio 应该是 gr.update(value=new_selection) -- 但这会覆盖choices，所以不能这么做
        # 我们需要让 delete_json_file 返回适合直接更新 Radio 的 choices 和 value

        # 重新设计 delete_json_file 的返回，或者在这里处理
        # 让我们修改 delete_json_file 的返回
        
        # 假设 delete_json_file 现在返回:
        # 1. gr.update(choices=new_radio_choices, value=new_radio_value) for selected_json_file_radio
        # 2. new_json_content_display
        # 3. new_file_details_display
        
        # 暂时保持原样，在 click 事件中处理转换
        # delete_json_file 返回 (files_with_details_after_delete, content_str, new_selection_name)
        files_after_delete_tuples, new_content_str, new_selected_name = delete_json_file(file_to_delete, current_selected_in_list)
        
        new_radio_choices = [f[0] for f in files_after_delete_tuples]
        
        # 更新详情
        new_details_str = "选择一个文件以查看其详细信息和内容。"
        if new_selected_name:
            for f_name, f_modified, f_size in files_after_delete_tuples:
                if f_name == new_selected_name:
                    new_details_str = f"**文件名:** {f_name}\n\n**最后修改:** {f_modified}\n\n**大小:** {f_size}"
                    break
        elif not new_selected_name and new_content_str == "请先选择一个文件。": # 如果没有选中项且内容是提示
             pass # 保持 details_str 为默认提示

        return gr.update(choices=new_radio_choices, value=new_selected_name), new_content_str, new_details_str

    delete_button.click(
        fn=handle_delete_and_refresh,
        inputs=[selected_json_file_radio, selected_json_file_radio],
        outputs=[selected_json_file_radio, json_content_display, file_details_display]
    )
    # 不需要 .then() 了，因为 handle_delete_and_refresh 会处理所有更新

    save_changes_button.click(
        fn=save_json_content,
        inputs=[selected_json_file_radio, json_content_display], # 文件名和编辑后的内容
        outputs=[json_content_display] # 更新显示区域的内容 (例如格式化后的)
    )


# 如果直接运行此文件，可以启动一个独立的 Gradio 应用进行测试
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
        API_JSON_DIR = folder_paths.get_output_directory() # Re-assign for test

    with gr.Blocks() as demo_test: # 创建一个顶层 Blocks 用于测试
        define_api_json_management_ui() # 调用修改后的函数
    demo_test.launch()
