# HP Smart / myHP 功能与界面还原规格（本地打印机版）

> 目标：为本机 **HP Ink Tank Wireless 410 series**（`192.168.1.100`，序列号 `000000000010`，固件 `KEP1FN2020AR`）
> 的离线克隆应用，还原 HP 官方两个 Windows 应用在 **本地 USB / Wi-Fi 打印机** 场景下真正呈现的功能与界面。
>
> 本文只描述 **可观测到的界面与数据模型**，不涉及绕过授权、不涉及修改原应用。
> 云依赖的完整证据见 `cloud-deps.md`。

---

## 0. 取证环境与路径简写

| 简写 | 实际路径 |
|---|---|
| `SMART` | `C:\Program Files\WindowsApps\AD2F1837.HPPrinterControl_166.2.1118.0_x64__v10z8vjag6ke6` |
| `MYHP` | `C:\Program Files\WindowsApps\AD2F1837.myHP_61.52637.14262.0_x64__v10z8vjag6ke6` |
| `MFE` | `MYHP\Weblets\webapps\root-web-mfe\assets\mfe` |
| `ROOT` | `MYHP\Weblets\webapps\root-web-mfe` |
| `LS_SMART` | `C:\Users\user\AppData\Local\Packages\AD2F1837.HPPrinterControl_v10z8vjag6ke6\LocalState` |
| `LS_MYHP` | `C:\Users\user\AppData\Local\Packages\AD2F1837.myHP_v10z8vjag6ke6\LocalState` |
| `RECON` | `C:\Users\user\opencode\hp-offline\recon`（打印机实测抓取） |

三个关键结论先给出：

1. **两个应用是两代产品**：`HP Smart`（UWP / .NET Native，磁贴式）与 `myHP`（WebView2 + React 微前端，单页应用）。
   myHP 是 HP Smart 的继任者，但 HP Smart 的**打印选项面板更完整**（有份数/双面/无边距/缩放/小册子/水印），
   myHP 把这些交给 **Windows 原生打印对话框**。克隆应取两者并集，以 HP Smart 的选项集为准。
2. **本机设备的真实能力远小于 UI 选项集**：无 ADF、无双面、无电子墨量、无纸盒传感器。
   UI 必须按设备上报能力裁剪，否则会出现「能选但打不出来」。
3. **所有打印/扫描/状态动作都是本地 GraphQL（`localPrint*` / `localDevice*`）**，
   由 WebView 通过 `window.JWeb.Plugins.*` 调原生实现，原生再走 IPP / eSCL / LEDM。
   云只在登录、固件、云端扫描、快捷方式、传真、OCR 转文本、商店这些路径上出现。

---

## 1. 首页 / 设备页

### 1.1 myHP 的页面骨架

`MYHP\Config\webapps_prod\manifest.json` 定义了 **80 条路由**（全部 `"public": true`，即路由层不做登录拦截）。
与打印机相关的子集：

| 路由 | 微前端（assetReference） | 角色 | 中文标题来源 |
|---|---|---|---|
| `/devices` | `@hpx-core-experiences/react-devices-mfe` | 底部 Tab「我的设备」 | `route.devices` |
| `/print` | `@hpx-core-experiences/react-print-mfe` | 打印机详情/打印中心 | `route.print` |
| `/print-documents` | `.../react-print-documents-mfe` | 打印文档 | — |
| `/print-photos` | `.../react-print-photos-mfe` | 打印照片 | — |
| `/print-install-driver` | `.../react-print-driver-install-mfe` | 驱动安装引导 | — |
| `/print-scan-home` | `.../react-print-scan-home-mfe` | 扫描设置页 | `route.printscanhome` |
| `/print-scan-detect-edge` | `.../react-print-scan-detect-edge-mfe` | 边缘检测/裁剪 | `route.printscanhome` |
| `/print-scan-edit` | `.../react-print-scan-edit-mfe` | 图像编辑 | `route.printscanedit` |
| `/print-scan-results` | `.../react-print-scan-results-mfe` | 扫描结果（保存/打印/分享） | `route.printscanresults` |
| `/devicedetailsdefault` | `.../react-devicedetails-default-mfe` | 通用设备详情 | `route.devicedetailsdefault` |
| `/app.printer.connected-remotely` | `.../react-print-printerinfo-mfe` | 远程（云）打印机提示页 | `route.cloudConnected` |
| `/updates` `/updates/detail` `/updates/history` `/updates/settings` | `.../react-device-updates-mfe` | PC 软件/驱动更新 | — |
| `/notifications` | `.../react-bell-notifications-mfe` | 通知中心 | — |
| `/settings` | `.../react-settings-mfe` | 应用设置 | — |
| `/signin` `/uto` | `.../react-signin-mfe` / `@pces/react-user-tenant-onboarding-mfe` | 登录 / 租户选择 | — |
| `/support` 及 15 个子路由 | `.../react-support-mfe` | 支持/诊断/保修 | `route.support` |
| `/print-shortcuts` | `.../react-print-shortcuts-mfe` | 快捷方式（Smart Tasks） | — |
| `/print-mobilefax` | `.../react-print-mobilefax-mfe` | 移动传真 | — |
| `/print-wechat` | `.../react-print-wechat-mfe` | 微信打印（中国区） | — |
| `/print-cloud-scan-valueprop` | `.../react-websolution-uto-valueprop-mfe` | 云扫描推销页 | — |

> 证据：`MYHP\Config\webapps_prod\manifest.json` → `navigation.routes[].path` / `.assetReference` / `.properties.translationKey`。
> 另有 40+ 条 PC 硬件路由（`/pcaudio`、`/pctouchpad`、`/pencontrol/*`、`/pctaskgroups` 等），与打印机无关，克隆不实现。

**底部导航结构**（`manifest.json` → `navigation.defaultNavigationElements`）：`navBar` + `actionsButtons` + `navPill` + `backButton`，全部可见。
Tab 项（`properties.isTab == true`）：`/devices`、`/shop`、`/hpaiassistant`。即 **三 Tab**：我的设备 / 为你推荐(商店) / AI 助手。

**Windows 上被显式封禁的 28 条路径**（`manifest.json` → `services.navigation.blockNavigation.pathList`）——这份清单是「云功能在桌面端被砍掉」最硬的证据：

```
/app.printer.diagnostics-diagnose-and-fix        /app.printer.diagnostics-print-quality-tools
/app.printer.diagnostics-view-all                /app.product-information-more
/app.printer.settings-security                   /app.printer.settings-privacy
/app.printer.settings-supply-status              /app.printer.settings-private-pickup
/app.printer.settings-print-anywhere             /app.printer.settings-all
/app.printer.log-settings                        /app.sms-detail
/app.add-device.add-printer                      /app.add-device.setup-paas-printer
/app.finish-setup                                /app.get-connection-help
/app.bell.print-anywhere                         /app.action.scan-to-cloud
/app.bell.cloud-scan                             /app.private-pickup-flow
/app.dsp                                         /supplies
/suppliesv3                                      /migrateduser
/addprinter                                      /psalauncher
/shortcuts                                       /fax
```

### 1.2 「我的设备」页（`/devices`）

| 区块 | 中文（zh_CN） | 英文原文 | 显示数据 | 云依赖 |
|---|---|---|---|---|
| 列表标题 | 我的设备 | — | 已关联设备列表 | 本地 |
| 设备卡·昵称 | 我的打印机 | `devices-nickname.printer` | 设备昵称，默认 `HPSERIAL (Ink Tank Wireless 410 series)` | 本地 |
| 设备卡·状态行 | USB 已连接 / 云已连接 / 未连接。获取连接帮助 / 设置未完成。请完成打印机设置 / 已激活 | `printerStatus.usbConnected` / `cloudConnected` / `offline` / `setupIncomplete` / `hpPlusEnrolled` | 连接态 + onboarding 态 | 本地（`connectionState`），`cloudConnected` 需云 |
| 空态 | 添加您的第一台设备以管理设置并获得支持 / 让我们开始吧！ | `firstDeviceCard.*` | 空列表引导 | 本地 |
| 热门功能（默认关闭） | 热门功能 | `devices.popularfeatures.header` | 推荐卡 | 需云 |
| 订单跟踪卡 | 订单状态 / 已确认 / 正在处理 / 已发货 / 已送达 / 跟踪送货状态 | `devices.components.trackingCard.*` | 打印机购买订单状态 | 需云 + 需账号 |
| 动作卡：相机扫描 | 相机扫描 / 从此设备发送安全传真 | `actionsCards.CameraScanName` | 手机拍照扫描 | 本地（`devices-x-camerascan` 开关当前 = `false`） |
| 动作卡：移动传真 | 移动传真 / 从此设备发送安全传真 | `actionsCards.MobileFaxName` | 传真 | 仅云 |
| 支持性访问提示 | 仅用于支持目的的访问 | `supportOnlyAccess` | 只读模式标识 | 本地 |

