import { app } from "/scripts/app.js"

// 加载图像的函数
function loadImage(base64) {
    const image = new Image();
    image.src = base64;
    return image;
}

// 加载两个图标
const canvasIcon = loadImage("data:image/webp;base64,这里放base64图像"); // 替换为你的Base64编码的图像数据


const outputIcon = loadImage("data:image/webp;base64,这里放base64图像"); // 替换为你的Base64编码的图像数据

// 设置图标的函数
function setIconImage(nodeType, image, size, padRows, padCols) {
    // 保存原始的 onAdded 方法
    const onAdded = nodeType.prototype.onAdded;
    // 重写 onAdded 方法
    nodeType.prototype.onAdded = function () {
        // 调用原始的 onAdded 方法
        onAdded?.apply(this, arguments);
        // 设置节点的大小
        this.size = size;
    };

    // 保存原始的 onDrawBackground 方法
    const onDrawBackground = nodeType.prototype.onDrawBackground;
    // 重写 onDrawBackground 方法
    nodeType.prototype.onDrawBackground = function(ctx) {
        // 调用原始的 onDrawBackground 方法
        onDrawBackground?.apply(this, arguments);

        // 计算图标的偏移量和可用空间
        const pad = [padCols * 20, LiteGraph.NODE_SLOT_HEIGHT * padRows + 8];
        if(this.flags.collapsed || pad[1] + 32 > this.size[1] || image.width === 0) {
            return;
        }
        const avail = [this.size[0] - pad[0], this.size[1] - pad[1]];
        const scale = Math.min(1.0, avail[0] / image.width, avail[1] / image.height);
        const size = [Math.floor(image.width * scale), Math.floor(image.height * scale)];
        const offset = [Math.max(0, (avail[0] - size[0]) / 2), Math.max(0, (avail[1] - size[1]) / 2)];

        // 绘制图标
        ctx.drawImage(image, offset[0], pad[1] + offset[1], size[0], size[1]);
    };
}

// 注册扩展
app.registerExtension({ //这是一个方法，用于注册一个扩展。扩展通常用于在应用程序中添加自定义功能或行为。
    name: "icon",//这是扩展的名称，用于标识这个扩展。在这个例子中，扩展的名称为

    beforeRegisterNodeDef(nodeType, nodeData, app) { //这是一个回调函数，在节点类型注册之前执行。beforeRegisterNodeDef 是这个回调函数的名称，nodeType、nodeData 和 app 是传递给这个函数的参数。
        if (nodeData.name === "GradioInputImage") {// 为特定节点类型设置图标
            setIconImage(nodeType, canvasIcon, [200, 100], 0, 2);
        } else if (nodeData.name === "Hua_Output") {
            setIconImage(nodeType, outputIcon, [200, 100], 1, 0);
        }
    }
});
