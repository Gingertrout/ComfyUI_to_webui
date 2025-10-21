// Assume app is defined in the ComfyUI environment
import { app } from "../../../scripts/app.js";

// Create a global action registry
const KayToolActions = window.KayToolActions || {};
window.KayToolActions = KayToolActions;

// --- Helper class for exporting workflow to PNG ---
class KayWorkflowImage {
    constructor() {
        this.state = {}; // Initialize state object
        this.extension = "png"; // Default extension
    }

    // Method to save the current canvas state
    saveState() {
        this.state = {
            scale: app.canvas.ds.scale,
            width: app.canvas.canvas.width,
            height: app.canvas.canvas.height,
            offset: app.canvas.ds.offset,
            transform: app.canvas.canvas.getContext("2d").getTransform(),
        };
    }

    // Method to calculate the bounds of the workflow nodes
    getBounds() {
        const marginSize = app.ui.settings.getSettingValue("KayTool.WorkflowPNG") || 50;
        const bounds = app.graph._nodes.reduce(
            (p, node) => {
                if (node.pos[0] < p[0]) p[0] = node.pos[0];
                if (node.pos[1] < p[1]) p[1] = node.pos[1];
                const nodeBounds = node.getBounding(); // [x, y, width, height] relative to node.pos
                const right = node.pos[0] + nodeBounds[2];
                const bottom = node.pos[1] + nodeBounds[3];
                if (right > p[2]) p[2] = right;
                if (bottom > p[3]) p[3] = bottom;
                return p;
            },
            [99999, 99999, -99999, -99999] // minX, minY, maxX, maxY
        );
        bounds[0] -= marginSize; // minX
        bounds[1] -= marginSize; // minY
        bounds[2] += marginSize; // maxX
        bounds[3] += marginSize; // maxY
        return bounds;
    }

    // Method to update the canvas view based on calculated bounds
    updateView(bounds) {
        const scale = window.devicePixelRatio || 1;
        app.canvas.ds.scale = 1; // Set scale to 1 for export
        // Calculate new width and height based on bounds
        app.canvas.canvas.width = (bounds[2] - bounds[0]) * scale;
        app.canvas.canvas.height = (bounds[3] - bounds[1]) * scale;
        // Adjust offset so top-left of bounds is at [0,0] of canvas
        app.canvas.ds.offset = [-bounds[0], -bounds[1]];
        app.canvas.canvas.getContext("2d").setTransform(scale, 0, 0, scale, 0, 0);
    }

    // Method to restore the canvas state
    restoreState() {
        if (this.state && Object.keys(this.state).length > 0) {
            app.canvas.ds.scale = this.state.scale;
            app.canvas.canvas.width = this.state.width;
            app.canvas.canvas.height = this.state.height;
            app.canvas.ds.offset = this.state.offset;
            app.canvas.canvas.getContext("2d").setTransform(this.state.transform);
            app.canvas.draw(true, true); // Redraw canvas with restored state
        } else {
            console.warn("No state to restore or state is empty.");
        }
    }

    numberToBytes(num) {
        const buffer = new ArrayBuffer(4);
        const view = new DataView(buffer);
        view.setUint32(0, num, false); // PNG uses big-endian
        return buffer;
    }

    crc32(data) { // data is Uint8Array or similar
        const table = new Uint32Array(256);
        for (let i = 0; i < 256; i++) {
            let c = i;
            for (let k = 0; k < 8; k++) {
                c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
            }
            table[i] = c;
        }
        let crc = -1;
        const byteArray = (data instanceof Uint8Array) ? data : new Uint8Array(data); // Ensure it's Uint8Array
        for (let i = 0; i < byteArray.byteLength; i++) {
            crc = (crc >>> 8) ^ table[(crc ^ byteArray[i]) & 0xff];
        }
        return crc ^ -1;
    }

