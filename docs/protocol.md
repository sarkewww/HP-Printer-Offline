# 协议实测记录（本机真实打印机验证）

实测设备：**HP Ink Tank Wireless 410 series**
- 主机名 `HPSERIAL` / `HPSERIAL.local`
- 序列号 `000000000010`，固件 `KEP1FN2020AR`，UUID `00000000-0000-0000-0000-000000000000`
- MAC `00:00:00:00:00:00`，当前 IP **192.168.1.100**（DHCP，会变！注册表里缓存的 192.168.1.100 已失效）
- 端口：80(EWS/LEDM/eSCL) 443 631(IPP) 3911(WSD XAddrs) 8080 9100 161 5353

> ⚠️ 本机装有 Clash/Meta TUN，`Find-NetRoute` 会把 192.168.10.x 也指向 198.18.0.1；
> 但实际 `/24` 直连路由存在，Python 直连 socket 可正常访问。发现逻辑必须
> **绑定本机局域网源地址**（`IP_MULTICAST_IF` / 源 IP 绑定），否则组播收不到回应。

## 1. 发现（WS-Discovery 实测最可靠）

UDP 组播 `239.255.255.250:3702`，SOAP `Probe`，8 秒内收到 `ProbeMatches`：

```xml
<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:wsd="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <soap:Header>
    <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>
    <wsa:MessageID>urn:uuid:{uuid4}</wsa:MessageID>
  </soap:Header>
  <soap:Body><wsd:Probe/></soap:Body>
</soap:Envelope>
```

回应中可用字段（正则/XML 解析均可）：
`dd:IPv4Address` `dd:Hostname` `dd:HardwareAddress` `dd:UUID`
`pwg:DeviceId`（`MFG:HP;MDL:Ink Tank Wireless 410 series;DES:Z4B53A;`）
`pwg:SerialNumber` `pwg:Services`（`Print9100 RESTScan DOT4 LEDM`）
`wsd:Types`（含 `wprt:PrintDeviceType wscn:ScanDeviceType`）

**mDNS 实测无响应**（本机被拦截或设备不广播）→ mDNS 仅作为兜底实现，不作为主路径。
**SNMP 161** 实测无响应（`NetAppsDyn` 写 `SNMP enabled` 但 community 为空）→ 兜底。
**子网扫描**（并发 TCP 探测 80/631/9100 + 拉 `/eSCL/ScannerStatus`）作为最后兜底，实测有效。

## 2. IPP（打印）— 端口 631，路径 `/ipp/print`

### ⚠️ 编码陷阱（踩过的坑）
IPP 属性布局是：`value-tag | name-length | name | value-length | value`
**值不带 tag**；只有「同名多值」时，后续每个值才重复一次 value-tag + 零长度 name。
（多写一个 tag 字节 → 打印机稳定返回 `0x0400 client-error-bad-request`，只回显 charset/lang。）

### 能力（Get-Printer-Attributes 实测）
```
printer-name            HPSERIAL
printer-info            HP Ink Tank Wireless 410 series [E0C183]
printer-state           3 = idle
printer-uri-supported   ipp://192.168.1.100/ipp/print , ipps://192.168.1.100:443/ipp/print
document-format-supported
    application/vnd.hp-PCL, image/jpeg, application/PCLm,
    image/urf, image/pwg-raster, application/octet-stream
sides-supported         one-sided        ← 不支持双面
print-color-mode-supported  auto, auto-monochrome, monochrome, color
printer-resolution-default  300x300 dpi
media-default           iso_a4_210x297mm
media-supported         iso_a4, na_letter, na_legal, na_executive, na_govt-letter, na_invoice,
                        iso_a5, iso_a6, iso_b5, iso_c5, iso_c6, iso_dl,
                        jis_b5, jpn_hagaki, jpn_chou3, jpn_chou4,
                        na_index-4x6, na_index-5x8, na_index-3x5, na_5x7, na_3x5,
                        na_monarch, na_number-10, na_a2, na_personal, na_foolscap,
                        oe_photo-l_3.5x5in, om_small-photo_100x150mm,
                        custom_min_3x5in, custom_max_8.5x14in
ipp-features-supported  airprint-1.7, ipp-everywhere
mopria-certified        1.3
operations-supported    2,4,8,57,9,10,11,5,6,19,3,7,59,60
marker-levels           -2 (-2 = 设备不报百分比)
printer-supply          tri-color ink / black ink，level=-2
printer-firmware-name   KEP1FN2020AR
```

### ✅ 打印可行的做法（已真机出纸）
- 操作：`Print-Job (0x0002)`，`document-format: image/jpeg`
- **必须是 baseline JPEG（SOF0）。progressive（SOF2）会被拒：
  `0x041B` + `job-state-reasons: document-unprintable-error`。**
  PyMuPDF 的 `pix.tobytes("jpeg")` 输出的是 **progressive**，不可直接用！
  必须 `pix → PIL.Image → save(progressive=False, optimize=False, dpi=(300,300))`。