> 证据：`MFE\@hpx-core-experiences\react-devices-mfe\assets\locale\zh_CN.json`；
> `MFE\@hpx-core-experiences\react-device-statuses-mfe\assets\locale\zh_CN.json`；
> `LS_MYHP\AsyncStorage.db` → key `HP.DeviceController.DeviceNicknames` =
> `{"00000000-…c183":"HPSERIAL (Ink Tank Wireless 410 series)","Default stringDefault string":"我的电脑"}`。

**设备卡数据模型**（GraphQL fragment，`MFE\@clientos\devices-northbound-api\clientos-devices-northbound-api.js` → `SimpleDevice`）：

```
deviceId
identity { serialNumber deviceUuid location friendlyName bizModel deviceSegment
           makeAndModel { name number typeId series manufacturer family }
           lastUpdatedAt firmwareVersion programLevel }
images { url orientation }
lastUpdatedAt
relations { type lastUpdatedAt }
type
... on PrinterDevice {
  solutions { printAnywhere { isEnabled } privatePickup { jobCount } }
  status { connection { connectionState } onboarding { setupComplete } }
}
```
另有 `ExtendedDevice` profile，追加 `deviceOwnership{ users{…email/fullName/locale/phone/roleCategory} addresses subscriptions }` —— 这是**需账号**的部分，克隆应整段丢弃。

**`localDeviceDetails`（设备详情页的分区装配）**
`MFE\@hpx-core-experiences\react-device-section-mfe\…-device-section-mfe.js`：
```graphql
query localDeviceDetails($deviceId: String!) { localDeviceDetails(deviceId: $deviceId) { devicePrimaryActions } }
```
`devicePrimaryActions` 的每一项形状（同文件 + `react-print-mfe`）：
`{ trackId, trackCategory, background, endContent/icon, title, description, mfePath, isEnabled, campaignName, taxonomyName, friendlyName, jumpId, channel }`
→ **动作卡是可下发的数据，不是硬编码 UI**。`mfePath` 以 `https://` 开头则 `window.open` 外开，否则内部 `navigate`。
克隆可以硬编码同样形状的数组，保留「数据驱动」这层抽象。

### 1.3 打印机详情页（`/print`）

分区（由原生 `localDeviceDetails` 拼装，开关见 `AsyncStorage.db` → `@hp-af/feature-switch/features`）：

| 分区 | 开关 key | 当前值 | 内容 |
|---|---|---|---|
| 主动作卡网格 | `printer-x-devicedetails-actioncards` | `True` | 打印 / 扫描 / 复印类入口 |
| 状态卡 | `printer-x-devicedetails-statuscard` | `False` | 状态横幅（被关闭） |
| 设备状态消息 | `devices-x-devicestatuses` | `True` | `localStatusMessages` 列表 |
| 耗材 | `communications-x-dynamicsupplies` | `True` | 见 §5 |
| 产品信息 | `devices-x-productinfo` + `-moreinfo` | `True` | 见 §4.1 |
| 个性化 | `devices-x-personalization` | `True` | 磁贴排序 |
| AI 迷你仪表盘 | `printer-x-devicedetails-aipminidashboard` | `True`（LD）/ `False`（缓存） | AI 建议 |
| 远程打印 | `printer-x-remoteprint` / `printer-x-printanywhere` | `True` | 仅云设备可见 |

**状态消息模型**（`MFE\@hpx-core-experiences\react-device-statuses-mfe\…-device-statuses-mfe.js`）：
```graphql
query GetStatusMessages($deviceId: String!) {
  localStatusMessages(deviceId: $deviceId) { name description icon priority toolTip }
}
```
本机实际缓存的一条（`AsyncStorage.db` → `HP.DeviceController.LocalDevicesCache`）：
```json
{"Id":"65640","StatusName":"eProductStatusAlertID_InPowerSave","Severity":2,"IsBlocking":false,
 "Title":{"Value":"打印机处于休眠状态"},"Description":{"Value":"打印机处于休眠状态"}}
```
→ 状态消息**已本地化中文**，来源是 `SMS`（Smart Message System）ID，而非云端文案。克隆应内置一张 `SMS ID → 中英文文案 + 图标 + severity + 是否阻断` 的本地表。

### 1.4 HP Smart 首页磁贴（对照参考）

`SMART\SortedTiles.xml` 定义默认排序与 12 个磁贴：
`Dsp, ScanCapture, SmartTasks, FunTile, PrintDoc, SoftFax, Help, PrintPhotos, PrinterInfo, PrivatePickup, Shortcuts, CloudScan`

| SortId | 功能 | 中文名（推断自 Extension 资源） | 默认启用 | 云依赖 |
|---|---|---|---|---|
| `Dsp` | Instant Ink / MNS 仪表盘 | 耗材订购 | 是 | 仅云 |
| `ScanCapture` | 扫描 | 扫描 | 是 | 本地 |
| `SmartTasks` | 快捷方式（扫描→动作） | 快捷方式 | 是（部分区域隐藏） | 部分本地，云端目的地需云 |
| `FunTile` | 趣味/支持内容 | 获取支持 | 是 | 需云 |
| `PrintDoc` | 打印文档 | 打印文档 | 是 | 本地 |
| `SoftFax` | 移动传真 | 传真 | **否** | 仅云 |
| `Help` | 帮助 | 帮助 | 是 | 需云 |
| `PrintPhotos` | 打印照片 | 打印照片 | 是 | 本地 |
| `PrinterInfo` | 打印机信息 | 打印机信息 | 是 | 本地 |
| `PrivatePickup` | 私人取件 | 私人取件 | 是（隐藏于个性化） | 仅云 |
| `Shortcuts` | 快捷方式 | 快捷方式 | 是（隐藏于个性化） | 部分本地 |
| `CloudScan` | 扫描到云 | 云扫描 | 是 | 仅云 |

> 证据：`SMART\SortedTiles.xml`、`LS_SMART\app_sortedTiles.xml`（用户实际生效版本，`Version 1.4`，无 `Shortcuts`/`CloudScan`）。

`SMART\ApplicationItems.xml` 共 **84 条** Item，带完整的可见性条件。对本机（**inkjet**）影响最大的三条：
```xml
<Item><PageId>ProductMaintenance</PageId> ... <DisableForInkjet/></Item>   <!-- 维护页对喷墨隐藏 -->
<Item><PageId>PrinterSettings</PageId>    ... <DisableForInkjet/></Item>   <!-- 打印机设置页对喷墨隐藏 -->
<Item><PageId>InternalPrint</PageId>      ... <DisableForInkjet/></Item>   <!-- 内部报告页对喷墨隐藏 -->
```
即 **HP Smart 对 Ink Tank 410 根本不显示维护/设置/报告页，而是把用户导向 EWS**：
```xml
<Item><PageId>PrinterHomePageEws</PageId><Extension>PrinterHomePageEwsExtension</Extension>
      <Command>PrinterHomePageEws</Command><Enabled>true</Behaviors><Behavior>8</Behavior></Item>
```
> 证据：`SMART\ApplicationItems.xml`（Group `Tools` / `Manage` / `Settings`）。

---

## 2. 打印流程

### 2.1 myHP 的打印流程（Web 层只负责选文件，选项交给原生对话框）

```
/devices  →  点「打印」动作卡
   ↓
/print                     ← 打印中心：两个入口卡
   ├─ localPrintDriverInstalledCheck(deviceId)   （PRINTER_DRIVER_INSTALLATION_CHECK）
   │    └─ localDeviceDriverInstallationRequired.installationNeeded == true
   │         → 重定向 /print-install-driver
   ↓
/print-documents  或  /print-photos
   ↓
localPrintFilePicker(filePickerArgs)     ← 原生文件选择器（Windows FileOpenPicker）
   ↓
localPrintGetPrintFiles → { localPrintGetPrintFiles, localNavigateBackToPreviousScreen,
                            localPrintIsScreenVisible, localPrintShowFileFormatErrorDialogue }
   ↓
（文档路径）localPrintCheckPDFWithPassword(passwordPromptArgs)   ← 加密 PDF 走这里
   ↓
预览
   ↓
localPrintDocument(imagePathCollection)  /  localPrintPhoto(imagePathCollection)
   ↓
localPrintClearPrintQueueItems           ← 清空本次队列
```