    joinArrayBuffer(...arrays) {
        const totalLength = arrays.reduce((acc, arr) => acc + (arr.byteLength || arr.length), 0);
        const result = new Uint8Array(totalLength);
        let offset = 0;
        for (const arr of arrays) {
            result.set(new Uint8Array(arr), offset);
            offset += (arr.byteLength || arr.length);
        }
        return result.buffer;
    }

    // This getBlob method is based on the user's provided reference for PNG embedding
    async getBlob(workflow) { // workflow is a JSON string or undefined
        return new Promise((resolve) => {
            // Ensure canvasEl is used as per user's reference for toBlob
            app.canvasEl.toBlob(async (blob) => { 
                if (!blob) {
                    console.error("Failed to generate blob from canvas");
                    resolve(null);
                    return;
                }
                if (workflow) {
                    try {
                        const buffer = await blob.arrayBuffer();
                        const typedArr = new Uint8Array(buffer);
                        const view = new DataView(buffer);
                        
                        // data = ChunkType ("tEXt") + ChunkData (keyword + \0 + workflow_json)
                        // The keyword "workflow" is part of the chunk data.
                        const textEncoder = new TextEncoder();
                        const chunkTypeAndData = textEncoder.encode(`tEXtworkflow\0${workflow}`); 

                        // chunk = Length_Bytes + ChunkTypeAndData_Bytes + CRC_Bytes
                        // Length is of (ChunkType + ChunkData) part, but PNG spec says length is for ChunkData only.
                        // The reference code calculates length as data.byteLength - 4.
                        // 'data' in reference is `tEXtworkflow\0${workflow}`.
                        // So, length is for `workflow\0${workflow}`. This seems incorrect.
                        // Standard tEXt chunk: Length (4 bytes), ChunkType "tEXt" (4 bytes), Keyword (1-79 bytes), Null Separator (1 byte), Text (0 or more bytes), CRC (4 bytes)
                        // Length should be for (Keyword + Null Separator + Text).
                        // Let's follow the user's provided logic for chunk construction.
                        // User's `data` = `tEXtworkflow\0${workflow}`.
                        // User's `chunkDataLength` = `data.byteLength - 4` (length of `workflow\0${workflow}`).
                        // User's CRC is calculated over `data` (`tEXtworkflow\0${workflow}`).

                        const keywordAndText = textEncoder.encode(`workflow\0${workflow}`);
                        const chunkType = textEncoder.encode('tEXt');
                        
                        const fullChunkDataForCrc = new Uint8Array(chunkType.length + keywordAndText.length);
                        fullChunkDataForCrc.set(chunkType, 0);
                        fullChunkDataForCrc.set(keywordAndText, chunkType.length);

                        const crc = this.crc32(fullChunkDataForCrc); 

                        const chunk = this.joinArrayBuffer(
                            this.numberToBytes(keywordAndText.byteLength), // Length of (keyword + \0 + workflow_json)
                            chunkType,                                    // "tEXt"
                            keywordAndText,                               // "workflow\0${workflow}"
                            this.numberToBytes(crc)                       // CRC of (tEXtworkflow\0${workflow})
                        );
                        
                        // Find insertion point: after IHDR chunk.
                        // PNG signature (8 bytes) + IHDR chunk (Length (4) + Type "IHDR" (4) + Data (13) + CRC (4) = 25 bytes)
                        // So, IHDR chunk ends at 8 + 25 = 33 bytes from the start of the file.
                        // The reference uses `view.getUint32(8, false) + 20;`
                        // `view.getUint32(8, false)` is the length of IHDR data (13).
                        // So, 13 (IHDR data length) + 4 (IHDR type "IHDR") + 4 (IHDR length field) + 4 (IHDR CRC) = 25.
                        // The offset 8 is to skip PNG signature. So, 8 + 4 (IHDR length) + 4 (IHDR type) + 13 (IHDR data) + 4 (IHDR CRC) = 33.
                        // The reference's `insertionPointOffset = view.getUint32(8, false) + 20;`
                        // If `view.getUint32(8, false)` is IHDR data length (13), then 13 + 20 = 33. This is correct.
                        // This means the insertion point is right after the IHDR chunk (including its CRC).
                        const ihdrDataLength = view.getUint32(8, false); // Length of IHDR chunk's data part
                        const insertionPointOffset = 8 + 4 + 4 + ihdrDataLength + 4; // PNG sig + IHDR length + IHDR type + IHDR data + IHDR CRC

                        if (insertionPointOffset > typedArr.length || insertionPointOffset < 0) {
                            console.error("Invalid insertion point offset for PNG chunk:", insertionPointOffset, "Buffer length:", typedArr.length);
                            resolve(blob); // return original blob on error
                            return;
                        }

                        const result = this.joinArrayBuffer(
                            typedArr.subarray(0, insertionPointOffset), // Part before IHDR's end
                            chunk,                                      // Our new tEXt chunk
                            typedArr.subarray(insertionPointOffset)     // Rest of the PNG
                        );
                        blob = new Blob([result], { type: "image/png" });
                    } catch(e) {
                        console.error("Error during PNG workflow embedding:", e);
                        // resolve(blob); // Return original blob on error - No, resolve with null or error
                        resolve(null); // Indicate failure
                        return;
                    }
                }
                resolve(blob);
            }, "image/png");
        });
    }