- 页面按 300dpi 渲染成 A4（2480×3508）；600dpi 也可（4959×7017），但更慢。
- 多页：逐页 JPEG，用 `Create-Job(5)` + 多个 `Send-Document(6)`，或每页一个 Print-Job。
- job 属性：`copies` `media` `print-color-mode` `print-quality(3=draft,4=normal,5=best)`
- 提交后轮询 `Get-Job-Attributes(9)`：`job-state` 3=pending 4=pending-held 5=processing 6=stopped
  7=canceled 8=aborted 9=completed

## 3. eSCL（扫描）— 端口 80

- `GET /eSCL/ScannerStatus` → `<pwg:State>Idle|Processing</pwg:State>` + 任务列表
- `GET /eSCL/ScannerCapabilities` → 平台式(Platen)，最大 2550×3508@300dpi（光学 1200dpi）
  ColorMode: `BlackAndWhite1` `Grayscale8` `RGB24`
  DocumentFormat: `image/jpeg` `application/pdf` `application/octet-stream`
  Resolution: 75/100/200/300/600/1200
  Intent: `Document` `Photo` `Preview` `TextAndGraphic`
  Brightness/Contrast 0–2000（默认 1000），Threshold 0–255（默认 128）
- `POST /eSCL/ScanJobs`，`Content-Type: text/xml`，body 为 `scan:ScanSettings`
  → `201` + `Location: http://<ip>/eSCL/ScanJobs/<uuid>`
- `GET <Location>/NextDocument` → 图像字节（`Content-Type: image/jpeg`）
  未就绪时返回 `503`，需退避重试（实测约 3–8 秒出图）
- **`503` 也可能表示扫描仪忙**（上一任务未完成 / 正在打印）→ UI 要提示「设备忙，请稍候」

ScanSettings 模板（实测通过）：
```xml
<?xml version="1.0" encoding="UTF-8"?>
<scan:ScanSettings xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03"
                   xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
  <pwg:Version>2.6</pwg:Version>
  <pwg:ScanRegions><pwg:ScanRegion>
    <pwg:Height>3508</pwg:Height><pwg:Width>2550</pwg:Width>
    <pwg:XOffset>0</pwg:XOffset><pwg:YOffset>0</pwg:YOffset>
  </pwg:ScanRegion></pwg:ScanRegions>
  <pwg:InputSource>Platen</pwg:InputSource>
  <scan:ColorMode>RGB24</scan:ColorMode>
  <scan:XResolution>300</scan:XResolution>
  <scan:YResolution>300</scan:YResolution>
  <pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat>
  <scan:Intent>Document</scan:Intent>
</scan:ScanSettings>
```

## 4. LEDM（状态 / 耗材 / 维护）— 端口 80

已实测可用的 GET 端点（全部 200）：
```
/DevMgmt/ProductStatusDyn.xml     ← 状态 + 告警表（scanProcessing / idle …）
/DevMgmt/ConsumableConfigDyn.xml  ← 墨盒信息（ConsumableLabelCode: CMY / K）
/DevMgmt/ProductConfigDyn.xml     ← 型号、序列号、固件、区域
/DevMgmt/ProductUsageDyn.xml      ← 打印/扫描页数计数器
/DevMgmt/MediaHandlingDyn.xml     ← 纸盒 / 就绪纸张
/DevMgmt/PrintConfigDyn.xml       ← 打印默认设置
/DevMgmt/NetAppsDyn.xml           ← 网络配置（mDNS/SNMP/9100/IPP 开关）
/DevMgmt/DiscoveryTree.xml        ← 能力清单（列出全部支持的 LEDM/eSCL 资源）
/DevMgmt/ProductStatusCap.xml /ProductConfigCap.xml /ConsumableConfigCap.xml /MediaHandlingCap.xml
/DevMgmt/MediaDyn.xml /DevMgmt/SecurityDyn.xml /DevMgmt/ProductLogsDyn.xml
```
- 端口 **3911 不是** LEDM（返回 500）；**必须用 80**。
- EWS 根路径 `/` 返回 **gzip** HTML，需按 `Content-Encoding` 解压。
- 耗材百分比：本机 `ConsumablePercentageLevelRemaining = 0` 且 IPP `marker-levels = -2`
  → **设备不提供墨量百分比**。UI 必须优雅降级（显示「墨仓式，无电子墨量」+ 墨盒状态文字）。
- 维护动作（清洗/对齐/校准）通过 `PUT/POST` 对应 `*Dyn.xml` 资源实现，
  具体路径需按 `DiscoveryTree` 的 `SupportedIfc` 清单探测（`/ProductActions/ProductActionsManifest.xml`
  `/Calibration/CalibrationManifest.xml` `/Utilities/UtilitiesManifest.xml`）。

## 5. 打印数据格式选择结论

| 格式 | 可行性 | 结论 |
|---|---|---|
| `application/pdf` | ❌ 打印机不支持 | 不能用 |
| `image/jpeg` | ✅ 已验证出纸 | **主路径**（必须 baseline） |
| `image/pwg-raster` | 支持但未实现 | 后续可选（无损，需 1796 字节 PWG 头） |
| `image/urf` | 支持但未实现 | 后续可选 |
| `application/PCLm` | 支持但未实现 | 后续可选（矢量清晰度最好） |
| `application/vnd.hp-PCL` | 需生成 PCL3GUI | 放弃 |