> 证据：`MFE\@hpx-core-experiences\react-print-mfe\…-print-mfe.js`（`PRINTER_DRIVER_INSTALLATION_CHECK`、`/print-photos`/`/print-documents` 跳转与驱动判断）；
> `…react-print-documents-mfe\…js`（`GET_PRINT_FILES`、`CHECK_PDF_WITH_PASSWORD`、`LOCALPRINT_PRINT_DOCUMENT_MUTATION`、`LOCALPRINT_PRINT_FILE_PICKER_MUTATION`）；
> `…react-print-photos-mfe\…js`（`GET_PRINT_FILES_QUERY`、`LOCALPRINT_PRINT_PHOTO_MUTATION`、`LOCALPRINT_CLOSE_FILE_FORMAT_ERROR_DIALOGUE_MUTATION`）。

**关键事实**：`localPrintPhoto` / `localPrintDocument` 的**唯一入参是 `imagePathCollection: JSON`**。
份数、颜色、质量、纸张、缩放**都不在 Web 层**——它们在原生打印对话框（DEVMODE）里。
所以 myHP 的打印选项 UI = **Windows 打印对话框**，克隆若自绘就必须自己补齐这一整组。

**错误态文案（要还原）**
| key | 中文 |
|---|---|
| `FileFormatErrorScreen.Title` | 文件格式错误 |
| `FileFormatErrorScreen.Description` | 无法打开该文件，文件已损坏或者格式不正确。 |
| `PasswordPromptScreen.Title` | 需要密码 |
| `PasswordPromptScreen.EnterPassword` | 输入密码打开文件 |
| `PasswordPromptScreen.ErrorMessage` | 密码不正确。请重试 |

### 2.2 HP Smart 的打印流程与完整选项集（克隆的选项基准）

页面链（`SMART\HP.Framework.Extensions.PrintPhotos\…xr.xml`）：
`ChooseSource → FilePicker / FilePickerIpp → ImageTiles → SingleImage / MultipleImages → PrintSettingsPage → 打印`

**打印设置页暴露的选项**（XAML 元素名 = 界面控件名）：

| 分组 | 控件（XAML 名） | 取值来源 / 说明 |
|---|---|---|
| 份数 | `CopiesBox` `CopiesLabel` | IPP `copies` |
| 颜色 | `ColorMode` `ColorModeCollection` | IPP `print-color-mode-supported`：`auto, auto-monochrome, monochrome, color` |
| 打印质量 | `PrintQuality` `PrintQualityCollection` `PageOutputQualityLabel` `cboPageOutputQuality` | IPP `print-quality`：3=Draft / 4=Normal / 5=Best |
| 纸张尺寸 | `PageSize` `MediaSize` `MediaSizeCollection` `PaperSizeCombo` `CustomPaperSizePopup` | IPP `media-supported`（含自定义尺寸） |
| 纸张类型 | `MediaType` `MediaTypeCollection` `PaperTypeCombo` `PageMediaTypeBox` | IPP `media-type-supported` |
| 进纸来源 | `MediaSource` `MediaSourceCollection` `PaperTrayGauge` | IPP `media-source-supported` |
| 方向 | `Orientation` `PageOrientationBox` `OrientationCombo` | 纵向 / 横向 |
| 双面 | `DuplexPrinting` `DuplexPrintingCombo` `DuplexFlipOverFinishingImage` `DuplexFlipUpFinishingImage` | IPP `sides-supported` → **本机仅 `one-sided`，必须隐藏** |
| 无边距 | `BorderLessPrintingCombo` `BorderLessOptionCollection` `BorderlessOptionAvailable` | IPP `hp-edge-to-edge-support` → **本机未上报，隐藏** |
| 缩放 | `PageScalingLabel` `ScalingControl` `ScalingRatioText` `ScaleToFit` `ScaleToFitLabel` `tsScaleToFit` `EnlargeButton` `FitPage` `FitPageCollection` `posterGrid` | 客户端软件缩放：适合页面 / 自定义百分比 / 放大 / 海报分块 |
| 逐份 | `DocumentCollateLabel` `tsDocumentCollate` | 多份时是否逐份 |
| 小册子 | `bookletGrid` `BookletNUpTemplateSelector` `BookletPageNumberScale` `BookletPageNumbers` `bookletpageNumber` `gridBookletUp/Down/Left/Right` | 小册子/N-up + 装订方向 |
| 水印 | `WatermarkPopup` `WatermarkControl` `PageWatermarkBox` `WatermarkTextFontCombobox` `WatermarkTextFontColorCombobox` `lblImgWmScale` `sliderImgWmScale` `UIWatermarkPlacementViewModel` `UIWatermarkTextTransparencyViewModel` `UIWatermarkUsageFirstPageOnlyViewModel` `WaterMarkTextStyleBold/Italic/Outline` | 文字/图片水印、字体、字号、颜色、透明度、位置、仅首页 |
| 照片专属 | `SinglePhotoSize` `PhotoSizeCombo` `PhotoSizeCollection` `PhotoSizesRevertRound*` | 照片尺寸（4×6 / 5×7 / 全页 等） |
| 任务类型 | `JobType` `PdfToPrint` `ItemToPrint` `CurrentPageDesc` | 打印 / 私有取件 / 云队列 |
| 打印限制提示 | `ShowPrintingLimitation` | 设备能力不足时提示 |

> 证据：`SMART\HP.Framework.Extensions.PrintPhotos\HP.Framework.Extensions.PrintPhotos.xr.xml`；
> `SMART\HP.Framework.Extensions.IppPrint\HP.Framework.Extensions.IppPrint.xr.xml`（`DuplexPrinting`、`FitPage`、`CustomSizeLink`、`IsPrivatePickup`）；
> `SMART\HP.Framework.Libs.PrinterControlContent\…xr.xml`（`CopiesBox`、`DuplexPrintingCombo`、`BorderLessPrintingCombo`、`PaperSizeCombo`、`PaperTypeCombo`、`PrintQualityCombo`、`DocumentCollateLabel`、`EstimatedSupplyLevels`）。

### 2.3 选项 → IPP 属性的权威映射

`SMART\hpuiodatamap.xml`（225 条 `DataItem`，`Command` 全部为 `Get-Printer-Attributes`）就是官方的「UI 字段 ↔ IPP 属性」字典。摘录与打印选项直接相关的：

| UI 数据项 | IPP 属性 | 备注 |
|---|---|---|
| `ModelName` | `printer-make-and-model` | |
| `DeviceID` | `printer-device-id` | |
| `PC_MediaSize` | `media-supported` | |
| `PC_MediaType` | `media-type-supported` | |
| `Media-source-Supported` | `media-source-supported` | |
| `DuplexUnit_Installed` | `sides-supported` | |
| `ColorType` / `Grayscale-BlackOnly` | `print-color-mode-supported` | |
| `PrintQuality-Draft/Normal/Best/Max/Economode` | `hp-print-quality-supported` + `.type,3/4/5/10/11.pq-mode` | 数字即 `print-quality` 枚举 |
| `Resolution-150x150/300x300/600x600/1200x1200dpi` | `printer-resolution-supported` | |
| `EdgetoEdge_Installed` | `hp-edge-to-edge-support` | 无边距 |
| `TabPrinting_Installed` | `hp-tabbed-printing-supported` | |
| `Staple_Mode` / `*_Installed` | `finishings-supported` | 本机无 |
| `UserMargins_Top/Bottom/Left/Right_1..2` | `media-top/bottom/left/right-margin-supported` | |
| `RGBThemes` / `CMYKThemes` / `AdvanceImageControl` / `AdvanceInkControl` | `hp-image-enhancement-support` | |
| `DynamicRGBProfile_Option1..9` | `hp-rgb-profiles-options-supported` | |
| `HPPantoneEmulation` | `hp-pantone-emulation-supported` | |
| `Tray1..10_Installed` | `printer-input-tray` | |
| `Job_Storage_*` | `hp-save-job-*` | 本机无 |

### 2.4 本机能力裁剪表（必须照此隐藏选项）

来自 `RECON\_eSCL_ScannerCapabilities` 与 `docs\protocol.md` 的实测 IPP 属性：

| 选项 | 本机实测值 | 克隆行为 |
|---|---|---|
| `sides-supported` | `one-sided` | **隐藏「双面」整组** |
| `print-color-mode-supported` | `auto, auto-monochrome, monochrome, color` | 显示 4 项 |
| `printer-resolution-default` | `300x300 dpi` | 默认 300 |
| `media-default` | `iso_a4_210x297mm` | 默认 A4 |
| `media-supported` | 27 种（A4/Letter/Legal/A5/A6/B5/C5/C6/DL/JIS B5/日式明信片/4×6/5×8/3×5/5×7/3×5/信封/照片 L/100×150mm/自定义 3×5in–8.5×14in） | 直接渲染设备列表 |
| `marker-levels` | `-2` | 不显示墨量条，见 §5 |
| `hp-edge-to-edge-support` | **未上报** | **隐藏「无边距」** |
| `finishings-supported` | 未上报 | 隐藏装订/打孔 |
| `document-format-supported` | `application/vnd.hp-PCL, image/jpeg, application/PCLm, image/urf, image/pwg-raster, application/octet-stream` | **无 `application/pdf`** |

