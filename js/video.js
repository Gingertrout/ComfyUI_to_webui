import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";
import { ComfyWidgets } from "/scripts/widgets.js";
import { $el } from "/scripts/ui.js";


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


app.registerExtension({
    name: "Comfy.VideoPreview.Hua",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "Hua_Video_Output") {

            const onNodeCreated = nodeType.prototype.onNodeCreated;
            // Add getExtraMenuOptions to the node prototype
            chainCallback(nodeType.prototype, "getExtraMenuOptions", function(_, options) {
                // `this` refers to the node instance
                if (!this.previewWidget || !this.previewWidget.videoEl || this.previewWidget.videoEl.hidden || !this.previewWidget.videoEl.src) return;

                const previewWidget = this.previewWidget;
                const url = previewWidget.videoEl.src;

                if (url) {
                    const optNew = [
                        {
                            content: "Open preview",
                            callback: () => {
                                window.open(url, "_blank");
                            },
                        },
                        // {
                        //     content: "Save preview",
                        //     callback: () => {
                        //         const a = document.createElement("a");
                        //         a.href = url;
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
                onNodeCreated?.apply(this, arguments);

                const node = this;

                node.previewWidget = null; // Initialize preview widget reference

                node.updatePreviewSource = function(params) {
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
                    previewWidget.videoEl.src = videoPath;
                    previewWidget.videoEl.hidden = false;
                    previewWidget.imgEl.style.display = 'none';
                    previewWidget.videoEl.load(); // Start loading the video
                    previewWidget.videoEl.play().catch(e => console.warn("Autoplay prevented:", e)); // Try to autoplay

                    previewWidget.aspectRatio = null;
                };

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


                const videoWidget = node.widgets?.find(w => w.name === "video");
                if (!videoWidget) {
                     console.warn("Hua_Video_Output: Could not find 'video' widget.");
                }



                const videoWidgetIndex = node.widgets?.findIndex(w => w === videoWidget); // Find the actual widget object
                const previewWidgetIndex = node.widgets?.findIndex(w => w === previewWidget); // Find the actual widget object

                if (videoWidgetIndex !== -1 && previewWidgetIndex !== -1 && node.widgets) {
                    const widgets = node.widgets;
                    if (previewWidgetIndex < videoWidgetIndex) {
                        widgets.splice(previewWidgetIndex, 1);
                        const currentVideoIndex = widgets.findIndex(w => w === videoWidget);
                        widgets.splice(currentVideoIndex + 1, 0, previewWidget);
                        // Force redraw
                        node.setDirtyCanvas(true, true);
                    } else if (previewWidgetIndex > videoWidgetIndex + 1) {
                         widgets.splice(previewWidgetIndex, 1);
                         const currentVideoIndex = widgets.findIndex(w => w === videoWidget);
                         widgets.splice(currentVideoIndex + 1, 0, previewWidget);
                         node.setDirtyCanvas(true, true);
                    }
                } else if (previewWidgetIndex !== -1 && node.widgets && node.widgets.length > 1) {
                    const widgets = node.widgets;
                    if (previewWidgetIndex < widgets.length - 1) {
                        widgets.splice(previewWidgetIndex, 1);
                        widgets.push(previewWidget);
                        node.setDirtyCanvas(true, true);
                    }
                }
                 fitHeight(node); // Adjust height after potentially rearranging widgets
            };

            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function(message) {
                onExecuted?.apply(this, arguments); // Call original onExecuted if exists

                let videoPath = null;
                if (message?.video_path) {
                    videoPath = message.video_path;
                    console.log("Received video_path directly:", videoPath);
                } else if (message?.videos && message.videos.length > 0) {
                    const videoInfo = message.videos[0];
                    if (videoInfo.type === 'gradio' || videoInfo.filename?.startsWith('/file=') || videoInfo.filename?.startsWith('http')) {
                        videoPath = videoInfo.filename;
                        console.log("Received Gradio/absolute video path from videos array:", videoPath);
                    } else if (videoInfo.type === 'output' && videoInfo.filename) {
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
                    this.updatePreviewSource({ video_path: videoPath });
                } else {
                    // if (this.previewWidget?.parentEl) {
                    //     this.previewWidget.parentEl.hidden = true;
                    //     fitHeight(this);
                    // }
                    console.log("No video path received in onExecuted message.");
                }
            };
        }
    },
});
