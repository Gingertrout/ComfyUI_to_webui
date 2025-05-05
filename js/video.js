import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js"; // 需要 api 来查看预览
import { ComfyWidgets } from "/scripts/widgets.js"; // 可能需要，以防万一
import { $el } from "/scripts/ui.js"; // 用于创建 DOM 元素

// --- 添加辅助函数 ---

// Helper function to chain callbacks
function chainCallback(object, property, callback) {
    if (object == undefined) {
        console.error("Tried to add callback to non-existant object");
        return;
    }
    if (property in object && object[property]) {
        const callback_orig = object[property];
        object[property] = function () {
            const r = callback_orig.apply(this, arguments);
            // If the original callback returns a value, respect it. Otherwise, return the new callback's result.
            const r2 = callback.apply(this, arguments);
            return r !== undefined ? r : r2;
        };
    } else {
        object[property] = callback;
    }
}

// Helper function to fit node height to content
function fitHeight(node) {
    // Debounce fitting height
    if (node.fitHeightTimeout) {
        clearTimeout(node.fitHeightTimeout);
    }
    node.fitHeightTimeout = setTimeout(() => {
        node.setSize([node.size[0], node.computeSize([node.size[0], node.size[1]])[1]]);
        node?.graph?.setDirtyCanvas(true);
        delete node.fitHeightTimeout;
    }, 50); // 50ms debounce
}


// Helper to allow dragging node from widget
function allowDragFromWidget(widget) {
    widget.onPointerDown = function(pointer, node) {
        // A simplified drag handler
        let isDragging = false;
        let dragStartPos = null;
        let nodeStartPos = [...node.pos]; // Copy start position

        pointer.onMove = (e, pos) => {
            if (!isDragging && dragStartPos && LiteGraph.distance(pos, dragStartPos) > 10) {
                isDragging = true;
                app.canvas.isDragging = true; // Let LiteGraph know we are dragging
                app.canvas.graph?.beforeChange(); // Notify graph change start
            }
            if (isDragging) {
                // Calculate movement delta relative to canvas scale
                const deltaX = (pos[0] - dragStartPos[0]) / app.canvas.ds.scale;
                const deltaY = (pos[1] - dragStartPos[1]) / app.canvas.ds.scale;
                node.pos[0] = nodeStartPos[0] + deltaX;
                node.pos[1] = nodeStartPos[1] + deltaY;
                app.canvas.dirty_canvas = true;
                app.canvas.dirty_bgcanvas = true;
            }
        };

        pointer.onDown = (e, pos) => {
            dragStartPos = [...pos]; // Copy position
            nodeStartPos = [...node.pos];
        };

        pointer.onUp = (e, pos) => {
            if (isDragging) {
                app.canvas.isDragging = false;
                app.canvas.graph?.afterChange(); // Notify graph change end
            }
            isDragging = false;
            dragStartPos = null;
        };

        app.canvas.dirty_canvas = true;
        return true; // Consume the event
    };
}

// --- 上传功能已移除 ---