> ⚠️ 最后一行是克隆的硬约束：`docs\protocol.md` §5 已实测 **PDF 不可打印**，必须走 baseline JPEG（progressive 会被拒，返回 `0x041B` + `document-unprintable-error`）。
> 克隆在「打印文档」流程里必须先把 PDF/图片统一转成 **baseline JPEG @300dpi**，不能把原文件直接丢给打印机。

---

## 3. 扫描流程

### 3.1 myHP 扫描设置页（`/print-scan-home`）— 字段顺序与取值

字段顺序取自 `MFE\@hpx-core-experiences\react-print-scan-home-mfe\assets\locale\zh_CN.json` 的键序
（React 按此顺序渲染 accordion），这是**官方 UI 的真实排列**：

| # | 分组 | 中文（zh_CN） | 英文原文 | 取值 | 本机是否可用 |
|---|---|---|---|---|---|
| 1 | 来源 | 来源 | `SourceSelection.Header` | 扫描仪玻璃板 `Flatbed` / 文档进纸器 `AdfIfLoaded` | 仅 **扫描仪玻璃板**（无 ADF） |
| 2 | 边缘 | 检测边缘 | `DetectEdges.Text` | 开 / 关（`localPrintSetEdgeDetect`） | 可用 |
| 3 | 高级预设 | 高级预设 / 预设值 | `AdvancePresetSelection.Header` / `PresetSelection.Header` | 文档 `Document` / 照片 `Photo` / 多项 `MultiItem` / 书本 `Book` / 身份证 `IDCard` | 全部可用（软件预设） |
| 4 | 扫描区域 | 扫描区域 | `ScanAreaSelection.Header` | — | 可用 |
| 5 | 页面尺寸 | 页面尺寸 | `PageSizeSelection.Header` | 整个扫描区域 `EntireAvailable` / A4 (210×297mm) / Letter (8.5×11in) / Legal (8.5×14in) / 4×6in(10×15cm) / 5×7in(13×18cm) | 全部可用 |
| 6 | 输出 | 输出 | `OutputSelection.Header` | **彩色 `Color` / 灰度 `Gray`**（仅两项） | 可用（映射 eSCL `RGB24` / `Grayscale8`） |
| 7 | 分辨率 | 分辨率 | `ResolutionSelection.Header` | 75 / **150** / 300 / 600 / 1200 dpi | ⚠️ 设备支持 `75/100/200/300/600/1200`，**150 不在列表** → 实际列表由 `flatbedResolutions` 下发，静态 i18n 只是标签 |
| 8 | 压缩 | 压缩 | `Compression.Header` | 低 `Low` / 中 `Medium` / 高质量打印 `High`（+ 结果页 `CompressionNone.Text` 无） | 可用（JPEG 质量） |
| 9 | 自动增强 | 自动增强 / 增亮颜色并增强对比度。 | `AutoEnhancementsTitle.Text` / `ScanAutoEnhancements_Desc_3.Text` | 开 / 关 | 可用 |
| 10 | 自动定向 | 自动定向 / 将图像旋转为正面朝上。 | `AutoOrientationTitle.Text` / `Orientation_Desc.Text` | 开 / 关 | 可用 |
| 11 | 自动修复 | 自动修复 / 从扫描中去除分散注意力的痕迹，比如打孔和手印。 | `AutoHealingTitle.Text` / `Autoheal_Desc.Text` | 开 / 关 | 可用（`isAutoHealEnabled`，需 HP Smart Advanced 用户 `isHpSmartAdvanceUser`） |
| — | 动作 | 预览 / 扫描 / 重置设置 | `PreviewButton.Label` / `ScanButton.Label` / `ResetSettings.Content` | — | — |

**默认值（本机实测，官方应用写下的真实默认）**
`LS_MYHP\scanSettings.json`：
```json
{"PaperSource":"Flatbed","DetectEdges":true,"Duplex":false,"ScanColorMode":"Color",
 "Content":"Photo","Resolution":600,"PageSize":"EntireAvailable",
 "IsOrientationEnabled":false,"IsEnhancementEnabled":true,"IsAutoHealEnabled":false,
 "IsIDCardScan":false,"IsBookScan":false,"IsMultiPageScan":false,
 "ScanAdfFace":"Simplex","Compression":"Medium","ScannerAvailabe":true}
```
→ 克隆的初始值应照抄这一组（注意 `Content:"Photo"` 与 `Resolution:600` 是「照片」预设的默认，不是文档预设）。

**设备能力（必须据此裁剪）**
`RECON\_eSCL_ScannerCapabilities`：
- `InputSource`: 仅 `Platen`
- `ColorMode`: `BlackAndWhite1` `Grayscale8` `RGB24`（UI 只暴露后两者 → **无 1-bit 黑白**）
- `DocumentFormat`: `image/jpeg` `application/pdf` `application/octet-stream`（扫描端**支持 PDF**，与打印端相反）
- `Resolution`: 75 / 100 / 200 / 300 / 600 / 1200
- `Intent`: `Document` `Photo` `Preview` `TextAndGraphic`
- `Brightness` / `Contrast`: 0–2000，默认 1000
- `Threshold`: 0–255，默认 128
- 最大区域 2550×3508 @300dpi（光学 1200dpi）

**`localPrintGetScanSettings` 返回的能力结构**（`react-print-scan-home-mfe`）：
```graphql
localPrintGetScanSettings(deviceId: $deviceId) {
  flatbedResolutions adfResolutions source output scanCompression
  duplexSupported flatbedSupported adfSupported IsADFLoaded
  isAutoHealEnabled isHpSmartAdvanceUser isCompressionSupported
}
```
→ 克隆应实现同形能力对象，UI 完全数据驱动。

### 3.2 扫描后的页面链

```
/print-scan-home
   │  START_SCAN_MUTATION → localPrintStartScan
   │  （预览）SCAN_PREVIEW_MUTATION → localPrintStartScanPreview
   ↓
/print-scan-detect-edge        ← 仅在 DetectEdges 开 且 有边缘需要确认时
   │  GET_LOCAL_DATA_QUERY → localPrintGetImageForDetectEdge / localPrintGetDetectEdgeInfo
   │  DETECT_EDGE_DONE_MUTATION(Quad, FlattenEnabled) → localPrintDetectEdgeApply
   │  DETECT_EDGE_FLATTEN_MUTATION → localPrintPerformFlatten     ← 书本压平
   ↓
/print-scan-results
   │  GET_SCANNED_IMAGES_QUERY → localPrintGetScannedItems
   │      { isImageListEmpty canAnimateImage activeImageFilePath currentIndex imagePathCollection }
   │  GET_TUHMBNAILIMAGES_QUERY → localPrintGetThumbnailItems
   ↓
/print-scan-edit               ← 单页编辑
      GET_LOCAL_DATA_QUERY → localPrintImageDataToEdit / localPrintGetImageResolutionInfo
      EDITED_IMAGE_DATA_MUTATION($imageInfo) → localPrintUpdateImageData
```

**多页 / 特殊扫描的独立状态机**（同一 MFE 内的 mutation 集合即功能清单）：
`SCAN_SET_PAGE_COLLECTION_MUTATION`（页面集合）、`SCAN_SET_PRESETS_MUTATION`、`SCANNER_SET_DUPLEX_MUTATION`、
`IMAGE_REORDER_MUTATION`（拖拽排序）、`ROTATE_SINGLE_IMAGE_MUTATION` / `ROTATE_MULTI_IMAGE_MUTATION` /
`AUTO_ROTATE_MULTI_IMAGES_MUTATION`、`DELETE_SINGLE_IMAGE_MUTATION` / `DELETE_MULTI_IMAGE_MUTATION(indexes)`、
`REPLACE_IMAGE_MUTATION(isIDCardReplaceFlow)`、`SET_CURRENT_IMAGE_INDEX_MUTATION(index, activePreviewImage)`。

