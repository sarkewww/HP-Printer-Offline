# HP Offline — 前后端 API 契约

所有接口均为 `http://127.0.0.1:8791/api/*`，`Content-Type: application/json`（上传除外）。
错误统一返回 `{"error": "<code>", "message": "<中文可读信息>"}` + 对应 HTTP 状态码。

## 1. 打印机发现与注册

### `GET /api/printers`
返回已保存打印机 + 实时状态摘要（不阻塞，读缓存；缓存过期由前端触发 refresh）。

```json
{
  "printers": [{
    "id": "00000000-0000-0000-0000-000000000000",
    "name": "HP Ink Tank Wireless 410 series",
    "queue_name": "HPSERIAL",
    "model": "Ink Tank Wireless 410 series",
    "host": "192.168.1.100",
    "serial": "000000000010",
    "firmware": "KEP1FN2020AR",
    "online": true,
    "state": "idle",
    "state_reason": "",
    "is_default": true,
    "last_seen": 1761300000
  }]
}
```

`state` ∈ `idle | processing | stopped | offline | unknown`

### `POST /api/printers/discover`
主动扫描局域网，返回**本次发现**的设备（不自动保存）。

```json
{ "found": [ { "host": "...", "model": "...", "serial": "...", "uuid": "...", "source": "wsd|mdns|snmp|scan" } ] }
```

### `POST /api/printers`
```json
{ "host": "192.168.1.100" }        // 手动添加，后端自动探测能力
```

### `DELETE /api/printers/{id}`

### `POST /api/printers/{id}/default`

## 2. 状态 / 耗材 / 维护

### `GET /api/printers/{id}/status?refresh=1`
```json
{
  "id": "...",
  "online": true,
  "state": "idle",
  "state_message": "就绪",
  "alerts": [ { "category": "supplyLow", "message": "黑色墨水量低" } ],
  "supplies": [
    { "key": "black", "label": "黑色墨水", "color": "#000000", "level": 72, "state": "ok", "kind": "ink" },
    { "key": "color", "label": "三色墨水", "color": "#00A0E9", "level": 41, "state": "low", "kind": "ink" }
  ],
  "media": { "ready": "iso_a4_210x297mm", "tray": "InputTray1" },
  "counters": { "total_pages": 1203, "scan_pages": 88, "jam_events": 0 },
  "capabilities": {
    "color": true,
    "duplex": false,
    "scan": true,
    "adf": false,
    "max_scan_dpi": 1200,
    "scan_color_modes": ["BlackAndWhite1", "Grayscale8", "RGB24"],
    "scan_formats": ["image/jpeg", "application/pdf"],
    "media": ["iso_a4_210x297mm", "na_letter_8.5x11in", "na_index-4x6", "oe_photo-l_3.5x5in"]
  }
}
```
`supplies[].level`: 0–100 整数；`-1` 表示设备不提供百分比（本机墨仓式返回 `-1` 时前端显示「未知」并在 UI 上改用「墨量估算不可用」文案）。

### `POST /api/printers/{id}/maintenance`
```json
{ "action": "clean|clean_deep|clean_verify|report|diagnose|network_report" }
```
后端映射到 **`POST /DevMgmt/InternalPrintDyn.xml`**（`JobType`，真机已验证 201 + 出纸）：

| action | JobType |
|---|---|
| `clean` | `cleaningPage` |
| `clean_deep` | `cleaningPageLevel2` |
| `clean_verify` | `cleaningVerificationPage` |
| `report` | `configurationPage` |
| `report_ext` | `extendedConfigurationPage` |
| `diagnose` | `pqDiagnosticsPage` |
| `network_report` | `networkSummary` |
| `network_diagnose` | `networkDiagnosticPage` |
| `wireless_report` | `wirelessNetworkPage` |
| `feed_clean` | `paperFeedCleaningPage` |
| `smear_clean` | `ribSmearCleaningPage` |
| `demo` | `demoPage` |
| `event_log` | `eventLogReport` |

返回 `{"ok": true, "job_type": "cleaningPage"}`。

### `GET /api/printers/{id}/reports`
返回该机型实际支持的报告/维护类型（读 `/DevMgmt/InternalPrintCap.xml` 的 `JobTypesSupport`），
用于 UI 只渲染真实存在的按钮：
```json
{ "job_types": ["cleaningPage", "cleaningPageLevel2", "configurationPage", "pqDiagnosticsPage", "networkSummary", "..."] }
```