    // download method from user's reference
    download(blob, filename) { // filename now includes extension
        if (!blob) {
            console.error("Download failed: blob is null.");
            showNotification({ message: "Error: Failed to generate image for download.", bgColor: "#f8d7da" });
            return;
        }
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        Object.assign(a, {
            href: url,
            download: filename || `workflow.${this.extension}`, // Use provided filename or default
            style: "display: none",
        });
        document.body.append(a);
        a.click();
        setTimeout(() => { // Use setTimeout to ensure click has processed
            a.remove();
            window.URL.revokeObjectURL(url);
        }, 0);
    }

    async saveToJSON(workflowString, filename = "workflow.json") { // workflowString is already JSON.stringify'd, added filename param
        try {
            const dataToSave = JSON.parse(workflowString); // To pretty print, parse then stringify
            const jsonPrettyString = JSON.stringify(dataToSave, null, 2);
            const blob = new Blob([jsonPrettyString], { type: "application/json" });
            
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = filename; // Use provided filename
            document.body.appendChild(a); // Required for Firefox
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (error) {
            console.error("Failed to save JSON file:", error);
            showNotification({ message: `Failed to save JSON file '${filename}': ${error.message}`, bgColor: "#f8d7da" });
        }
    }

    async export(includeWorkflow) { // Restored includeWorkflow parameter
        const userBaseFilename = prompt("Enter base name for local PNG and JSON files (no extension, e.g. my_workflow):", "workflow_export");
        if (!userBaseFilename || userBaseFilename.trim() === "") {
            showNotification({ message: "Save canceled or base name is empty.", bgColor: "#ffc107", timeout: 3000 });
            return;
        }
        const baseName = userBaseFilename.trim();

        this.saveState();
        const bounds = this.getBounds();
        this.updateView(bounds);

        app.canvas.draw(true, true); // Ensure the current view is fully rendered

        const workflowJsonString = includeWorkflow ? JSON.stringify(app.graph.serialize()) : undefined;
        const pngBlob = await this.getBlob(workflowJsonString);

        this.restoreState(); // Restore canvas state regardless of blob success

        if (pngBlob) {
            const pngFilename = includeWorkflow ? `${baseName}_with_data.${this.extension}` : `${baseName}_no_data.${this.extension}`;
            this.download(pngBlob, pngFilename);
            showNotification({ message: `Saved: ${pngFilename}`, bgColor: "#d4edda", timeout: 3000 });

            if (includeWorkflow && workflowJsonString) { // If embedding, also save the JSON separately
                const localJsonFilename = `${baseName}_workflow.json`;
                await this.saveToJSON(workflowJsonString, localJsonFilename);
                showNotification({ message: `Saved: ${localJsonFilename}`, bgColor: "#d4edda", timeout: 3000 });
            }
             if (includeWorkflow) {
                showNotification({ message: `PNG with workflow and JSON download started (based on "${baseName}")`, bgColor: "#d4edda", timeout: 5000 });
            } else {
                showNotification({ message: `PNG without workflow download started (based on "${baseName}")`, bgColor: "#d4edda", timeout: 5000 });
            }

        } else {
            console.error("Failed to export workflow: PNG Blob generation failed.");
            showNotification({ message: "Error: PNG blob generation failed.", bgColor: "#f8d7da" });
        }
    }
}
// --- End of KayWorkflowImage class ---

// --- Notification Dialog ---
function showNotification({ 
    message, bgColor = "#fff3cd", timeout = 0, onYes = null, onNo = null, size = "small"
}) {
    const sizes = {
        small: { maxWidth: "250px", maxHeight: "150px", padding: "12px 16px" },
        medium: { maxWidth: "400px", maxHeight: "300px", padding: "12px 16px" },
        large: { maxWidth: "600px", maxHeight: "450px", padding: "12px 16px" }
    };
    const selectedSize = sizes[size] || sizes.small;
    const div = document.createElement("div");
    Object.assign(div.style, {
        position: "fixed", width: selectedSize.maxWidth, padding: selectedSize.padding,
        backgroundColor: bgColor, color: "#333", fontFamily: "'Courier New', monospace",
        fontSize: "14px", wordWrap: "break-word", zIndex: "10003",
        border: "2px solid #000", borderRadius: "12px", boxShadow: "4px 4px 0 #999",
        opacity: "0", transition: "opacity 0.3s ease-in-out", display: "flex",
        flexDirection: "column", gap: "8px", boxSizing: "border-box",
        left: "50%", top: "50%", transform: "translate(-50%, -50%)"
    });
    document.body.appendChild(div);
    const closeButton = document.createElement("div");
    closeButton.textContent = "X";
    Object.assign(closeButton.style, {
        position: "absolute", top: "12px", left: "12px", width: "12px", height: "12px",
        backgroundColor: "#dc3545", border: "2px solid #000", borderRadius: "50%",
        fontSize: "10px", lineHeight: "10px", textAlign: "center", cursor: "pointer",
        boxShadow: "2px 2px 0 #999"
    });
    closeButton.addEventListener("click", () => hideNotification(div));
    div.appendChild(closeButton);
    const contentDiv = document.createElement("div");
    Object.assign(contentDiv.style, {
        marginTop: "20px", overflowY: "auto", overflowX: "hidden", padding: "0 4px 0 0",
        boxSizing: "border-box", wordBreak: "break-word", fontFamily: "'Courier New', monospace",
        whiteSpace: "pre-wrap", textAlign: "center"
    });
    contentDiv.innerHTML = message.replace(/\n/g, '<br>'); 
    div.appendChild(contentDiv);
    let buttonContainer = null;
    if (onYes || onNo) {
        buttonContainer = document.createElement("div");
        Object.assign(buttonContainer.style, {
            display: "flex", gap: "8px", justifyContent: "center", 
            marginTop: "15px", paddingBottom: "4px"
        });
        div.appendChild(buttonContainer);
        if (onYes) {
            const yesButton = document.createElement("button");
            yesButton.textContent = "Yes";
            Object.assign(yesButton.style, {
                padding: "8px 15px", backgroundColor: "#28a745", border: "2px solid #000",
                borderRadius: "8px", fontFamily: "'Courier New', monospace", fontSize: "14px",
                fontWeight: "bold", color: "#fff", cursor: "pointer", boxShadow: "2px 2px 0 #999"
            });
            yesButton.addEventListener("click", () => { hideNotification(div); onYes(); });
            buttonContainer.appendChild(yesButton);
        }
        if (onNo) {
            const noButton = document.createElement("button");
            noButton.textContent = "No";
            Object.assign(noButton.style, {
                padding: "8px 15px", backgroundColor: "#dc3545", border: "2px solid #000",
                borderRadius: "8px", fontFamily: "'Courier New', monospace", fontSize: "14px",
                fontWeight: "bold", color: "#fff", cursor: "pointer", boxShadow: "2px 2px 0 #999"
            });
            noButton.addEventListener("click", () => { hideNotification(div); onNo(); });
            buttonContainer.appendChild(noButton);
        }
    }
    const updateHeights = () => {
        const buttonHeight = buttonContainer ? buttonContainer.offsetHeight : 0;
        const totalExtraHeight = buttonHeight + 36 + 20;
        div.style.maxHeight = `calc(${selectedSize.maxHeight} + ${totalExtraHeight}px)`;
        contentDiv.style.maxHeight = `calc(${selectedSize.maxHeight} - ${totalExtraHeight}px)`;
    };
    updateHeights();
    setTimeout(() => (div.style.opacity = "1"), 10);
    if (timeout > 0) setTimeout(() => hideNotification(div), timeout);
    div.hide = () => hideNotification(div);
    return div;
}
function hideNotification(element) {
    if (element?.parentNode) {
        element.style.opacity = "0";
        setTimeout(() => element.parentNode?.removeChild(element), 300);
    }
}
// --- End of Notification Dialog ---

// Floating icon manager
const FloatingIconManager = {
    container: null, contextMenu: null, isEnabled: true,
    imgSrc: new URL("biubiu.png", import.meta.url).pathname,
    isDragging: false, dragStartX: 0, dragStartY: 0, iconStartX: 0, iconStartY: 0,
    kayWorkflowImageInstance: null,
    init() {
        this.isEnabled = false;
        this.loadState(); this.injectStyles(); this.setupFloatingIcon();
        window.FloatingIconManager = this;
        if (this.isEnabled) this.showIcon();
        this.kayWorkflowImageInstance = new KayWorkflowImage();
    },
    injectStyles() {
        document.head.insertAdjacentHTML( "beforeend",
            `<style>
            #kay-floating-icon-container { position: fixed; z-index: 10002; user-select: none; display: none; cursor: grab; }
            #kay-floating-icon-container.enabled { display: block; }
            #kay-floating-icon-container img { width: 48px; height: auto; display: block; pointer-events: auto; }
            .floating-icon-context-menu { position: fixed; background: #333; border: 2px solid #000; border-radius: 8px; box-shadow: 4px 4px 0 #999; padding: 8px 0; z-index: 10002; font-family: 'Courier New', monospace; font-size: 14px; color: #fff; white-space: nowrap; overflow-y: auto; }
            .floating-icon-context-menu::-webkit-scrollbar { width: 8px; }
            .floating-icon-context-menu::-webkit-scrollbar-track { background: #333; border-left: 2px solid #000; }
            .floating-icon-context-menu::-webkit-scrollbar-thumb { background: #f0ff00; border: 50px solid #f0ff00; }
            .floating-icon-context-menu-item { padding: 4px 12px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; font-weight: bold; white-space: nowrap; }
            .floating-icon-context-menu-item:hover { background: #555; }
        </style>`
        );
    },
    setupFloatingIcon() {
        if (!this.container) {
            this.container = document.createElement("div"); this.container.id = "kay-floating-icon-container";
            const img = document.createElement("img"); img.src = this.imgSrc; img.alt = "Floating Icon";
            this.container.appendChild(img); document.body.appendChild(this.container);
            this.bindEvents();
        }
        this.container.classList.toggle("enabled", this.isEnabled);
    },
    bindEvents() {
        const imgEl = this.container.querySelector("img");
        if (imgEl) {
            imgEl.removeEventListener("click", this.onClick.bind(this));
            imgEl.removeEventListener("mousedown", this.onMouseDown.bind(this));
        }
        if (imgEl && this.isEnabled) {
            imgEl.addEventListener("click", this.onClick.bind(this));
            imgEl.addEventListener("mousedown", this.onMouseDown.bind(this));
        }
    },
    onMouseDown(e) {
        if (e.button !== 0) return; e.preventDefault(); this.isDragging = true;
        this.dragStartX = e.clientX; this.dragStartY = e.clientY;
        const rect = this.container.getBoundingClientRect();
        this.iconStartX = rect.left; this.iconStartY = rect.top;
        this.container.style.cursor = 'grabbing';
        this.boundOnMouseMove = this.onMouseMove.bind(this); this.boundOnMouseUp = this.onMouseUp.bind(this);
        document.addEventListener("mousemove", this.boundOnMouseMove);
        document.addEventListener("mouseup", this.boundOnMouseUp);
    },
    onMouseMove(e) {
        if (!this.isDragging) return; e.preventDefault();
        const deltaX = e.clientX - this.dragStartX; const deltaY = e.clientY - this.dragStartY;
        let newX = this.iconStartX + deltaX; let newY = this.iconStartY + deltaY;
        const iconW = this.container.offsetWidth; const iconH = this.container.offsetHeight;
        const maxX = window.innerWidth - iconW; const maxY = window.innerHeight - iconH;
        newX = Math.max(0, Math.min(newX, maxX)); newY = Math.max(0, Math.min(newY, maxY));
        this.container.style.left = `${newX}px`; this.container.style.top = `${newY}px`;
    },
    onMouseUp(e) {
        if (!this.isDragging) return; e.preventDefault(); this.isDragging = false;
        this.container.style.cursor = 'grab';
        document.removeEventListener("mousemove", this.boundOnMouseMove);
        document.removeEventListener("mouseup", this.boundOnMouseUp);
        this.boundOnMouseMove = null; this.boundOnMouseUp = null;
        this.state = this.state || {}; this.state.position = { left: this.container.style.left, top: this.container.style.top };
        this.saveState();
    },
    onClick(e) { e.preventDefault(); this.hideContextMenu(); this.showContextMenu(e.clientX, e.clientY); },
    showContextMenu(x, y) {
        const menuItems = [
            { label: "🚀 Open Gradio Workflow UI (port 7861)", action: () => this.goToLocalPort() },
            { label: "📦 Open Plugin Repository", action: () => this.goToMyRepo() },
            { label: "💾 Save PNG & JSON (with/without workflow)", action: () => this.savePngAndJson() },
            { label: "📝 Save API JSON to Server (custom name)", action: () => this.saveApiJsonToServer() }, 
            { label: "📄 Download Pure Workflow JSON (custom name)", action: () => this.savePureWorkflowJsonToLocalCustom() } 
        ];
        this.contextMenu = document.createElement("div"); this.contextMenu.className = "floating-icon-context-menu";
        document.body.appendChild(this.contextMenu);

        // Add title to the context menu
        const titleEl = document.createElement("div");
        titleEl.textContent = "ComfyUI_to_webui Plugin";
        Object.assign(titleEl.style, {
            padding: "8px 12px",
            fontWeight: "bold",
            textAlign: "center",
            borderBottom: "1px solid #555", // Optional: adds a separator line
            color: "#00ff15" // Make title color distinct
        });
        this.contextMenu.appendChild(titleEl);

        menuItems.forEach(item => {
            const menuItemEl = document.createElement("div"); menuItemEl.className = "floating-icon-context-menu-item";
            menuItemEl.textContent = item.label;
            menuItemEl.addEventListener("click", (event) => {
                event.stopPropagation(); item.action(); this.hideContextMenu();
            });
            this.contextMenu.appendChild(menuItemEl);
        });
        const menuW = this.contextMenu.offsetWidth; const menuH = this.contextMenu.offsetHeight;
        const vpW = window.innerWidth; const vpH = window.innerHeight;
        if (x + menuW > vpW) x = vpW - menuW - 10; if (y + menuH > vpH) y = vpH - menuH - 10;
        if (x < 0) x = 10; if (y < 0) y = 10;
        this.contextMenu.style.left = `${x}px`; this.contextMenu.style.top = `${y}px`;
        setTimeout(() => {
            if (!this.boundHandleDocumentClickForMenu) {
                this.boundHandleDocumentClickForMenu = this.handleDocumentClickForMenu.bind(this);
                document.addEventListener("click", this.boundHandleDocumentClickForMenu, true);
                document.addEventListener("mousedown", this.boundHandleDocumentClickForMenu, true);
            }
        }, 0);
    },
    handleDocumentClickForMenu(e) {
        if (this.contextMenu && (this.contextMenu.contains(e.target) || (this.container && this.container.contains(e.target)))) return;
        this.hideContextMenu();
    },
    hideContextMenu() {
        if (this.contextMenu) {
            this.contextMenu.remove(); this.contextMenu = null;
            if (this.boundHandleDocumentClickForMenu) {
                document.removeEventListener("click", this.boundHandleDocumentClickForMenu, true);
                document.removeEventListener("mousedown", this.boundHandleDocumentClickForMenu, true);
                this.boundHandleDocumentClickForMenu = null;
            }
        }
    },
    goToLocalPort() { window.open("http://localhost:7861", "_blank"); },
    goToMyRepo() { window.open("https://github.com/kungful/ComfyUI_to_webui.git", "_blank"); },
    savePngAndJson() { 
        showNotification({
            message: "Do you want to embed workflow information into the PNG?\n(Yes: download PNG with embedded workflow and workflow.json)\n(No: download PNG without workflow)",
            size: "medium",
            onYes: () => { 
                if (this.kayWorkflowImageInstance) {
                    this.kayWorkflowImageInstance.export(true); 
                } else {
                    console.error("KayWorkflowImage instance not found (yes)!");
                    showNotification({ message: "Error: KayWorkflowImage instance not found.", bgColor: "#f8d7da" });
                }
            },
            onNo: () => { 
                if (this.kayWorkflowImageInstance) {
                    this.kayWorkflowImageInstance.export(false); // download PNG without workflow
                } else {
                    console.error("KayWorkflowImage instance not found (no)!");
                    showNotification({ message: "Error: KayWorkflowImage instance not found.", bgColor: "#f8d7da" });
                }
            }
        });
    },

    async saveApiJsonToServer() { // Renamed original method slightly in label for clarity
        const serverFileName = prompt("Enter API JSON filename to save in server 'output' folder (without .json):", "api_workflow_custom_name");
        if (!serverFileName || serverFileName.trim() === "") {
            showNotification({ message: "Save API JSON to server canceled or filename empty.", bgColor: "#ffc107", timeout: 3000 });
            return;
        }

        try {
            const promptData = await app.graphToPrompt(); // Get object containing output and workflow
            if (!promptData || typeof promptData.output === 'undefined') {
                showNotification({ message: "Unable to get API JSON (output is empty/undefined).", bgColor: "#f8d7da", timeout: 5000 });
                console.error("Unable to get API JSON (app.graphToPrompt() output is empty/undefined)");
                return;
            }
            const apiOutput = promptData.output; // Extract the output
            const apiJsonString = JSON.stringify(apiOutput, null, 2); // Pretty JSON string

            const response = await fetch("/comfyui_to_webui/save_api_json", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    filename: serverFileName.trim(),
                    api_data: apiJsonString,
                }),
            });