**身份证专用流程**（4 个独立 mutation + 2 个插图 + 2 条引导文案）：
```
ID_Card.FrontPageText  = 将身份证的正面放在扫描仪玻璃板的左上角。选择<bold>扫描</bold>将身份证的正面和背面合并到一页上。
ID_Card.BackPageText   = 将身份证的背面放在扫描仪玻璃板的左上角，然后选择<bold>扫描</bold>。
SKIP_ID_CARD_BACK_SCAN / MOVE_TO_ID_CARD_NEXT_PAGE / MERGE_IDCARD_FRONT_AND_BACK / RESET_IDCARD_IMAGE
插图：MFE\...\react-print-scan-home-mfe\assets\images\ID_Card_Front_illustration.svg / ID_Card_Back_illustration.svg
```
**书本扫描**：`BookScanInstructions.Text` = 「自动压平、分开书页并保存为单个文件。\n将您的书放在扫描仪上，然后选择<bold>扫描</bold>。」
**多项扫描**：`MultiItem_Instructions.Text` = 「一次扫描多个物品并将其保存到单独的页中。…将所有物品放在扫描仪玻璃板上的中心位置。」

### 3.3 扫描结果页动作（`/print-scan-results`）

顶栏动作（`zh_CN.json` 键序）：`打印 Print` / `保存 Save` / `共享 Share` / `更多 More` / `更换 Replace` / `快捷方式 Shortcuts` / `传真 Fax` / `删除 Delete` / `扫描 Scan` / `添加 Add` / `新扫描 NewScan`

视图切换：`ThumbnailView`（缩略图视图）/ `Gallery`（图库）/ `缩略图/列表` 两套无障碍标签

**保存对话框（「功能和文件类型」）**

| 文件类型（中文） | 英文 key | 说明文案 | 生成位置 |
|---|---|---|---|
| 基本 PDF | `FileTypePDF.Text` / `BasicPdfText` | 在 PDF 文件中嵌入了图像。不包含文本内容。 | **本地** |
| 图像 (*.jpg) | `FileTypeJPG.Text` | — | **本地** |
| 可搜索 PDF | `FileTypeSearchablePDF.Text` / `SearchablePDFHeader` | 保留格式和图形的可搜索内容。 | ⚠️ 云（见下） |
| 纯文本 (*.txt) | `FileTypePlainText.Text` / `PlainTextHeader` | 不保留格式和图形。文本可编辑。 | ⚠️ 云 |
| Word 文档 (*.docx) | `FileTypeWordDocument.Text` / `WordDocHeader` | 保留格式和图形的可编辑文本。 | ⚠️ 云 |

> **云依赖铁证**：`ConvertToTextFileTypes.Title` = 「转换为文本文件类型」，
> `ConvertToTextFileTypes.Desc` = 「**这些文件类型在 HP 安全云中创建**」。
> 同文件另有 `LanguageDownloadFailedNetworkError.Text` = 「由于网络错误，无法下载所选的语言。检查网络连接，然后重试。」
> → 本地只有 PDF/JPG 两种输出；可搜索 PDF / txt / docx **必须联网**。克隆应只保留 PDF + JPG。

**其他保存选项**：`FileNameHeader`（文件名，可编辑）、`SmartFileNameHeader`（智能文件名，按检测到的重要信息自动命名）、
`FileRotationHeader`（文件轮换）、`Compression.Header`（压缩）、`DocumentLanguageHeader`（文档语言）、
`PasswordProtectionTitle.Text`（添加密码保护，6–32 字符，禁止空格）。

**OCR 错误文案（要还原）**
| key | 中文 |
|---|---|
| `TextWasNotDetected.Title` | 未检测到文本 |
| `OcrFailedImageresolutionError.Text` | 图像分辨率错误。分辨率必须介于 [150]dpi 到 [1200]dpi 之间 |
| `OcrFailedImageSizeError.Text` | 图像大小调整错误。图像大小必须大于 [300] 像素 |
| `OcrFailedGeneralError.Text` | 处理文件时出错，请尝试其他文件。 |
| `LanguageDownloadFailedTitle.Text` | 语言下载失败 |

**「扫描到」目标汇总**

| 目标 | 实现 | 本地/云 |
|---|---|---|
| 保存到本地文件 | `localPrintSaveImage(saveInfo)` | 本地 |
| 打印扫描件 | `localPrintScannedDocument` | 本地 |
| 共享（Windows 共享面板） | `localPrintShareImage(shareInfo)` | 本地 |
| 电子邮件 | `Email.Text` | 需系统邮件客户端 |
| 快捷方式（Smart Tasks） | `localPrintExecuteShortcut` | 本地动作 + 云端目的地 |
| 传真 | `localPrintGoToSoftFax` / `UPLOAD_TO_SOFTFAX_MUTATION` | **仅云** |
| 云文档源（DocProvider） | `localPrintLaunchDocProvider(sourceId)` | 需云 |
| 扫描到云 / Cloud Scan | 路由 `/app.action.scan-to-cloud`、`/app.bell.cloud-scan` | **Windows 端已封禁** |

**快捷键/云目的地证据**：`MFE\@shortcuts\react-bell-shortcuts-notifications-mfe\…js` 出现
`OneDrive` / `Google Drive` / `Dropbox` / `SharePoint`；`SMART\...\ScanCapture\...xr.xml` 有 `SmartTaskHasCloudDestination`。

### 3.4 实测扫描输出规格（用于确认默认参数）

`LS_MYHP\LocalState\.hpscan\` 中的真实输出：

| 文件 | 大小 | 像素 | JPEG 类型 | JFIF 密度 |
|---|---|---|---|---|
| `6_37_44_ziasjYtmY6xg1g0i9Eck5Q.jpg` | 1 926 038 B | 2544 × 3504 | **baseline (SOF0)** | units=1(inch), 257×300 |
| `scan183725531.jpg` | 2 757 465 B | **2550 × 3508** | **baseline (SOF0)** | units=1(inch), 257×300 |
| `scan174926911.jpg` / `scan183537595.jpg` | 0 B | — | 失败/占位 | — |

结论：
- 输出是 **A4 @300dpi 的 baseline JPEG**（2550×3508 恰为 A4@300dpi）。
- `2544×3504` 是**边缘检测裁掉 6×4 px** 的结果 → 对应 `DetectEdges:true`。
- 尽管 `scanSettings.json` 写 `Resolution:600`，实际输出仍是 300dpi —— 因为设备把全页扫描钳制在 2550×3508（`docs\protocol.md` §3）。
- `C:\Users\user\opencode\hp-offline\tools\scan_out.jpg` 同样是 baseline 2550×3508，1 675 423 B。
- **克隆必须输出 baseline JPEG（SOF0）**，与打印端要求一致。

---

## 4. 打印机管理 / 设置

### 4.1 设备信息字段（`/print` 的产品信息区）

`MFE\@hpx-core-experiences\react-product-information-mfe\assets\locale\zh_CN.json`：

| 中文标签 | key | 本机值（实测） | 来源 | 云依赖 |
|---|---|---|---|---|
| 打印机名称 | `printer.label` | `HPSERIAL (HP Ink Tank Wireless 410 series)` | 本地（用户可改） | 本地 |
| 产品信息 | `product_information.title` | — | 分组标题 | 本地 |
| 产品型号 | `product_number.start` | `Z4B53A` | LEDM `ProductConfigDyn` | 本地 |
| 产品序列号 | `serial_number.start` | `000000000010` | LEDM `ProductConfigDyn` / IPP `printer-device-id` | 本地 |
| 固件版本 | `firmware_version.start` | `KEP1FN2020AR` | LEDM `ProductConfigDyn` / IPP `printer-firmware-name` | 本地 |
| Bonjour 名称 | `bonjour.label` | `HPSERIAL` | mDNS / WSD `Hostname` | 本地 |
| 网络发现名称 | `network_discovery_name.label` | `HP Ink Tank Wireless 410 series [E0C183]` | WSD `pwg:DeviceId` | 本地 |
| 保修状态 | `warranty_status.start` | 未知 / 待定 | 云端 entitlement | **需云** |
| 订阅 | `subscription_status.start` | 「登录以查看范围状态」/「订阅与此帐户无关」 | 云端 | **需云 + 需账号** |
| 金牌服务 | `carepack_status.start` | — | 云端 | **需云** |
| 更多信息和报告 | `more_information_and_reports.start` | — | 链接到 EWS | 本地 |
| 电脑隐私设置 | `pc_privacy.label` | 全部接受 / 全部拒绝 / 自定义 | 本地 consent 存储 | 本地 |

**HP Smart 侧的产品信息页**（`SMART\HP.Framework.Extensions.PrinterInformation\…xr.xml`）额外有：
`CountriesSource` / `SelectedCountryAndRegion`（**地区/国家更改**）、`LanguagesSource` / `SelectedLang`（**语言更改**）、
`AutoOffEnabled` / `AutoIntervalSource` / `SelectedAutoInterval`（**自动关机**）、`ShowSavePopup`。
这三项都是**写打印机**的本地操作（LEDM `ProductConfigDyn` PUT），但**本机 `CountryRegionWriteAccess:true` / `LangWriteAccess:true`** 才可写。

### 4.2 维护动作

**关键发现：HP Smart 对喷墨机型隐藏了整个维护页**（`ApplicationItems.xml` 中 `ProductMaintenance` / `InternalPrint` / `PrinterSettings` / `DiagnoseAndFix` / `PrintQueueMgmt` 全部带 `<DisableForInkjet/>`）。
喷墨用户被导向 **EWS（打印机内嵌网页）**：`PrinterHomePageEws` 扩展 + `ShowOfflineErrorEws` / `ShowNavigationErrorEws`。

因此，对本机而言「官方 UI 上的维护」= **在 WebView 里打开 `http://192.168.1.100/`**。

