from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 圆角底：与 web favicon 同色 #0096D6
d.rounded_rectangle([0, 0, S - 1, S - 1], radius=56, fill=(0, 150, 214, 255))

W = 17
WHITE = (255, 255, 255, 255)

def rr(box, r):
    d.rounded_rectangle(box, radius=r, outline=WHITE, width=W)

# 打印机主体
rr([46, 96, 210, 176], 20)
# 顶部进纸
d.line([(74, 96), (74, 46), (182, 46), (182, 96)], fill=WHITE, width=W, joint="curve")
# 出纸口
rr([74, 150, 182, 214], 14)

# 圆形裁切，保证托盘小尺寸也好看
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=56, fill=255)
img.putalpha(mask)

img.save("app/ui/favicon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save("app/ui/icon-256.png")
print("ico ok", __import__("os").path.getsize("app/ui/favicon.ico"))