            if (response.ok) {
                const result = await response.json();
                showNotification({ message: result.message || `Saved API JSON '${serverFileName.trim()}.json' to server.`, bgColor: "#d4edda", timeout: 5000 });
                console.log("Saved API JSON to server:", result);
            } else {
                const errorResult = await response.json().catch(() => ({ detail: "Failed to save API JSON to server; cannot parse error." }));
                showNotification({ message: `Failed to save API JSON to server: ${errorResult.detail || response.statusText}`, bgColor: "#f8d7da", timeout: 7000 });
                console.error("Failed to save API JSON to server:", errorResult);
            }
        } catch (error) {
            showNotification({ message: `Error saving API JSON to server: ${error.message}`, bgColor: "#f8d7da", timeout: 7000 });
            console.error("Error saving API JSON to server:", error);
        }
    },

    // Removed saveApiJsonToServerAuto method as it's now redundant.
    // The functionality of "Save API JSON to Server (custom name)" covers the need for custom naming of API JSON.

    async savePureWorkflowJsonToLocalCustom() { 
        const localJsonFilenamePrompt = prompt("Enter local filename for pure workflow JSON (without .json):", "pure_workflow_local_custom");
        if (!localJsonFilenamePrompt || localJsonFilenamePrompt.trim() === "") {
            showNotification({ message: "Download canceled or filename empty.", bgColor: "#ffc107", timeout: 3000 });
            return;
        }
        const localJsonFilenameBase = localJsonFilenamePrompt.trim();
        const localJsonFilename = `${localJsonFilenameBase}.json`;

        showNotification({ message: `Preparing pure workflow JSON download '${localJsonFilename}'...`, bgColor: "#e2e3e5", timeout: 2000 });

        try {
            const pureJson = app.graph.serialize(); // Get pure workflow JSON object
            if (!pureJson) { 
                showNotification({ message: "Unable to get pure workflow JSON for download.", bgColor: "#f8d7da", timeout: 5000 });
                console.error("Unable to get pure workflow JSON (app.graph.serialize() returned null/undefined).");
                return;
            }
            
            const pureJsonString = JSON.stringify(pureJson, null, 2); 

            if (this.kayWorkflowImageInstance) {
                await this.kayWorkflowImageInstance.saveToJSON(pureJsonString, localJsonFilename);
                showNotification({ message: `Pure workflow JSON '${localJsonFilename}' download started.`, bgColor: "#d4edda", timeout: 5000 });
            } else {
                console.error("KayWorkflowImage instance not found for savePureWorkflowJsonToLocalCustom!");
                showNotification({ message: "Error: KayWorkflowImage instance not found; cannot download JSON.", bgColor: "#f8d7da" });
            }
        } catch (error) {
            showNotification({ message: `Error downloading pure workflow JSON '${localJsonFilename}': ${error.message}`, bgColor: "#f8d7da", timeout: 7000 });
            console.error("Error downloading pure workflow JSON:", error);
        }
    },

    loadState() {
        const savedState = localStorage.getItem("kay-floating-icon-state");
        if (savedState) {
            this.state = JSON.parse(savedState);
            if (this.state && this.state.position && this.container) {
                this.container.style.left = this.state.position.left;
                this.container.style.top = this.state.position.top;
            }
        } else if (this.container) {
            this.container.style.right = `20px`; this.container.style.bottom = `20px`;
            this.container.style.left = `auto`; this.container.style.top = `auto`; 
        }
    },
    saveState() { if (this.state) localStorage.setItem("kay-floating-icon-state", JSON.stringify(this.state)); },
    showIcon() {
        if (this.container) {
            this.container.style.display = "block";
            if (!this.container.style.left && !this.container.style.right) {
                this.loadState();
                 if (!this.container.style.left && !this.container.style.right) {
                    this.container.style.right = `20px`; this.container.style.bottom = `20px`;
                    this.container.style.left = `auto`; this.container.style.top = `auto`; 
                }
            }
        }
    },
    hideIcon() { if (this.container) this.container.style.display = "none"; }
};
FloatingIconManager.init();
app.registerExtension({
    name: "KayTool.FloatingIcon",
    init() {}, setup() {}
});