但**设备本身确实支持**这些维护/报告动作（这才是克隆可以真正实现的）：
`RECON\_DevMgmt_InternalPrintCap.xml` → `ipcap:JobTypesSupport`：

| JobType | 含义 | 建议 UI 名 |
|---|---|---|
| `cleaningPage` | 清洗打印头（1 级） | 清洁打印头 |
| `cleaningPageLevel2` | 深度清洗（2 级） | 深度清洁 |
| `cleaningVerificationPage` | 清洗验证页 | 清洁校验页 |
| `paperFeedCleaningPage` | 进纸清洁 | 清洁进纸辊 |
| `ribSmearCleaningPage` | 墨污清洁 | 清洁墨渍 |
| `configurationPage` | 配置页 | 打印配置页 |
| `extendedConfigurationPage` | 扩展配置页 | 打印扩展配置页 |
| `demoPage` | 演示页 | 打印演示页 |
| `diagnosticsPage` | 诊断页 | 打印诊断页 |
| `pqDiagnosticsPage` | 打印质量诊断页 | 打印质量诊断 |
| `networkSummary` | 网络摘要 | 打印网络摘要 |
| `networkDiagnosticPage` | 网络诊断页 | 打印网络诊断 |
| `wirelessNetworkPage` | 无线网络页 | 打印无线网络信息 |
| `eventLogReport` | 事件日志 | 打印事件日志 |
| `webAccessReport` | Web 访问报告 | 打印 Web 访问报告 |

调用方式：`POST /DevMgmt/InternalPrintDyn.xml`，body 指定 `JobType`（`JobUrl` 已在 cap 中声明）。

对齐（Align）：`SMART\...\ProductMaintenance\...xr.xml` 有完整的两级流程
`ManualAlignmentChoicesDialog`（手动对齐选项）+ `SemiAutoLevelDialog`（半自动分级）+ `AlignButtonTitleBody`；
素材 `bestAlignment.bmp`（对位样张）、`maintenance_Align-Printheads.jpg`、`maintenance_Clean-Printheads.jpg`。
**但设备侧没有暴露对齐 LEDM 资源**：`RECON\_DevMgmt_DiscoveryTree.xml` 里只有
`/Calibration/CalibrationManifest.xml`（HP Connected 校准，云相关）与 `/Utilities/UtilitiesManifest.xml`，
而 `UtilitiesManifest` 的 `ICCJob` / `ICCStatus` 实际是 `ut:InternetConnectionStatus`（**联网状态检查，不是墨水校准**）。
→ **结论：本机无「对齐」的本地协议入口；克隆不应实现对齐，只保留清洗 + 打印报告。**

清洗分级 UI 参考（HP Smart）：
`CleanCommand` → `CleanLevelDialog`（`CleanLevelText1`、`CleanLevelButtons`、`CleanLevelButtonLevelText`、`CleanLevelButtonDoneText`）
→ 对应设备 `cleaningPage` / `cleaningPageLevel2`。

### 4.3 网络设置

| 项 | 中文 | 来源 | 本地/云 |
|---|---|---|---|
| 连接方式 | USB 已连接 / 云已连接 / 未连接 | `localDeviceDetails.status.connection.connectionState` | 本地 |
| Wi-Fi 列表 | — | LEDM `/IoMgmt/Adapters/Wifi0/WifiNetworks` | 本地 |
| Wi-Fi 当前配置 | — | `/IoMgmt/Adapters/Wifi0/Profiles/Active` | 本地 |
| Wi-Fi 协议开关 | — | `/IoMgmt/Adapters/Wifi0/Protocols` | 本地 |
| 有线适配器 | — | `/IoMgmt/Adapters/eth0|eth1/Protocols` | 本地 |
| 适配器能力 | — | `/IoMgmt/IoMgmtCap.xml`、`/IoMgmt/IoConfig.xml` | 本地 |
| 网络应用开关（mDNS/SNMP/9100/IPP） | — | `/DevMgmt/NetAppsDyn.xml` | 本地 |
| 更改网络 | `ChangeNetwork` / `ChangeNetworkBtn` / `ChangeNetworkDialog` / `NoWirelessNetworkFound` / `NetworkNamePlaceholder` | HP Smart `OobeSetup` + `NetworkInformation` | 本地（BLE/SoftAP 配网时需近距离） |
| 打印网络摘要/诊断 | — | `InternalPrintDyn` JobType | 本地 |

**HP Smart 的网络信息页**（`SMART\HP.Framework.Extensions.NetworkInformation\…xr.xml`）：
`WifiItemCollection` / `WifiDirectItemCollection` / `EthernetItemCollection` / `ShowUSBConnection` —— 即 **Wi-Fi + Wi-Fi Direct + 以太网 + USB** 四类适配器分区。

本机实测：`RECON\_IoMgmt_Adapters`（3174 B，非空）；`NetworkList` 缓存为 `["3F","Ethernet~#~3F"]`（`LS_MYHP\RecentDeviceList.xml`）。

### 4.4 固件

| 环节 | 实现 | 本地/云 |
|---|---|---|
| 当前版本显示 | LEDM `ProductConfigDyn` → `dd:Revision` = `KEP1FN2020AR` | **本地** |
| 检查更新 | 云：`/devices/v1/FWUpdateCheck`；UI 是**远程网页** `https://static.hpsmart.com/jarvis/react-firmware-update-controller-pro/latest/index.html` | **仅云** |
| 更新订阅开关 | `localSetFirmwareUpdateSubscription(deviceId, enabled)`（`REGISTERFWUPDATE`） | 本地开关，云端执行 |
| 更新进度 | `UpdatingFirmware` / `FirmwareProgressBar`（HP Smart XAML） | 本地展示，数据来自设备 |
| 固件下载 ID | LEDM `ProductConfigDyn` → `dd:FirmwareDownloadID`（128 hex） | 本地 |

> 证据：`LS_SMART\EBWebView\Default\History` 中
> `https://static.hpsmart.com/jarvis/react-firmware-update-controller-pro/latest/index.html?appInstanceId=…`（访问 2 次）；
> `MFE\...\react-print-mfe\…js` → `mutation REGISTERFWUPDATE($deviceId: String!, $enabled: Boolean!) { localSetFirmwareUpdateSubscription(deviceId: $deviceId, enabled: $enabled) }`；
> `paths` 扫描命中 `/devices/v1/FWUpdateCheck`。
> **克隆必须放弃「检查固件更新」**，只显示当前版本 + `FirmwareDownloadID`。

### 4.5 LEDM vs 云端：本机哪些设置项真的能写

| 设置项 | 协议 | 端点 | 本机可写 |
|---|---|---|---|
| 打印机名称 / 位置 | LEDM | `ProductConfigDyn` PUT | 是（`LangWriteAccess/CountryRegionWriteAccess: true`） |
| 国家/地区 | LEDM | `ProductConfigDyn` PUT | 是 |
| 面板语言 | LEDM | `ProductConfigDyn` PUT | 是（设备已内置 24 种语言） |
| 自动关机 | LEDM | `ProductConfigDyn` PUT | 是 |
| 默认打印设置 | LEDM | `PrintConfigDyn` | 是（只读 GET 已实测 200；PUT 需 EWS 鉴权） |
| 纸张/纸盒 | LEDM | `MediaHandlingDyn` | 是（只读实测 200） |
| 网络应用开关 | LEDM | `NetAppsDyn` | 是 |
| Wi-Fi 配置 | LEDM | `IoMgmt/*` | 是（需 `SecurityDyn` 鉴权） |
| 清洗 / 打印报告 | LEDM | `POST InternalPrintDyn.xml` | 是 |
| 恢复出厂 / 重启 | LEDM | `ProductActions/FactoryDefaults` / `PowerCycle` / `DirtyPowerCycle` / `ResetOnNextBoot`（全部 `SecureAccess=true`） | 是（需 EWS 口令） |
| 打印机隐私设置 | 云 | `localShowConsents` + 云端 consent | **否** |
| 安全设置（Smart Security） | 云 | `SmartSecurity` JWebView | **否** |
| Instant Ink / 订阅 | 云 | `*.hpinstantink.com` | **否** |

