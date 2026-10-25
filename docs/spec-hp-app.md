# HP 应用（myHP）功能规格 — 逆向还原基准

来源：
1. `Config/webapps_prod/manifest.json` 的 `routes`（权威路由表）
2. `Weblets/webapps/root-web-mfe/**/assets/locale/zh_CN.json`（官方中文文案）
3. `HP.HPX.dll` 方法名与端点字符串（`docs/re-bin/analysis.md`）
4. 真机运行截图（`docs/ui-ref/hp-0*.png`）
5. 真机协议实测（`docs/protocol.md`）

> HP Smart（`HPPrinterControl`）已确认**于 1 月 15 日停止服务**，官方在应用内弹窗强制迁移到本应用。
> 因此还原基准 = 本应用（myHP / `HP.HPX.exe`）。

---

## 1. 应用本质

`HP` 不是打印机工具，而是**HP 设备中心**：打印机 + HP 笔记本硬件（音频/电池/键盘/鼠标/触控板/笔/屏幕/手势…）+ 商店 + 账号。
路由表里约 80 条路由，**与打印机相关的只有 17 条**，其余 `pc*` / `pencontrol*` / `gestures*` 全部是 PC 硬件控制，与打印无关。

克隆只做打印机部分——这正是用户要的。

---

## 2. 打印机相关路由（权威）

| 路由 | 页面 | 微前端 | 云端依赖 | 克隆 |
|---|---|---|---|---|
| `/devices` | 我的设备（设备列表） | react-devices-mfe | 列表本地，订单跟踪走云 | ✅ 做 |
| `/devicedetailsdefault` | **设备详情（主页面）** | react-devicedetails-default-mfe | 本地 | ✅ 核心 |
| `/adddevice`、`/addDevice` | 添加设备（OOBE） | react-adddevice-mfe | 发现本地，注册走云 | ⚠️ 简化为「手动 IP / 自动发现」 |
| `/print` | 打印入口 | react-print-mfe | 本地 | ✅ 做 |
| `/print-documents` | 打印文档 | react-print-documents-mfe | 本地 | ✅ 做 |
| `/print-photos` | 打印照片 | react-print-photos-mfe | 本地 | ✅ 做 |
| `/print-scan-home` | **扫描** | react-print-scan-home-mfe | 本地 | ✅ 核心 |
| `/print-scan-results` | **扫描结果** | react-print-scan-results-mfe | 基本 PDF/JPEG 本地；OCR/可搜索 PDF/Word **标称云端** | ✅ 做（本地 PDF/JPEG；OCR 见 v1.2） |
| `/print-scan-edit` | 扫描编辑 | react-print-scan-edit-mfe | 本地 | ✅ 做 |
| `/print-scan-detect-edge` | 边缘检测/裁切 | react-print-scan-detect-edge-mfe | 本地 | ✅ 做 |
| `/app.printer.connected-remotely` | 远程连接说明 / 连接故障引导 | react-print-printerinfo-mfe | 本地文案 | ✅ 做（故障引导） |
| `/print-shortcuts` | 快捷方式（Smart Tasks 继任） | react-print-shortcuts-mfe | **云端执行** | ❌ 放弃（改本地「一键动作」预设） |
| `/print-mobilefax` | 移动传真 | react-print-mobilefax-mfe | **云端** | ❌ 放弃 |
| `/print-wechat` | 微信打印 | react-print-wechat-mfe | **云端** | ❌ 放弃 |
| `/print-cloud-scan-valueprop` | 云扫描推广页 | react-websolution-uto-valueprop-mfe | 营销页 | ❌ 放弃 |
| `/print-install-driver` | 驱动安装 | react-print-driver-install-mfe | 需下载 | ❌ 放弃 |
| `/print-psamigration` | PSDr 迁移 | solution-hpx-react-print_psamigration-mfe | 云 | ❌ 放弃 |
| `/settings` | 设置 | react-settings-mfe | 本地 + 隐私云 | ✅ 做（只保留本地项） |
| `/notifications` | 通知中心 | react-bell-notifications-mfe | 云推送 | ⚠️ 改为本地作业/设备通知 |
| `/support` | 支持 | react-support-mfe | 云 | ⚠️ 改为本地诊断 |
| `/shop` | 商店/耗材 | react-foryou-mfe | **云** | ❌ 放弃（保留「耗材型号」信息） |

