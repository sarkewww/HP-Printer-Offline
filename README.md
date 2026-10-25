# HP Offline

> 把 HP Smart / HP 从「每点一下都要连 HP 服务器」变成「纯局域网、纯本地、秒响应」。

一个用 **Material Design 3** 重做的、**完全离线**的惠普打印机控制台。
不登录、不联网、不上传、不弹广告、不检查更新 —— 只跟局域网里那台打印机说话。

---

## 为什么要做这个

HP Smart（`AD2F1837.HPPrinterControl`）和新版 HP（`AD2F1837.myHP`）都是 Microsoft Store 应用，
但它们的**核心操作路径被设计成必须过 HP 云**：

| 操作 | 官方 App 实际行为 | 本应用 |
|---|---|---|
| 查看墨量 | 拉云端设备影子，失败就显示「无法获取」 | 直读 LEDM `/DevMgmt/ConsumableConfigDyn.xml` |
| 打印 | 先鉴权 → 云端下发指令 → 轮询结果 | 直接 `IPP Print-Job` 到 `:631` |
| 扫描 | 云端建任务 → 设备轮询 | 直接 `eSCL POST /eSCL/ScanJobs` |
| 维护/校准 | 云端指令中继 | 直接 `PUT/POST` LEDM 资源 |
| 打开 App | 先连 CDN 拉 UI、拉配置、拉 flag | 静态本地文件，0 请求 |

**关键事实**：现代 HP 打印机的本地协议**完全够用**——
IPP 打印、eSCL 扫描、LEDM 状态/耗材/维护/复印，一个不缺。
HP 云在这条链路上**没有提供任何打印机做不到的能力**，它只是中间商。

本仓库里的 `docs/cloud-deps.md` 记录了逆向官方 App 得到的云端依赖证据。

---

## 功能

- **打印机发现** — WS-Discovery 组播 / mDNS / SNMP / 子网扫描，四路并行；DHCP 换 IP 后自动重定位
- **首页** — 实时状态、耗材、能力徽章、快捷操作、最近作业、「零云端」计数器（恒为 0）
- **打印** — 拖拽 PDF / 图片，多页预览，份数 / 彩色 / 质量 / 纸张 / 缩放 / 页码范围
- **扫描** — 彩色 / 灰度 / 黑白，75–1200 dpi，JPEG / PDF，亮度对比度，自动裁切，预览与另存
- **打印机** — 设备信息、耗材明细、能力清单、维护动作、手动指定 IP
- **历史** — 打印与扫描作业记录，重新打印 / 删除
- **设置** — 主题、强调色、保存目录、自动发现、轮询间隔、默认打印机
- **零云** — 进程内统计所有对外请求，公网请求数永远显示 0

---

## 运行

```bat
:: 1) 装依赖（只有两个）
python -m pip install -r requirements.txt

:: 2) 双击运行
run.cmd
```

`run.cmd` 会：启动本地服务（`127.0.0.1:8791`）→ 等健康检查通过 → 用 Edge 的 `--app` 模式
开一个没有地址栏的独立窗口。停止用 `stop.cmd`。

也可以直接 `python app\server.py`，然后浏览器打开 `http://127.0.0.1:8791/`。

---

## 架构

```
app/
  server.py          # 标准库 ThreadingHTTPServer：/api/* + 静态文件 + SSE
  store.py           # SQLite：打印机、作业、扫描、设置
  hp/
    ipp.py           # IPP/2.0 客户端（RFC 8010 编解码，Print-Job/Get-Job/Cancel…）
    escl.py          # eSCL 扫描客户端（ScanJobs + NextDocument 退避重试）
    ledm.py          # LEDM 状态/耗材/用量/介质/维护
    discovery.py     # WS-Discovery + mDNS + SNMP + 子网扫描
    render.py        # PDF/图片 → 300dpi baseline JPEG 分页
    service.py       # 编排：状态缓存、作业线程、事件总线
  ui/                # MD3 前端（原生 ES modules，无构建、无 CDN）
docs/
  protocol.md        # ★ 全部实测协议细节（含踩过的坑）
  api.md             # 前后端契约
  spec-features.md   # 官方 App 功能对照（逆向结果）
  cloud-deps.md      # 官方 App 云端依赖证据
tools/               # 一次性探针脚本（ipp_probe / print_test / scan_test / wsd_probe）
```

依赖只有 `PyMuPDF`（PDF 渲染）和 `Pillow`（baseline JPEG 编码）。
HTTP、IPP、eSCL、LEDM、SSE、SQLite 全部用 Python 标准库手写。

---

## 协议要点（都是真机验证过的）

- **打印走 IPP**：`http://<ip>:631/ipp/print`，`document-format: image/jpeg`
- **必须 baseline JPEG（SOF0）**：progressive（SOF2）会被打印机直接判
  `document-unprintable-error`。PyMuPDF 默认输出 progressive，必须转一道 Pillow。
- **PDF 不能直传**：多数 HP 机型的 `document-format-supported` 里**没有** `application/pdf`。
- **扫描走 eSCL**：`POST /eSCL/ScanJobs` → `Location` → `GET .../NextDocument`，
  未就绪返回 503，需退避重试。
- **LEDM 在 80 端口**，不是 3911（3911 是 WSD 的 XAddrs，直接请求会 500）。
- **IPP 编码陷阱**：属性布局是 `tag | name-len | name | value-len | value`，
  值**不再带 tag**；多值属性才在后续每个值前重复 tag。多写一个字节 → 稳定 `0x0400`。
- **部分墨仓式机型不提供墨量百分比**：`marker-levels = -2`、`ConsumablePercentageLevelRemaining = 0`。
  UI 如实显示「墨仓式 · 无电子墨量」，**不编造数字**。
- **发现优先 WS-Discovery**：mDNS 常收不到回应、SNMP community 可能为空；
  WS-Discovery 实测最可靠。所有组播必须绑定局域网源地址（开了 Clash/TUN 之类的透明代理会劫持组播）。

完整记录见 `docs/protocol.md`。

---

## 已知限制

- 只做 **单面**（按设备 `sides-supported` 能力，家用机通常为 one-sided）
- 打印是**光栅化**路径：文字边缘有轻微 JPEG 痕迹。后续可接 PWG-Raster / PCLm 提升到矢量级
- 仅支持**平台式扫描**；带 ADF 的机型暂未适配
- 墨量百分比不可用（设备不上报，`marker-levels = -2`）
- **打印较慢**：整页 300dpi 光栅在墨仓式机型上约 60–90 秒，是真实出纸时间，不是软件卡顿
- **复印**不是设备原生：`POST /Copy/Jobs` 在部分机型固件上挂死无响应（见 `docs/protocol.md` §6），
  因此复印 = 「扫描 → 打印」本地流水线，多花几秒
- 打印时打印机的 Web 服务会短暂无响应，状态轮询偶发超时（已容忍，不影响出纸）
- 已在 HP 墨仓式机型上完成真机验证；其它 HP 机型理论上可用（协议通用），
  建议先用「打印测试页」确认；维护动作的可用性取决于机型暴露了哪些 LEDM 资源

真机验收记录见 `docs/acceptance.md`。

---

## 免责声明

本项目仅用于**控制你自己拥有的打印机**。所有协议都是打印机对外公开的标准
（IPP / eSCL / LEDM / WS-Discovery），不包含任何破解、绕过计费或规避耗材认证的行为。
逆向分析仅针对本地已安装的软件，目的是确认「哪些功能其实不需要云」。
请勿用于侵犯他人设备或违反当地法律。