## 3.5 复印（设备原生，PC 不参与）

### `POST /api/copy`
```json
{
  "printer_id": "...",
  "options": {
    "copies": 1,
    "color": "color|monochrome",
    "media": "iso_a4_210x297mm",
    "media_type": "plain|photoStandard|specialtyGlossy|specialtyMatte",
    "quality": "normal|best",
    "reduce_enlarge": "original|fitToPage|custom",
    "scale": 100,
    "borderless": true,
    "lighter_darker": 0
  }
}
```
→ `{"ok": true}`；后端 `POST /Copy/Jobs`（LEDM），扫描与打印全部在设备内完成，
**不经过 PC 的光栅化**，速度远快于「扫描→PC→打印」。

## 3. 打印

### `POST /api/print/upload`  (multipart/form-data, 字段名 `files`, 可多个)
返回上传后的临时文件描述：
```json
{ "files": [ { "token": "u_8f3a", "name": "报告.pdf", "kind": "pdf", "pages": 3, "size": 812345,
               "thumbs": ["/api/print/thumb/u_8f3a/0", "/api/print/thumb/u_8f3a/1"] } ] }
```

### `GET /api/print/thumb/{token}/{page}` → image/png

### `POST /api/print`
```json
{
  "printer_id": "...",
  "files": ["u_8f3a"],
  "options": {
    "copies": 1,
    "color": "auto|color|monochrome",
    "quality": "draft|normal|best",
    "dpi": 300,
    "media": "iso_a4_210x297mm",
    "scale": "fit|fill|actual",
    "pages": "all|1-3,5"
  }
}
```
→ `{ "job_id": 12 }`，立即返回，后台线程执行。

### `GET /api/jobs/{id}`
```json
{ "id": 12, "kind": "print", "printer_id": "...", "title": "报告.pdf",
  "state": "queued|preparing|sending|printing|done|error|canceled",
  "progress": 0.42, "pages_total": 3, "pages_sent": 1,
  "message": "正在发送第 2/3 页", "error": null, "created_at": 1761300000 }
```

### `POST /api/jobs/{id}/cancel`

### `GET /api/jobs?limit=50&kind=print|scan`

## 4. 扫描

### `POST /api/scan`
```json
{
  "printer_id": "...",
  "options": {
    "color_mode": "RGB24|Grayscale8|BlackAndWhite1",
    "dpi": 300,
    "format": "jpeg|pdf",
    "region": { "width": 2550, "height": 3508, "x": 0, "y": 0 },
    "intent": "Document|Photo|TextAndGraphic",
    "brightness": 1000,
    "contrast": 1000,
    "auto_crop": true
  }
}
```
→ `{ "job_id": 13 }`

### `GET /api/scans?limit=50`
```json
{ "scans": [ { "id": 7, "job_id": 13, "printer_id": "...", "format": "jpeg",
               "path": "C:\\Users\\...\\Pictures\\HP Offline\\scan_20261024_175512.jpg",
               "thumb": "/api/scans/7/thumb", "width": 2480, "height": 3508,
               "size": 1675423, "created_at": 1761300000 } ] }
```

### `GET /api/scans/{id}/file` → 原始文件
### `GET /api/scans/{id}/thumb` → image/png
### `DELETE /api/scans/{id}`

## 5. 设置

### `GET /api/settings`
```json
{
  "theme": "light|dark|system",
  "accent": "#0096D6",
  "language": "zh-CN",
  "save_dir": "C:\Users\user\\Pictures\\HP Offline",
  "auto_discover": true,
  "poll_interval": 10,
  "default_printer": "...",
  "offline_mode": true
}
```

### `PATCH /api/settings` — 部分更新，返回完整设置

## 6. 系统

### `GET /api/health`
```json
{ "ok": true, "version": "1.0.0", "python": "3.10.11", "cloud_calls": 0 }
```
`cloud_calls` 恒为 0 —— 本应用**不发起任何公网请求**，前端会展示这个数字作为「零云端」证明。

### `GET /api/events` (SSE)
`text/event-stream`，事件：`job`（任务进度）、`printer`（状态变化）。
用于前端实时刷新，无需轮询。