**被官方遗漏但设备支持、克隆必须补的**（见 `docs/protocol.md` §6/§7）：
- **复印** `POST /Copy/Jobs`（设备内完成，官方本应用没有入口）
- **清洗打印头 / 打印报告** `POST /DevMgmt/InternalPrintDyn.xml`（15 种 JobType）

---

## 3. 设备详情页（主页面）真实结构

截图：`docs/ui-ref/hp-01.png`（上）、`hp-02-scan.png`（下）

```
┌ 顶栏 ──────────────────────────────────────────────┐
│ ←返回      [🖨 打印队列] [🛍 商店]      🔔  👤  [登录] │
├ 主视觉 ────────────────────────────────────────────┤
│ HPSERIAL (Ink Tank Wireless 410 series)   ← 56px 粗体 │
│ HP Ink Tank Wireless 410 series           ← 蓝色副标题│
│ ┌墨量卡┐                                            │
│ │C M Y K 四条竖条│            [打印机插画]            │
│ │估计耗材余量    │                                   │
│ └──────┘                                            │
├ 动作网格（2 列）────────────────────────────────────┤
│ [获取耗材 / HP 原装墨水]   [扫描 / 使用打印机扫描文件。]│
│ [打印 PDF 文件 / 编辑、打印…] [打印照片 / 编辑、保存…] │
│ [移动传真 / 从此设备发送安全传真] [快捷方式 / 加快重复任务]│
│ [打印仪表板 / 管理功能、耗材和用户]                    │
├ 获取帮助（大卡）────────────────────────────────────┤
│ 请使用智能助手来协助解决问题，或者选择其他支持选项。      │
│ [启动惠普智能助手]         ♡ 联系我们 →                │
├ 诊断 ──────────────────────────────────────────────┤
└────────────────────────────────────────────────────┘
```

要点：
- 背景是**淡紫灰**（约 `#E9E7F1`），卡片纯白、圆角约 24px、几乎无阴影
- 标题**极大**（约 56px），两行，深墨色
- 副标题蓝色（约 `#4B4BFF` / 靛蓝）
- 墨量卡：4 条竖条（青/品红/黄/黑），下方 C M Y K 字母，底部小字「估计耗材余量」
  → **本机不报百分比，官方仍画满格条**（这是它的缺陷，我们不照抄，改为「墨仓式·无电子墨量」）
- 图标风格：淡紫/淡蓝渐变填充的扁平插画图标

---

## 4. 扫描页真实结构

截图：`docs/ui-ref/hp-06-scan.png`

```
┌ 左：预览画布（占 ~2/3）──────────┐ ┌ 右：设置面板（白卡）──────┐
│                                  │ │ ⚙  🪄  （两个图标按钮）    │
│  将内容添加到扫描仪并选择扫描，     │ │ ───────────────────── │
│  或者 导入文件。                  │ │ 来源      扫描仪玻璃板  ▾ │
│                                  │ │ ☑ 检测边缘              │
│                                  │ │ 预设值    照片        ▾ │
│                                  │ │ 扫描区域  整个扫描区域 ▾ │
│                                  │ │ 输出      彩色        ▾ │
│                                  │ │ 分辨率    600 dpi     ▾ │
│                                  │ │        重置设置          │
│ 扫描后取出文档原件。将文档原件留在   │ │                        │
│ 扫描仪上可能导致网络上的任何人都可以 │ │ [🔍 预览]               │
│ 访问该文档原件。                   │ │ [⧉ 扫描]               │
└──────────────────────────────────┘ └────────────────────────┘
```
默认值（实测）：来源=扫描仪玻璃板，检测边缘=开，预设值=照片，扫描区域=整个扫描区域，
输出=彩色，分辨率=**600 dpi**（注意：官方默认 600，比我们 API 默认 300 高）。