→ 首版用 JPEG 300dpi，文字会有轻微压缩痕迹；`quality=92` 时 A4 单页约 200–400 KiB，可接受。

## 6. 复印（原生，无需 PC 参与）— 实测能力

`/Copy/CopyJobCap.xml` 表明设备支持**独立复印作业**（PC 只发指令，扫描+打印全在设备内完成）：

- `POST /Copy/Jobs`，`Content-Type: text/xml`，body 为 `cpjob:CopyJob`
- `GET/PUT /Copy/CopyConfigDyn.xml` — 读取/设置复印默认值
- 可用参数（实测 cap）：
  - `NumberOfCopies` 1–9
  - `MediaSizeName`（29 种，含 iso_a4 / na_letter / na_index-4x6 / om_small-photo_100x150mm …）
  - `MediaType` plain | photoStandard | specialtyGlossy | specialtyMatte
  - `ReduceEnlarge` original | fitToPage | custom（custom 25–400%）
  - `CopyQuality` best | normal
  - `OutputType` monochrome | color
  - `MarginOff` enabled | disabled（无边距）
  - `LighterDarker` −4…+4
  - `CopySides` simplexToSimplex（仅单面）
  - `TraySelect` Tray1

→ 建议作为 v1.1 的「复印」页：UI 只发一个 XML，出纸速度比「扫描→PC→打印」快一个数量级。

### ⚠️ 实测结果（2026-10-25 修正）
`POST /Copy/Jobs`（按 `CopyJobCap` 的元素名构造 `cpjob:CopyJob`）在本机固件 **KEP1FN2020AR** 上
**连接被接受但永不响应，45 秒超时（curl HTTP 000）**；同一时刻 `/DevMgmt/ProductStatusDyn.xml` 正常 200，
说明不是设备整体无响应，而是该端点在本机型未实现（能力表里有、实现缺失）。
设备上也没有暴露 CopyJob 的 XSD（`/schemas/CopyJob.xsd` 等全部 404）可供对照。

→ **结论：本机不做原生复印。** 复印功能改用已验证的本地流水线：
`eSCL 扫描（300dpi JPEG） → IPP Print-Job（baseline JPEG）`，全程离线，仅多花几秒。
UI 文案需注明「复印 = 先扫描再打印，约 X 秒」。

## 7. 维护 / 产品动作

`/ProductActions/ProductActionsManifest.xml`：
```
PUT /FactoryDefaults        （需 SecureAccess）
PUT /PowerCycle             （需 SecureAccess）
PUT /DirtyPowerCycle        （需 SecureAccess）
PUT /ResetOnNextBoot        （需 SecureAccess）
GET /ProductActionsCap.xml  （本机返回空/404 → 该机型未暴露 cap）
```
`/Calibration/CalibrationManifest.xml`：
```
GET  /Calibration/State
POST /Calibration/Session            → 创建会话
GET  /Calibration/Session/{id}
PUT  /Calibration/Session/{id}       → 推进校准步骤
```
`/Utilities/ICCStatus` 实测返回的是 **Internet Connection Check**（联网自检）状态，
**不是**打印头维护：
```xml
<ut:State>checkCompleted</ut:State>
<ut:ErrorDetails><ut:Type>connected</ut:Type></ut:ErrorDetails>
```

### ★ 真正的「清洗打印头 / 打印报告」= 内部打印（真机已验证）
`GET /DevMgmt/InternalPrintCap.xml` → `JobTypesSupport`（本机 15 种）：
`cleaningPage` `cleaningPageLevel2` `cleaningVerificationPage` `configurationPage`
`extendedConfigurationPage` `demoPage` `diagnosticsPage` `pqDiagnosticsPage`
`networkSummary` `networkDiagnosticPage` `wirelessNetworkPage`
`paperFeedCleaningPage` `ribSmearCleaningPage` `eventLogReport` `webAccessReport`

触发（**只写资源**：GET=404，PUT=405，**必须 POST**）：
```
POST http://<ip>/DevMgmt/InternalPrintDyn.xml   Content-Type: text/xml
<ipdyn:InternalPrintDyn
  xmlns:ipdyn="http://www.hp.com/schemas/imaging/con/ledm/internalprintdyn/2008/03/21"
  xmlns:dd="http://www.hp.com/schemas/imaging/con/dictionaries/1.0/">
  <dd:Version><dd:Revision>1.0</dd:Revision></dd:Version>
  <ipdyn:JobType>configurationPage</ipdyn:JobType>
</ipdyn:InternalPrintDyn>
```
→ `201 Created`，`ProductStatusDyn` 转 `processing`，真机出纸（实测）。

`/Jobs/JobsManifest.xml` → 设备端作业队列查询/控制。
`/Utilities/ICCJob`（POST）/`/Utilities/ICCStatus`（GET）→ 联网自检，与打印头无关。

**注意**：本机型**没有** `/ProductActions/CleanPrintheads` 端点。
「清洗打印头」= `InternalPrintDyn` + `cleaningPage`，完全本地、无需 EWS、无需云。
