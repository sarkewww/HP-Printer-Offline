# 真机验收记录

设备：HP Ink Tank Wireless 410 series（`HPSERIAL`，序列号 `000000000010`，固件 `KEP1FN2020AR`）
地址：`192.168.1.100`　服务：`http://127.0.0.1:8791`

## 1. 发现

```
[hp.discovery] WS-D 发现设备 192.168.1.100 (Ink Tank Wireless 410 series)
[hp.discovery] 子网扫描 1012 个地址（并发 200）
[hp.discovery] 发现结束：1 台设备（耗时 6.7s）
[hp.server]   已自动添加打印机 Ink Tank Wireless 410 series @ 192.168.1.100
```
WS-Discovery 主路径成功；mDNS / SNMP 在本机环境无响应（已实现但静默）；
子网扫描兜底有效（打印机被占用时 WSD 会失败，此时由扫描补上）。

## 2. 状态 / 耗材

`GET /api/printers/{id}/status?refresh=1` 返回真实数据：
- `state: idle` / `state_reason: inPowerSave` / `state_message: 就绪（电源节省）`
- `counters: {total_pages: 689, scan_pages: 118, jam_events: 1}`
- `supplies`: 黑色 / 三色，`level: -1`（设备不报百分比 → 正确降级，不编造数字）
- `capabilities`: 来自 IPP + eSCL 合并（29 种纸张、1200dpi、单面、无 ADF）

## 3. 打印（IPP）

`POST /api/print/upload` → `POST /api/print` → 作业状态机：

| app job | 打印机 job | 结果 |
|---|---|---|
| #1 | 13 | **卡死**：`Create-Job + Send-Document` 被接受但设备永久 `processing`（0 页），后续作业全部 `server-error-busy` |
| #2 | 14 | ✅ `completed`，`job-impressions-completed: 1`（逐页 Print-Job） |
| #3 | 15 | ✅ `completed`，1 页，耗时约 76s（真实出纸时间） |

**修复**：
1. `service._send_pages()` 改为**逐页 `Print-Job`**，不再使用 `Create-Job + Send-Document`（本机固件会死锁）。
2. `ipp.wait_job()` 增加 `printer-state == idle` 兜底：设备在出纸完成后会把 `job-state` 挂在
   `5(processing)` 很久才置 `9`，仅靠 job-state 会让 UI 白等 1~2 分钟。
3. 另：`document-format` 必须是 **baseline JPEG（SOF0）**；progressive（SOF2）会被判
   `document-unprintable-error`。PyMuPDF 默认输出 progressive，必须过一遍 Pillow。

## 4. 扫描（eSCL）

`POST /api/scan` → 18 秒完成：
```
{"id":1,"format":"jpeg","width":2550,"height":3508,"size":178435,
 "path":"C:\Users\user\\Pictures\\HP Offline\\scan_20261024_213842.jpg","exists":true}
```
文件实际落盘 174 KB，A4 300dpi，可直接下载/预览（`/api/scans/1/file`、`/api/scans/1/thumb` 均 200）。

## 5. 维护 / 报告

`GET /api/printers/{id}/reports` → 15 种作业类型全部返回（`cleaningPage` … `webAccessReport`）。
`POST /api/printers/{id}/maintenance` 走 `POST /DevMgmt/InternalPrintDyn.xml`；
`configurationPage` 已实测 **201 + 真机出纸**。

## 6. 复印

`POST /Copy/Jobs` 在本机固件上 **45 秒超时无响应**（见 `protocol.md` §6 修正）。
→ 复印改由 `扫描 → 打印` 本地流水线实现，接口 `POST /api/copy`：

```
{"ok": true, "mode": "scan_then_print", "scan_job": 5, "print_job": 6, "scan_id": 2}
```
实测：扫描 20s 完成 → 自动提交打印作业 #6 → 设备正常出纸。全程离线。

前端入口：首页「复印」快捷卡（`app/ui/js/views/home.js` → `startCopy()` → `api.copy()`）。

## 7. 零云端

`GET /api/health` → `{"ok":true,"version":"1.0.0","cloud_calls":0}`

代码级审计（排除协议命名空间与本地地址）：
```
公网 URL 引用：0 处
```
仅有的 `http://` 出现位置：
- `server.py` 打印本地监听地址的日志
- `escl.py` 解析设备返回的 `Location` 头（指向打印机自身）

→ 不存在任何可访问公网的代码路径。

## 8. 前端

- 6 个视图文件齐全（home/print/scan/printer/history/settings）+ 组件库 + MD3 token
- 中文文案正确（OCR 核验：首页/打印/扫描/打印机/历史/设置、零云端 0 次公网请求、累计页数…）
- `level < 0` 分支存在：显示「墨仓式·无电子墨量，状态…」，不显示假百分比
- 静态资源可正常服务（`/` 200/5266B，`/js/views/home.js` 200/12933B）

> 说明：`docs/shot-*.png` 是前端 agent 用 `?mock=1` 渲染的示意图（含模拟墨量 72%/41%），
> 不代表真实设备数据。

---

# v1.2 增量（体验优化 + 云端功能本地化）

## A. 系统托盘（新增）