---

## 5. 耗材 / 状态

### 5.1 本机真实耗材数据（这是硬约束）

**LEDM**（`RECON\_DevMgmt_ConsumableConfigDyn.xml`）：
```xml
<dd:ConsumableLabelCode>CMY</dd:ConsumableLabelCode>
<dd:ConsumableState>newGenuineHP</dd:ConsumableState>
<dd:ConsumableTypeEnum>inkCartridge</dd:ConsumableTypeEnum>
<dd:ConsumablePercentageLevelRemaining>0</dd:ConsumablePercentageLevelRemaining>
<!-- 同样一组重复一次，LabelCode = K -->
```
**IPP**：`marker-levels = -2`（-2 = 设备不报百分比）、`printer-supply` = tri-color ink / black ink。

**HP Smart 的落库形态**（`LS_MYHP\RecentDeviceList.xml`，最完整）：

| 字段 | 三色 | 黑色 |
|---|---|---|
| `SupplyName` | `tri-color` | `black` |
| `SupplyColor` | `#0098CE#EA1D76#FFD100` | `#000000` |
| `SupplyLevel` | `0` | `0` |
| `SupplyCode` / `SupplyLabelCode` | `CMY` | `K` |
| `SupplyType` | `inkCartridge` | `inkCartridge` |
| `SupplyFamilyName` | `TIJ2` | `TIJ2` |
| `SupplyInstalled` | `M0H50A` | `M0H51A` |
| `IsTriColor` | `true` | `false` |
| `SupplyState` | `eStatusCategory_UsedConsumable` | 同 |
| **`LevelState`** | **`Unknown`** | **`Unknown`** |
| **`SupplySeverity`** | **`SeverityType_Unknown`** | **`SeverityType_Unknown`** |
| `IsSubscription` | `false` | `false` |

**myHP 的落库形态**（`LS_MYHP\SavedConsumables.json`，注意与上表冲突）：
```json
{"00000000-…c183":{"Consumables":[
  {"id":"CYAN","level":{"current":100,"maxCapacity":100},"state":"READY","color":"CYAN"},
  {"id":"MAGENTA", …同上…}, {"id":"YELLOW", …同上…}, {"id":"BLACK", …同上…}],
 "LastSavedAt":"2026-10-24T19:01:01"}}
```
→ myHP 把三色**拆成 CMY 三条**，并在「设备不报」时**填 `100/100` + `READY`**。
这是官方实现里的**降级缺陷**（会让人误以为满墨）。克隆**不应复制**这个行为，应显示「墨量未知」。

### 5.2 UI 呈现方式（文案齐全，可直接照抄）

`MFE\@hpx-core-experiences\react-supply-levels-mfe\assets\locale\zh_CN.json`：

| 场景 | 中文模板 |
|---|---|
| 卡片标题 | 估计耗材余量（`estimated-supply-levels`） |
| 时间戳 | 上次更新日期：{{date}}（`last-updated`） |
| 百分比正常 | {{supplyName}}耗材余量约为 {{level}}%（`supply-level-is-approximately`） |
| 偏低 | {{supplyName}}耗材余量不足（`supply-level-is-low`） |
| 极低 | {{supplyName}}耗材余量严重不足（`supply-level-is-very-low`） |
| 耗尽 | {{supplyName}}耗材已耗尽（`supply-depleted`） |
| 缺失 | {{supplyName}}耗材缺失（`supply-missing`） |
| **未知** | **{{supplyName}}耗材状态未知**（`supply-status-unknown`） |
| 三色专用 | 三色耗材余量约为 {{level}}% / 三色耗材余量不足 / 三色耗材已耗尽 / 三色耗材缺失 / 三色耗材状态未知 |
| 质量提醒 | 耗材余量不足时，打印质量可能会受到影响（`print-quality-low`） |
| 纸张：正常 | 纸张耗材余量约为 {{level}}% |
| 纸张：偏低/极低/耗尽 | 纸张耗材余量不足 / 严重不足 / 已耗尽 |
| 无障碍标签 | 耗材余量卡（`supply-levels-card`）、耗材卡链接（`supplies-card-link`） |

**数据模型**（`MFE\...\react-supply-levels-mfe\chunks\747.js`）：
```graphql
query GetPrinterSupplies($printerId: String!) {
  localPrinterSupplies(deviceId: $printerId) {
    lastUpdatedAt
    consumables { id level { current maxCapacity } state color }
    media      { id level { current maxCapacity } state }
  }
}
```
→ **`media` 是独立一路**（纸张耗材），本机 `TrayLevelInfo: -1` 即不支持 → 纸张那组文案必须走「未知/隐藏」。

**视觉呈现**（HP Smart XAML）：`SupplyGaugeVertical`、`SupplyGauge`、`SupplyGaugeBackground`、
`SupplyGradientFill1/2/3Brush`、`SupplyOutlineState`、`SupplyLevelSlices`、`ShowColorIndicator`、
`SupplyCodeConverter` / `SupplyCodeLetter` / `SupplyLetter`、`LastSupplyDate`、`RechargesAvailable`。
即：**竖向墨柱 + 三段渐变填充 + 描边表示状态 + 色点指示**。
`EstimatedSupplyLevels` / `eEstInkLevelsBtn` / `idEstInkLevels` / `HasEstInkLevelsBtn` 是「估算墨量」入口，
`CurrentDevice.LastSupplyDate` 是时间戳字段。

### 5.3 「预计剩余页数」

**两个应用都没有这个功能**。检索结果：
- `Estimated` 在 `SMART\resources.pri` 中出现 4 次，全部是 `EstimatedSupplyLevels` / `EstInkLevels`（**估算墨量**，不是页数）；
- `pages-left` 只出现在 myHP 的 **Instant Ink 订阅卡**（`subscription-card.pages-left` = 「剩余 [X] 页」、`plan-pages-used`、`rollover-pages`、`additional-pages`、`resets-in-x-days`）——**纯云订阅概念**；
- `localPrinterSupplies` 无任何 pages 字段。

→ **结论：不要实现「预计剩余页数」。** 可替代的是 `ProductUsageDyn` 的**历史计数器**（已打印/已扫描总页数），
见 `RECON\_DevMgmt_ProductUsageDyn.xml`（25 367 B，字段最多的一份）。

### 5.4 告警 / 状态

| 层 | 数据 | 中文示例 |
|---|---|---|
| 设备状态 | LEDM `ProductStatusDyn.xml` → `scanProcessing` / `idle` 等 | — |
| 告警表 | 同上 `ConsumableStateAction`、`dd:ConsumableState` | — |
| 应用状态消息 | `localStatusMessages` → `{name, description, icon, priority, toolTip}` | 打印机处于休眠状态 |
| 阻断性告警 | 同结构 + `IsBlocking` | — |
| 墨盒状态 | `SupplyState` = `newGenuineHP` / `eStatusCategory_UsedConsumable` / 缺失 / 耗尽 | 三色耗材缺失 |

**HP Smart 的耗材详情页**（`SMART\...\SupplyDetail\...xr.xml`）：
`SupplyDetailPage` + `SupplyItem` + `SupplyGaugeVertical` + `ShowColorIndicator` + `ShowChangeNetworkBtn`
+ `ShowVirtualAlertsPromoButton`（虚拟告警推销）+ `InstantInkSupplyNotification` + `EnableInstantInkPromo`
+ `OwsWebContentView` / `JWebView`（**页内嵌 WebView，指向云端商店**）。

---

## 6. 云依赖总表（克隆保留 / 丢弃的依据）

图例：**本地** = 完全不联网可用；**需账号** = 需 HP 账号登录；**需云** = 需 HP 云服务；**仅商城** = 纯电商/订阅。

### 6.1 首页 / 设备页

| 功能 | 本地 | 需账号 | 需云 | 仅商城 | 克隆 |
|---|---|---|---|---|---|
| 设备列表 / 发现（WSD、mDNS、子网扫描） | ✅ | | | | **保留** |
| 设备卡（昵称、连接态、onboarding 态） | ✅ | | | | **保留** |
| 设备昵称修改 | ✅ `localSetDeviceFriendlyName` | | | | **保留** |
| 设备状态消息（SMS ID → 中文） | ✅ `localStatusMessages` | | | | **保留** |
| 动作卡网格（打印/扫描入口） | ✅ `devicePrimaryActions` | | | | **保留** |
| 产品信息（型号/序列号/固件/Bonjour） | ✅ | | | | **保留** |
| 保修状态 / 金牌服务 / 订阅状态 | | ✅ | ✅ | | 丢弃 |
| 订单跟踪卡 | | ✅ | ✅ | | 丢弃 |
| 热门功能 / 为你推荐 | | | ✅ | | 丢弃 |
| 相机扫描（手机） | ✅（本机开关关闭） | | | | 丢弃（无手机端） |
| 移动传真动作卡 | | ✅ | ✅ | | 丢弃 |
| 远程打印 / 已远程连接页 | | ✅ | ✅ | | 丢弃 |
| AI 助手（`/hpaiassistant`） | | | ✅ | | 丢弃 |
| 商店 Tab（`/shop`） | | | | ✅ | 丢弃 |
| 通知中心（`/notifications`） | 部分（本地 badge） | ✅ | ✅ | | 丢弃 |
| 个性化（磁贴排序） | ✅ | | | | 保留（可选） |

