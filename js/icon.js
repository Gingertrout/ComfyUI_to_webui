import { app } from "/scripts/app.js"

function loadImage(base64) {
    const image = new Image();
    image.src = base64;
    return image;
}

const canvasIcon = loadImage("data:image/webp;base64,REPLACE_WITH_BASE64_ICON");
const outputIcon = loadImage("data:image/webp;base64,REPLACE_WITH_BASE64_ICON");

function setIconImage(nodeType, image, size, padRows, padCols) {
    const onAdded = nodeType.prototype.onAdded;
    nodeType.prototype.onAdded = function () {
        onAdded?.apply(this, arguments);
        this.size = size;
    };

    const onDrawBackground = nodeType.prototype.onDrawBackground;
    nodeType.prototype.onDrawBackground = function(ctx) {
        onDrawBackground?.apply(this, arguments);

        const pad = [padCols * 20, LiteGraph.NODE_SLOT_HEIGHT * padRows + 8];
        if(this.flags.collapsed || pad[1] + 32 > this.size[1] || image.width === 0) {
            return;
        }
        const avail = [this.size[0] - pad[0], this.size[1] - pad[1]];
        const scale = Math.min(1.0, avail[0] / image.width, avail[1] / image.height);
        const size = [Math.floor(image.width * scale), Math.floor(image.height * scale)];
        const offset = [Math.max(0, (avail[0] - size[0]) / 2), Math.max(0, (avail[1] - size[1]) / 2)];

        ctx.drawImage(image, offset[0], pad[1] + offset[1], size[0], size[1]);
    };
}

app.registerExtension({
    name: "icon",
    beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "GradioInputImage") {
            setIconImage(nodeType, canvasIcon, [200, 100], 0, 2);
        } else if (nodeData.name === "Hua_Output") {
            setIconImage(nodeType, outputIcon, [200, 100], 1, 0);
        }
    }
});