app.registerExtension({
    name: "Comfy.VideoPreview.Hua", // 重命名扩展，因为不再包含上传按钮
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "Hua_Video_Output") {

            const onNodeCreated = nodeType.prototype.onNodeCreated;
            // --- 添加预览功能 ---
            // Add getExtraMenuOptions to the node prototype
            chainCallback(nodeType.prototype, "getExtraMenuOptions", function(_, options) {
                // `this` refers to the node instance
                if (!this.previewWidget || !this.previewWidget.videoEl || this.previewWidget.videoEl.hidden || !this.previewWidget.videoEl.src) return;

                const previewWidget = this.previewWidget;
                const url = previewWidget.videoEl.src; // 直接使用 video 元素的 src

                if (url) {
                    const optNew = [
                        {
                            content: "Open preview",
                            callback: () => {
                                window.open(url, "_blank");
                            },
                        },
                        // Save preview 可能不适用于 Gradio 路径，暂时移除或注释掉
                        // {
                        //     content: "Save preview",
                        //     callback: () => {
                        //         const a = document.createElement("a");
                        //         a.href = url;
                        //         // 尝试从 URL 中提取文件名，但这可能不可靠
                        //         let downloadName = "preview.mp4";
                        //         try {
                        //             const urlObj = new URL(url);
                        //             const pathParts = urlObj.pathname.split('/');
                        //             downloadName = pathParts[pathParts.length - 1] || downloadName;
                        //         } catch (e) { /* ignore invalid URL */ }
                        //         a.setAttribute("download", downloadName);
                        //         document.body.append(a);
                        //         a.click();
                        //         requestAnimationFrame(() => a.remove());
                        //     },
                        // }
                    ];
                     // Add separator if other options exist
                    if (options.length > 0 && options[0] != null && optNew.length > 0) {
                        optNew.unshift(null); // Add separator *before* new options
                    }
                    options.unshift(...optNew);
                }
            });


            nodeType.prototype.onNodeCreated = function () {
                // 调用原始的 onNodeCreated (如果存在)
                onNodeCreated?.apply(this, arguments);

                const node = this; // 当前节点实例

                // --- 预览功能初始化 ---
                node.previewWidget = null; // Initialize preview widget reference

                // Method to update the preview source - 修改为接受完整路径
                node.updatePreviewSource = function(params) {
                    // 现在接收 params = { video_path: "..." }
                    if (!node.previewWidget || !params || !params.video_path) {
                        console.warn("Preview widget or video_path not available for update.");
                        // Optionally hide preview if path is missing
                        if (node.previewWidget?.parentEl) {
                            node.previewWidget.parentEl.hidden = true;
                            fitHeight(node);
                        }
                        return;
                    }

                    const previewWidget = node.previewWidget;
                    const videoPath = params.video_path;

                    console.log("Updating preview source to:", videoPath);

                    previewWidget.parentEl.hidden = false; // Show the container
                    previewWidget.videoEl.src = videoPath; // 直接设置 Gradio 路径
                    previewWidget.videoEl.hidden = false;
                    previewWidget.imgEl.style.display = 'none'; // 确保图片隐藏
                    previewWidget.videoEl.load(); // Start loading the video
                    previewWidget.videoEl.play().catch(e => console.warn("Autoplay prevented:", e)); // Try to autoplay

                    // 重置 aspect ratio，因为新视频可能不同
                    previewWidget.aspectRatio = null;
                    // fitHeight 会在 loadedmetadata 事件中调用
                };

                // --- 创建预览 Widget ---
                var element = document.createElement("div");
                const previewWidget = node.addDOMWidget("videopreview", "preview", element, {
                    serialize: false,
                    hideOnZoom: false, // Keep preview visible on zoom
                });
                node.previewWidget = previewWidget; // Store reference on the node

                allowDragFromWidget(previewWidget); // Allow dragging node from preview

                previewWidget.computeSize = function(width) {
                    if (this.aspectRatio && !this.parentEl.hidden) {
                        let height = (node.size[0] - 20) / this.aspectRatio + 10; // width - margins
                        if (!(height > 0)) {
                            height = 0;
                        }
                        // Limit max height? Maybe node.size[0] * 1.5 ?
                        // height = Math.min(height, node.size[0] * 1.5);
                        this.computedHeight = height + 10; // Add padding
                        return [width, height];
                    }
                    return [width, -4]; // Hide widget if no src/hidden or no aspect ratio yet
                };

                // Prevent default context menu and pass events to canvas
                element.addEventListener('contextmenu', (e) => { e.preventDefault(); return app.canvas._mousedown_callback(e); }, true);
                element.addEventListener('pointerdown', (e) => { e.preventDefault(); return app.canvas._mousedown_callback(e); }, true);
                element.addEventListener('mousewheel', (e) => { e.preventDefault(); return app.canvas._mousewheel_callback(e); }, true);
                element.addEventListener('pointerup', (e) => { e.preventDefault(); return app.canvas._mouseup_callback(e); }, true);

                previewWidget.parentEl = $el("div.vhs_preview", { style: { width: "100%", position: "relative" } }); // Added relative positioning if needed later
                element.appendChild(previewWidget.parentEl);

                previewWidget.videoEl = $el("video", {
                    controls: false, loop: true, muted: true, style: { width: "100%", display: "block" } // Added display block
                });
                previewWidget.videoEl.addEventListener("loadedmetadata", () => {
                    console.log("Video metadata loaded:", previewWidget.videoEl.videoWidth, previewWidget.videoEl.videoHeight);
                    previewWidget.aspectRatio = previewWidget.videoEl.videoWidth / previewWidget.videoEl.videoHeight;
                    fitHeight(node);
                });
                previewWidget.videoEl.addEventListener("error", (e) => {
                    console.error("Error loading video preview:", e.target.error);
                    previewWidget.parentEl.hidden = true;
                    fitHeight(node);
                });
                 // Basic hover to unmute/mute
                previewWidget.videoEl.onmouseenter = () => { previewWidget.videoEl.muted = false; };
                previewWidget.videoEl.onmouseleave = () => { previewWidget.videoEl.muted = true; };

                // 保留 imgEl 以防万一，但默认隐藏
                previewWidget.imgEl = $el("img", { style: { width: "100%", display: "none" }}); // Use display: none instead of hidden attribute
                previewWidget.imgEl.onload = () => {
                    // This shouldn't be called if we only load videos
                    previewWidget.aspectRatio = previewWidget.imgEl.naturalWidth / previewWidget.imgEl.naturalHeight;
                    fitHeight(node);
                };
                 previewWidget.imgEl.onerror = (e) => {
                    console.error("Error loading image preview:", e);
                    previewWidget.parentEl.hidden = true; // Hide parent if image fails (though unlikely to be used)
                    fitHeight(node);
                };

                previewWidget.parentEl.appendChild(previewWidget.videoEl);
                previewWidget.parentEl.appendChild(previewWidget.imgEl);
                previewWidget.parentEl.hidden = true; // Initially hidden
                // --- 结束预览 Widget 创建 ---


                // 查找现有的 video 输入 widget (通常是 ComboBox) - 保留查找，但不再修改其 callback
                const videoWidget = node.widgets?.find(w => w.name === "video");
                if (!videoWidget) {
                     console.warn("Hua_Video_Output: Could not find 'video' widget.");
                }

                // --- 上传按钮已移除 ---

                // --- 移除 videoWidget callback 修改 ---
                // 不再需要根据 ComboBox 选择更新预览

                // 调整 Widget 顺序：确保 preview 在 video 之后 (如果 video widget 存在)
                const videoWidgetIndex = node.widgets?.findIndex(w => w === videoWidget); // Find the actual widget object
                const previewWidgetIndex = node.widgets?.findIndex(w => w === previewWidget); // Find the actual widget object

                if (videoWidgetIndex !== -1 && previewWidgetIndex !== -1 && node.widgets) {
                    const widgets = node.widgets;
                    // 确保 preview 在 video 之后
                    if (previewWidgetIndex < videoWidgetIndex) {
                        // 从原始位置移除 preview
                        widgets.splice(previewWidgetIndex, 1);
                        // 找到 video widget 的新索引 (因为 preview 被移除了)
                        const currentVideoIndex = widgets.findIndex(w => w === videoWidget); // 注意这里应该是 videoWidget 而不是 videoW
                        // 将 preview 插入到 video 之后
                        widgets.splice(currentVideoIndex + 1, 0, previewWidget);
                        // Force redraw
                        node.setDirtyCanvas(true, true);
                    } else if (previewWidgetIndex > videoWidgetIndex + 1) {
                        // 如果 preview 在 video 之后，但中间有其他 widget，也移动它
                         widgets.splice(previewWidgetIndex, 1);
                         const currentVideoIndex = widgets.findIndex(w => w === videoWidget); // 注意这里应该是 videoWidget 而不是 videoW
                         widgets.splice(currentVideoIndex + 1, 0, previewWidget);
                         node.setDirtyCanvas(true, true);
                    }
                } else if (previewWidgetIndex !== -1 && node.widgets && node.widgets.length > 1) {
                    // 如果 videoWidget 不存在，但 preview 不是最后一个 widget，将其移到最后
                    const widgets = node.widgets;
                    if (previewWidgetIndex < widgets.length - 1) {
                        widgets.splice(previewWidgetIndex, 1);
                        widgets.push(previewWidget);
                        node.setDirtyCanvas(true, true);
                    }
                }
                 fitHeight(node); // Adjust height after potentially rearranging widgets
            };

            // --- 添加 onExecuted 来处理后端传来的视频路径 ---
            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function(message) {
                onExecuted?.apply(this, arguments); // Call original onExecuted if exists

                // 检查 message 中是否包含我们期望的视频信息
                // 假设 message.videos 是一个数组，包含 { filename: "...", type: "gradio" / "output", ... }
                // 或者直接是 message.video_path
                let videoPath = null;
                if (message?.video_path) {
                    videoPath = message.video_path;
                    console.log("Received video_path directly:", videoPath);
                } else if (message?.videos && message.videos.length > 0) {
                    const videoInfo = message.videos[0];
                    // 优先使用明确的 Gradio 类型或绝对路径
                    if (videoInfo.type === 'gradio' || videoInfo.filename?.startsWith('/file=') || videoInfo.filename?.startsWith('http')) {
                        videoPath = videoInfo.filename;
                        console.log("Received Gradio/absolute video path from videos array:", videoPath);
                    } else if (videoInfo.type === 'output' && videoInfo.filename) {
                         // 如果是 output 类型，尝试构造 /view URL 作为后备
                         console.warn("Received 'output' type video, constructing /view URL as fallback:", videoInfo);
                         const params = {
                             filename: videoInfo.filename,
                             type: videoInfo.type,
                             subfolder: videoInfo.subfolder || '',
                             // timestamp: Date.now() // Add cache buster?
                         };
                         videoPath = api.apiURL('/view?' + new URLSearchParams(params));
                    } else {
                        console.warn("Received video data, but unsure how to form the path:", videoInfo);
                    }
                }

                if (videoPath) {
                    // 调用更新预览的方法，传入完整路径
                    this.updatePreviewSource({ video_path: videoPath });
                } else {
                    // 如果没有收到视频路径，可以选择隐藏预览
                    // if (this.previewWidget?.parentEl) {
                    //     this.previewWidget.parentEl.hidden = true;
                    //     fitHeight(this);
                    // }
                    console.log("No video path received in onExecuted message.");
                }
            };
            // --- 结束 onExecuted ---
        }
    },
});