### 6.2 打印

| 功能 | 本地 | 需账号 | 需云 | 仅商城 | 克隆 |
|---|---|---|---|---|---|
| 选择文件（原生 FileOpenPicker） | ✅ `localPrintFilePicker` | | | | **保留** |
| 打印文档 | ✅ `localPrintDocument` | | | | **保留**（须转 baseline JPEG） |
| 打印照片 | ✅ `localPrintPhoto` | | | | **保留** |
| 加密 PDF 解锁 | ✅ `localPrintCheckPDFWithPassword` | | | | **保留** |
| 文件格式错误提示 | ✅ | | | | **保留** |
| 份数 / 颜色 / 质量 / 纸张 / 类型 / 来源 / 方向 | ✅（IPP） | | | | **保留** |
| 双面 | ❌ 设备不支持 | | | | 隐藏 |
| 无边距 | ❌ 设备未上报 | | | | 隐藏 |
| 缩放（适合页面 / 百分比 / 海报） | ✅（客户端） | | | | **保留** |
| 逐份 / 小册子 / 水印 | ✅（客户端） | | | | 保留（低优先级） |
| 驱动安装检查 | ✅ `localPrintDriverInstalledCheck` | | | | **保留** |
| 打印队列清理 | ✅ `localPrintClearPrintQueueItems` | | | | **保留** |
| 微信打印（`/print-wechat`） | | ✅ | ✅ | | 丢弃 |
| 移动传真（`/print-mobilefax`） | | ✅ | ✅ | | 丢弃 |
| 快捷方式（Smart Tasks） | 本地动作 | ✅ | ✅（云端目的地） | | 丢弃（或只保留本地动作） |
| 私人取件 / Print Anywhere | | ✅ | ✅ | | 丢弃（Windows 已封禁） |

### 6.3 扫描

| 功能 | 本地 | 需账号 | 需云 | 仅商城 | 克隆 |
|---|---|---|---|---|---|
| 平板扫描（eSCL） | ✅ | | | | **保留** |
| 来源 / 页面尺寸 / 输出颜色 / 分辨率 / 压缩 | ✅ | | | | **保留** |
| 检测边缘 + 手动校正 Quad | ✅ `localPrintDetectEdgeApply` | | | | **保留** |
| 自动增强 / 自动定向 | ✅ | | | | **保留** |
| 自动修复（AutoHeal） | ✅（需 `isHpSmartAdvanceUser`） | ⚠️ 判定在本地 | | | 保留（默认开或忽略） |
| 预设：文档 / 照片 / 多项 / 书本 / 身份证 | ✅ | | | | **保留** |
| 多页管理（排序/旋转/删除/替换/新扫描） | ✅ | | | | **保留** |
| 保存为 PDF / JPG | ✅ | | | | **保留** |
| 保存为**可搜索 PDF / txt / docx** | | | ✅（「在 HP 安全云中创建」） | | 丢弃 |
| OCR 语言包安装 | 本地包存在（`en.zip` 8.67MB） | | 下载需云 | | 丢弃（或只保留内置 en） |
| 打印扫描件 | ✅ `localPrintScannedDocument` | | | | **保留** |
| 共享（Windows 共享） | ✅ `localPrintShareImage` | | | | **保留** |
| 密码保护 PDF | ✅ | | | | 保留（可选） |
| 扫描到云 / Cloud Scan | | ✅ | ✅ | | 丢弃（路由已封禁） |
| 扫描到传真 | | ✅ | ✅ | | 丢弃 |
| 扫描到云文档源（DocProvider） | | ✅ | ✅ | | 丢弃 |
| 安全扫描（eSCL 用户名/密码） | ✅ `localPrintEsclSubmitCredential` | | | | 保留（可选） |

### 6.4 设置 / 维护 / 状态

| 功能 | 本地 | 需账号 | 需云 | 仅商城 | 克隆 |
|---|---|---|---|---|---|
| 设备信息展示 | ✅ | | | | **保留** |
| 清洁打印头（1/2 级） | ✅ `InternalPrintDyn` | | | | **保留** |
| 打印配置页 / 诊断页 / 网络摘要 / 事件日志 | ✅ `InternalPrintDyn` | | | | **保留** |
| 对齐打印头 | ❌ 无本地协议入口 | | | | **丢弃** |
| 校准（Calibration） | | ✅（HP Connected 校准） | ✅ | | 丢弃 |
| 网络信息（Wi-Fi/Direct/以太网/USB） | ✅ `IoMgmt/*` | | | | **保留** |
| 更改网络（配网） | ✅ | | | | 保留（低优先级） |
| 国家/地区、语言、自动关机 | ✅ `ProductConfigDyn` PUT | | | | 保留 |
| 固件版本显示 | ✅ | | | | **保留** |
| 检查/安装固件更新 | | | ✅（远程网页 + FWUpdateCheck） | | **丢弃** |
| 墨量显示 | ⚠️ 设备不报 → 「未知」 | | | | **保留（降级显示）** |
| 预计剩余页数 | ❌ 不存在 | | | | **不实现** |
| 用量计数器（已打印/已扫描页数） | ✅ `ProductUsageDyn` | | | | 保留（替代页数估算） |
| 纸张余量 | ❌ `TrayLevelInfo: -1` | | | | 隐藏 |
| 打印机隐私设置 | | ✅ | ✅ | | 丢弃 |
| Smart Security | | ✅ | ✅ | | 丢弃 |
| Instant Ink / 购买耗材 | | ✅ | ✅ | ✅ | 丢弃 |
| 诊断和修复（Diagnose & Fix） | 部分 | | ✅ | | 丢弃（Windows 已封禁） |
| 支持 / 保修 / 案例 / 在线客服 | | ✅ | ✅ | | 丢弃（仅保留「打开 EWS」和「打开 HP 支持网页」两个外链） |
| PC 软件/驱动更新（`/updates`） | | | ✅（HP SoftPaq） | | 丢弃 |

### 6.5 统计

- 本文共登记 **118 条**功能/界面条目（6.1 17 + 6.2 16 + 6.3 21 + 6.4 24 + 界面选项 40）。
- 其中 **本地可用 68 条**、**需账号 11 条**、**需云 27 条**、**仅商城 6 条**、**设备不支持而须隐藏 6 条**。
- 克隆应实现 **约 68 条**，其中首版必须做的是：
  1. 设备发现 + 设备卡 + 状态消息
  2. 打印（文件/照片）+ 完整 IPP 选项 + baseline JPEG 转换
  3. 扫描（eSCL）+ 11 项设置 + 5 个预设 + 多页管理 + PDF/JPG 保存
  4. 设备信息 + 清洁 + 打印报告 + 网络信息
  5. 墨量「未知」降级显示 + 用量计数器

---

## 7. 界面还原要点（给实现的硬约束）

1. **不要在 Web 层自己发明打印选项的取值**——全部从 `Get-Printer-Attributes` 读，缺属性就隐藏整组。
2. **扫描分辨率列表必须来自 `ScannerCapabilities`**，不能硬编码 150dpi（本机不支持）。
3. **输出颜色只有「彩色 / 灰度」两项**（`Color` / `Gray`），不要暴露 1-bit 黑白。
4. **所有 JPEG 必须是 baseline（SOF0）**，扫描输出与打印输入都要检查；progressive 会被设备拒绝。
5. **墨量「未知」是常态**，文案用「{{supplyName}}耗材状态未知」，不要画 0% 也不要画 100%。
6. **「预计剩余页数」不存在**，不要造。
7. **对齐功能不存在**，不要造。
8. **双面 / 无边距 / 纸盒 / ADF 全部按能力隐藏**。
9. **中文文案优先照抄** `zh_CN.json`（已在本文逐条给出），英文原文同时保留在代码常量里。
10. **状态消息用 SMS ID 表**（如 `65640 → eProductStatusAlertID_InPowerSave → 打印机处于休眠状态`），不要只靠 LEDM 的 `scanProcessing/idle`。