官方扫描设置全集（来自 zh_CN 文案）：
- 来源：文档进纸器 / 扫描仪玻璃板
- 高级预设：文档 / 照片 / 多项 / 书本 / 身份证
- 页面尺寸：4×6 / 5×7 / A4 / Legal / Letter / 整个扫描区域
- 输出：彩色 / 灰度 /（黑白）
- 分辨率：75 / 150 / 300 / 600 / 1200
- 压缩：无 / 低 / 中 / 高
- 自动增强 / 自动定向 / 自动修复
- 身份证：正反面合并到一页

扫描结果页（`/print-scan-results`）动作：编辑、修订、涂鸦、文本提取、旋转、删除、
全选、打印、保存、共享、更换、快捷方式、传真；文件类型：基本 PDF、图像(*.jpg)、
可搜索 PDF、纯文本(*.txt)、Word(*.docx)；另有压缩、文档语言、智能文件名、密码保护。

---

## 5. 状态文案（官方原文，直接复用）

`react-device-statuses-mfe`：
- `cloudConnected` 云已连接 / `offline` 未连接。获取连接帮助 / `usbConnected` USB 已连接
- `setupIncomplete` 设置未完成。请完成打印机设置 / `connectPrinter` 连接此打印机以使用所有功能

`react-supply-levels-mfe`：
- `estimated-supply-levels` 估计耗材余量 / `last-updated` 上次更新日期：{{date}}
- `supply-level-is-approximately` {{supplyName}}耗材余量约为 {{level}}%
- `supply-level-is-low` 耗材余量不足 / `supply-level-is-very-low` 严重不足 / `supply-depleted` 已耗尽
- `supply-status-unknown` {{supplyName}}耗材状态未知  ← **本机用这一条**
- `tricolor-supply-*` 三色耗材系列

`react-print-printerinfo-mfe`（连接故障引导，可直接复用文案）：
检查打印机 → 检查网络连接 → 重新启动路由器和打印机 → 诊断和修复

---

## 6. 克隆的最终功能集（决定版）

### 必做（本地可达）
1. 设备详情页：型号/状态/耗材/能力 + 8 个动作卡
2. 打印文档（PDF/图片，多页预览，份数/彩色/质量/纸张/缩放/页范围）
3. 打印照片（1×1、2×2 拼版可选）
4. 扫描（来源/预设/区域/输出/分辨率/压缩/自动增强/边缘检测/身份证双面）
5. 扫描结果（预览、旋转、裁切、保存 JPEG/PDF、多页 PDF、分享到文件夹）
6. **复印**（设备原生，官方没有）
7. **维护**：清洗打印头（一级/深度）、清洗验证页、配置页、诊断页、网络报告
8. 设备信息与网络信息（只读）
9. 作业历史（打印/扫描/复印）+ 重新打印
10. 设置（主题/保存目录/自动发现/轮询间隔/默认打印机）
11. 连接故障引导（复用官方三步文案）

### 明确放弃（云）
快捷方式、移动传真、微信打印、商店、账号登录、云扫描推广、驱动安装、PSDr 迁移、
固件在线更新、OCR 云端文件类型（v1.2 用本地引擎替代）

### 明确不做（PC 硬件，与本项目无关）
`pcaudio` `pcbattery` `pckeyboard` `pcmouse` `pctouchpad` `pencontrol` `gestures`
`internaldisplay` `pcscreentime` `pcwellbeing` `pcsmartscreen` `dynamicwallpaper` …
