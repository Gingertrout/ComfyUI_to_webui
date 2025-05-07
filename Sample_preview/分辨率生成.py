resolutions = []
for m in range(16, 129):  # m: 16~128 → 宽 = 64×m (1024~8192)
    for n in range(16, 129):  # n: 16~128 → 高 = 64×n (1024~8192)
        width = 64 * m
        height = 64 * n
        aspect_ratio = width / height
        # 筛选好看的比例，例如接近 16:9、4:3、21:9 或 1:1
        if (abs(aspect_ratio - 16/9) < 0.1 or 
            abs(aspect_ratio - 4/3) < 0.1 or 
            abs(aspect_ratio - 21/9) < 0.1 or 
            abs(aspect_ratio - 1) < 0.1):
            resolutions.append(f"{width}×{height}")

# 保存到文件，指定编码为 utf-8
with open("分辨率列表.txt", "w", encoding="utf-8") as f:
    for res in sorted(resolutions, key=lambda x: int(x.split('×')[0])):  # 改为由小到大排序
        f.write(res + "\n")