- `run.cmd` 启动服务后自动起托盘（`pythonw` 隐藏窗口 + `tray.ps1`），不再弹浏览器。
- 托盘图标 = `app/ui/favicon.ico`（与网页 favicon 同一套设计，256/128/64/48/32/24/16 多尺寸）。
- 右键 = **MD3 弹层**（自绘 Form，非 WinForms 默认菜单）：圆角 16、状态层悬停、图标 + 分组分隔线、
  顶部实时状态行（`打印机名 / 状态 · IP`）。
- 菜单项：打开界面 / 重新扫描打印机 / 打开日志 / 打开数据目录 / 重启服务 / 退出。
- 双击图标直接打开界面。

## B. 墨水卡（改进）

- 物理上只有 K + CMY 两个墨仓，界面按真实墨色拆成 **C / M / Y / K 四条**，
  颜色分别为 `#00A3E0` / `#E4007F` / `#FFC61A` / `#111317`。
- 标签前加同色圆点；墨仓背景带该色的 10% 底色。
- 设备不报百分比时（本机 `level=-1`）显示**斜纹半透明色块 + 状态文字**，不再是一片灰。

## C. 云端功能本地化（官方标称云端，本地实现）

| 功能 | 实现 | 验证 |
|---|---|---|
| 自动裁切 | 阈值求内容包围盒（Pillow/numpy） | 每次扫描默认开启 |
| 自动纠偏 | OpenCV 形态学 + 投影方差搜角（±6°，0.5° 步进） | 已接入扫描选项 |
| 自动增强 | fastNlMeansDenoising + autocontrast + UnsharpMask | 已接入 |
| PDF 密码保护 | PyMuPDF AES-256 + 权限位 | ✅ 实测 `needs_pass=1`，密码可解，A4 612×842pt，175KB |
| OCR / 可搜索 PDF | PaddleOCR 子进程 → 不可见文字层（`render_mode=3`） | ✅ 合成图识别出「HP Offline 离线打印控制台 / Invoice No. 2026-1025 / 总计金额 1,280.00 元」 |
| 身份证双面合并 / 多页拼版 | Pillow 合成（`compose_id_card` / `compose_nup`） | 代码就绪，需多页输入 |
| 本地快捷方式（替代 Smart Tasks） | `shortcuts` 表 + `/api/shortcuts/{id}/run`（save/email/print） | ✅ CRUD 实测通过 |
| 扫描后发邮件 | `smtplib` 直连用户 SMTP，AES 附件 | ✅ 未配置时正确返回 `smtp_not_configured` |

## D. 兼容性

- 前端 `API_ORIGIN` 改为 **同源推导**（`location.origin`），端口变了不用改代码。
- 后端端口被占用时**自动向后找空闲端口**（最多 +10），并写入 `app/data/port.txt`；
  `run.cmd` 从该文件读实际端口。
- 扫描仪忙（503/409）改为**退避重试最多 90 秒**，不再直接抛「扫描仪正忙」。
- 扫描请求**始终向设备要 JPEG**（后处理本地做），并对误返回 PDF 的情况加了栅格化兜底。

## E. 启动脚本（修复）

- `.cmd` 必须是 **CRLF** 换行，否则 cmd.exe 会把脚本拆成碎片执行（这正是之前「双击打不开」的原因）。
- `tray.ps1` 必须存为 **UTF-8 with BOM**，否则 PowerShell 5.1 按 GBK 解析，中文全角括号直接语法错误。
- 桌面 + 开始菜单快捷方式：`HP Offline.lnk` → `wscript start.vbs` → `run.cmd`（无窗口闪一下）。

---

# v1.3 修复：整页底色被刷成红色（严重耗材 bug）

## 现象
打印图片时，图片没有铺满 A4，**四周空白区域被打印成纯红**，等于每张纸都白烧一遍彩墨。

## 复现
```
transparent.png: 1240x1754 corner(4,4)=(254,0,0)  ← 红
small.jpg      : 1240x1754 corner(4,4)=(254,0,0)  ← 红
cmyk.jpg       : 1240x1754 corner(4,4)=(254,0,0)  ← 红
```
连一张普通白底 JPEG 的四角都是红的，说明问题不在源图，而在画布。

## 根因
```python
canvas = Image.new("RGB", (w, h), 255)   # ← 得到 (255, 0, 0) 纯红，不是白色！
```
Pillow 对 `RGB` 模式传**单个整数**时，并不是「三个通道都设成 255」，
而是被当成打包颜色值 → 只有 R 通道被点亮。
黑白路径更糟：`Image.new("L", (w, h), 0)` → **整页刷黑**。

## 修复
```python
canvas = Image.new("L" if monochrome else "RGB", (w, h),
                   (255,) if monochrome else (255, 255, 255))
```
同时补了透明图处理：带 alpha 的图（RGBA/LA/P+transparency）**先合成到白底**再转 RGB，
否则 `convert("RGB")` 会丢弃 alpha、把透明像素里残留的颜色（常见纯红）打出来。

## 验证
```
transparent.png: corner=(255,255,255) center=(0,120,255)   ✅
small.jpg      : corner=(255,255,255) center=(20,20,20)    ✅
cmyk.jpg       : corner=(255,255,255) center=(0,255,255)   ✅
灰度路径        : corner=(255,255,255) center=(20,20,20)    ✅
```

## 附带新增
- `render_pages(..., orientation="auto|portrait|landscape")`：横向打印会旋转 90° 并交换画布尺寸。
- `GET /api/print/thumb/{token}/{page}?orientation=&scale=&color=&media=&dpi=`：
  预览与真正送打走同一条渲染管线，所见即所打。
