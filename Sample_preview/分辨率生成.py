resolutions = []
for m in range(16, 128):  # m: 16~127 → 宽 = 64×m
    for n in range(16, 128):  # n: 16~127 → 高 = 64×n
        width = 64 * m
        height = 64 * n
        aspect_ratio = width / height
        # 筛选好看的比例，例如接近 16:9 或 4:3
        if abs(aspect_ratio - 16/9) < 0.1 or abs(aspect_ratio - 4/3) < 0.1:
            resolutions.append(f"{width}×{height}")

# 保存到文件，指定编码为 utf-8
with open("分辨率列表.txt", "w", encoding="utf-8") as f:
    for res in sorted(resolutions, key=lambda x: int(x.split('×')[0]), reverse=True):
        f.write(res + "\n")