可在我的镜像中直接使用，直接使用本插件的云端算力桌面程序：https://github.com/kungful/xiangongyun_GUI.git
![前后端原理image](https://github.com/kungful/ComfyUI_to_webui/blob/f3b459882f6f9961559f166f21719d662a575584/Sample_preview/%E5%89%8D%E5%90%8E%E7%AB%AF%E5%AF%B9%E6%8E%A5%E5%8E%9F%E7%90%862.png)

## 概述
<span style="color:blue;">**示例工作流在**</span> Sample_preview 文件夹里面
<span style="color:blue;">**`ComfyUI_hua_boy` 是一个为 ComfyUI工作流变成webui的项目**</span>

## 计划的功能
- **收录到comfyui管理器**: 进行中..........
- **实时日志预览**: 编写中............
- **队列功能**:已完成编写
- **多图显示，预览所有图片**:已完成编写
- **自动保存api json流**: 已编写完成
- **gradio前端动态显示图像输入口**：已编写完成
- **模型选择**：已经编写完成
- **分辨率选择**： 已经编写完成
- **种子管理**：已编写完成
- **生成的批次** 开发中.....
  <span style="color:purple;">随机种已经完成</span>
- **增强的界面**：已经优化

## 安装
如果comfyui加载时自动安装模块没能成功可用以下方法手动安装
### 导航到custom_nodes
1. **克隆仓库**：
   ```bash
   git clone https://github.com/kungful/ComfyUI_to_webui.git
   cd ComfyUI_to_webui
   ..\..\..\python_embeded\python.exe -m pip install -r requirements.txt
## 使用方法
你的comfyui搭建好工作流后不需要手动保存api格式json文件，只需要运行一遍跑通后就可以了，在输出端接入"☀️gradio前端传入图像这个节点就行

### 已经完成自动保存api工作流功能，工作流位置在output
1. **api工作流自动保存位置**
   ```bash
   D:\
     └── comfyUI\
       ├── ComfyUI\
       │   ├── output
       │   └── ...
     
### 注意一个问题
建议接入 （🧙hua_gradio随机种）这个节点，不然comfyui识别到相同的json数据不进行推理直接死机.有了随机种的变化就没问题了。

### 思维导图节点
不可推理
![预览image](https://github.com/kungful/ComfyUI_to_webui/blob/4af4203a114cef054bf31287f1f191fa8b0f5742/Sample_preview/6b8564af2dbb2b75185f0bcc7cf5cd5.png)

### 这是检索多提示词字符串判断图片是否传递哪个模型和图片的布尔节点，为的是跳过puilid的报错
![预览image](https://github.com/kungful/ComfyUI_to_webui/blob/4af4203a114cef054bf31287f1f191fa8b0f5742/Sample_preview/image.png)
![预览model](https://github.com/kungful/ComfyUI_to_webui/blob/4af4203a114cef054bf31287f1f191fa8b0f5742/Sample_preview/model.png)
![image](https://github.com/user-attachments/assets/85867dab-ded0-46f3-b0f7-a1e3e0843600)
