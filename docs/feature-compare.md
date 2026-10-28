# myHP vs 我们：功能对比矩阵

> 只读逆向产物。仅列**有证据**的行；无证据的标注「未确认」。
> 证据缩写见 §0。HP 侧 = 新版 myHP `61.52637.14262.0`；我们 = `C:\Users\seakura\opencode\hp-offline\app`。

---

## 0. 证据源

| 短名 | 路径 |
|---|---|
| `MFE\*` | `C:\Program Files\WindowsApps\AD2F1837.myHP_61.52637.14262.0_x64__v10z8vjag6ke6\Weblets\webapps\root-web-mfe\assets\mfe\@hpx-core-experiences\<name>\<name>.js` |
| `LOCALE` | 各 MFE 下 `assets\locale\zh_CN.json`（真实文案） |
| `TRANSLATIONS` | `...\HP.Print.Printing\Assets\translations.json`（原生 My Print UI 文案） |
| `HPX` | `...\HP.HPX.dll`（UTF-16 字符串，含 `HP.Print.*` / `IPPProtocol` / `ExtractAndEnhanceImage`） |
| `RECON` | `C:\Users\seakura\opencode\hp-offline\docs\recon_*.xml`（本项目对真机的 LEDM 能力抓取） |
| `APP` | `C:\Users\seakura\opencode\hp-offline\app\hp\{ipp,render,service,ledm,escl,postprocess}.py`、`app\ui\js\views\print\*.js` |

MFE 清单（本机实际存在，共 60+）：`react-print-mfe`、`react-print-photos-mfe`、`react-print-documents-mfe`、`react-print-scan-home-mfe`、`react-print-scan-edit-mfe`、`react-print-scan-results-mfe`、`react-print-scan-detect-edge-mfe`、`react-print-shortcuts-mfe`、`react-print-printerinfo-mfe`、`react-print-mobilefax-mfe`、`react-print-wechat-mfe`、`react-print-driver-install-mfe`、`react-print-switchback-hpsmart-mfe`、`react-supply-levels-mfe`、`react-printer-settings-mfe`、`react-device-health-mfe`、`react-diagnostics-mfe`、`react-support-*`。

---

## 1. 打印

| 功能 | HP 应用 | 我们 | 差距 | 建议 |
|---|---|---|---|---|
| 打印入口 | 打印首页三卡片 `PHOTOS / DOCUMENTS / PRINTABLES`（`MFE\react-print-mfe` 字符串池） | 单/批量/编辑三个视图（`views\print\single.js`、`batch.js`、`edit.js`） | HP 多「PRINTABLES」类目（云端模板/可打印内容）；我们无 | P2：不追 |
| 照片打印 | 原生 My Print：`psPhotoSize` 14 个「尺寸 on 纸张」预设、`psLayout` 单/多图每页、`Crop`/`Full Page`、预览不可用态（`TRANSLATIONS` + `HPX` @61368050/@60969450） | `options.js`：方向/缩放(fit·fill·actual)/纸张/彩色/质量/份数/亮度/自动优化/页码 | 我们**缺**照片尺寸独立维度、多图每页、无边距；**多**亮度滑杆与自动增强 | **P0**：补 `media-col` 与照片尺寸预设；P2：多图每页 |
| 文档打印 | `Simple PDF print`；`psRange` All/Current/Range（`1,3,5-8`）、`Shrink to fit`、PDF 密码（`localPrintCheckPDFWithPassword` / `localPrintPdfpasswordInput`，`MFE\react-print-documents-mfe`） | `render.py::render_pages` 支持 PDF/图片、页选择（All/单页）、质量/色彩/缩放；**PDF 密码未支持** | 缺 Range 输入、缺 PDF 密码 | P1：Range 正则已有参考 `^\s*\d+\s*(-\s*\d+\s*)?(,\s*\d+\s*(-\s*\d+\s*)?)*$`；P2：PDF 密码 |
| 批量打印 | 多选 → `imagePathCollection[]` → 一次任务（`printLocalPrintPhoto(imagePathCollection)`） | `views\print\batch.js` + `service.py::start_print`（多文件） | 基本对齐 | — |
| 打印预览 | 原生 canvas 合成（`GeneratePage canvas` / `CreatePreviewPage`），放不下则 `PrintService_PreviewUnavailable` | 前端预览 + 后端渲染（`render.py::preview`） | HP 更严格（拒绝而非拉伸） | P2 |
| 打印选项：份数 | `PrintSettings.NumberOfCopies` 存在；UI 文案未见于 `TRANSLATIONS` → **未确认** | `options.js` stepper 1–99 | 未确认 | 抓 UI 截图 |
| 打印选项：无边距 | `Bordering` option + `BorderlessOptionAvailable` / `borderless enabled : {0}`（`HPX` @60894582） | 无 | 缺 | P2（取决于机型） |
| 打印选项：双面 | `DuplexPrinting` / `duplex` option（`HPX` @61368050、@60894582） | 无 | 缺 | P2 |
| 打印选项：进纸盒 | `InputBin is …`（`HPX` @61368050） | 无 | 缺 | P2 |
| 图像增强 | **打印路径无增强**（`DocEnhance` 仅扫描 `ExtractAndEnhanceImage`；`HPPageLift` 在 `HPX` 0 命中） | `render.py::_enhance_photo`（autocontrast + gamma 0.92 提亮 + 饱和 1.05 + USM），默认开 | 我们多做一步 | **P0**：默认关闭或降权，先对齐观感 |
| 传输格式 | `application/PCLm` @300（`HPX` @60117798，`IppProductInfoConfig.cs`） | baseline JPEG @300（`ipp.py` 默认 `document_format="image/jpeg"`、`render.py::JPEG_QUALITY`） | 成像分支不同 | **P0**：见 `re-hp-print-flow.md` §6 |
| Job 属性 | `copies, sides, print-color-mode, print-scaling, ipp-attribute-fidelity, media-col{media-type,media-size,margins,source}, orientation-requested, page-ranges, multiple-document-handling, number-up, page-delivery, hp-print-quality, print-quality, hp-pc-version-major/minor, hp-sierra-api-version`（`HPX` @60076337 / @61855702 / @60083954） | `copies, print-color-mode, print-quality, media, print-content-optimize`（`ipp.py:933-940`） | **缺 9 项**，其中 `media-col`/`print-scaling` 影响成像 | **P0**：补 `media-col` + `print-scaling`；P1：`sides`/`orientation-requested` |
| 格式探测 | 读 `document-format-supported` / `urf-supported` / `epcl-version-supported` 后决策（`HPX` @60081078） | 读 `document-format-supported`、`print-color-mode-supported`（`ipp.py:814-817`） | 我们不读 `urf-supported` / `epcl-version-supported` | P1 |
| 其他打印渠道 | 微信打印（`react-print-wechat-mfe`）、移动传真（`react-print-mobilefax-mfe`）、打印快捷方式（`react-print-shortcuts-mfe`）、驱动安装（`react-print-driver-install-mfe`） | 无 | 差距大 | P2：不追 |

---

## 2. 扫描

| 功能 | HP 应用 | 我们 | 差距 | 建议 |
|---|---|---|---|---|
| 扫描入口 | `react-print-scan-home-mfe`（175 KB）→ `scan-detect-edge` → `scan-edit` → `scan-results`，四段式 | `service.py::start_scan` / `_run_scan` + `escl.py::scan` | 流程对齐 | — |
| 自动裁边 | 独立 MFE `react-print-scan-detect-edge-mfe`（`brightness`/`gamma` 命中） | `postprocess.py::auto_crop`（margin=8, threshold=244）+ `auto_deskew`（max 6°） | 我们裁边+纠偏合并；HP 分步 | P2 |
| 编辑（亮度/伽马/锐化） | `react-print-scan-edit-mfe` 含 `brightness` / `gamma` / `sharpen`（2.1 MB bundle） | 无交互式编辑；仅 `auto_enhance` 自动 | 缺手动编辑 | P2 |
| 自动增强 | `ExtractAndEnhanceImage` + `DocEnhanceImage` + `BookDewarpHPScanAsync` + `SingleImageDetect(ISIDcardScan/DetectQuad)`（`HPX` @60960451，`HPPageLift.UWP.dll` 提供 TFLite `DocEnhance`） | `postprocess.py::auto_enhance`（denoise）、`compose_id_card`、`compose_nup` | HP 有书籍去弯/证件识别/自动文档识别；我们只有证件拼版 | P1（书籍去弯不追，P2） |
| OCR | `react-print-scan-results-mfe` 中 `OCR` 29 次命中 | `postprocess.py::ocr_images`（PaddleOCR 子进程，中/英） | 能力对齐（引擎不同） | — |
| PDF 输出 | 结果页 `PDF` 16 次命中，`compress` 6 次 | `postprocess.py::to_pdf`（PyMuPDF，`resolution=dpi`） | 对齐 | — |
| PDF 加密 | 结果页 `password` 17 次 / `Password` 13 次命中 | `to_pdf(password=...)` → `PDF_ENCRYPT_AES_256` | 对齐（我们 AES-256） | — |
| 扫描后直接打印 | `PRINT_FROM_SCAN` → `printLocalPrintPhoto`（`MFE\react-print-photos-mfe` @50780） | 无（扫描→保存→再进打印） | 缺一步 | P2 |
| 扫描仪协议 | 未在 JS 中暴露（原生 `HPScan.dll` 23.6 MB） | eSCL（`escl.py`） | 实现不同，效果等价 | — |

---

## 3. 复印

| 功能 | HP 应用 | 我们 | 差距 | 建议 |
|---|---|---|---|---|
| 复印 | 设备侧能力存在于 `RECON\recon_Copy_CopyManifest.xml`（3,674 B）；新版 myHP 的 MFE 列表中**无 copy MFE** → 复印可能仍在旧 HP Smart / 设备网页 | `service.py::copy`（568 行）+ eSCL/LEDM | 我们**有**，HP 新版主 UI 未见 | P2：可作为差异化 |
| 复印选项 | 未确认（`CopyManifest.xml` 仅证明设备支持） | `service.py:761` 默认 `{copies:1, color:"auto", quality:"normal", dpi:300}` | 未确认 | 读 `CopyManifest.xml` 细项 |

---

## 4. 维护（清洗/对齐/校准/报告）

| 功能 | HP 应用 | 我们 | 差距 | 建议 |
|---|---|---|---|---|
| 校准状态 | `HPX` `CalibrationStateHelper.GetCalibrationState/SetCalibrationState/GetManualSupportedPatterns`（`Ledm\CalibrationStateHelper.cs`） | `ledm.py::calibration_state`（**只读状态**） | 我们**不能执行**校准 | P1：补 `SetCalibrationState` |
| 清洗/对齐 | `RECON\recon_Utilities_UtilitiesManifest.xml`（3,438 B）、`recon_Calibration_CalibrationManifest.xml`（2,892 B）证明设备侧有 Utilities/Calibration 能力；myHP 通过 `react-diagnostics-mfe`（`/app.printer.diagnostics-print-quality-tools`，见 `HPX` @62199679） | 无 | 缺 | P1 |
| 诊断/修复 | `react-diagnostics-mfe`、`react-device-health-mfe`、`react-support-diagnostics-mfe` | 无 | 缺 | P2 |
| 打印质量工具 | `HPX` @62199679 路由 `/app.printer.diagnostics-print-quality-tools` | 无 | 缺 | P2 |
| 报告 | `RECON\recon_DevMgmt_*.xml`（ProductConfig/ProductStatus/ConsumableConfig/MediaHandling 四份，合计 60 KB） | `ledm.py::reports`、`service.py::reports` | 我们读得到，UI 覆盖未确认 | P2 |

---

## 5. 耗材 / 状态

| 功能 | HP 应用 | 我们 | 差距 | 建议 |
|---|---|---|---|---|
| 耗材水位 | `react-supply-levels-mfe`（含 `print-quality` 命中于 `chunks\747.js`） | `ledm.py::consumables` | 对齐 | — |
| 设备状态 | `react-device-statuses-mfe`、`react-device-status-messages-sms-mfe`、`react-device-health-mfe` | `ledm.py::product_status`、`service.py::status/_build_status` | 对齐；HP 多 SMS 状态消息 | P2 |
| 状态原因码 | `HPX` `***LEDM/CDM status***` / `***IPP status***` / `GetDeviceStatus prioritizedStateReason=`（双通道） | `ledm.py` + `ipp.py` | 对齐（我们也双通道） | — |
| 耗材订购 | `react-supply-levels-mfe` + 云订阅（`SUBSCRIBED_NO_PRINTER`、`instant-paper`、`Paper add-on included`，`MFE\react-print-mfe`） | 无 | 云功能 | 不做 |

---

## 6. 任务 / 历史

| 功能 | HP 应用 | 我们 | 差距 | 建议 |
|---|---|---|---|---|
| 任务列表 | `RECON\recon_Jobs_JobsManifest.xml`（3,823 B）；`HPX` `GetPrintJobStatus` / `job-state-reasons` / `job-impressions-completed` / `job-media-sheets-completed` | `service.py::list_jobs` / `get_job`（含 `_reconcile_orphan_jobs`） | 对齐 | — |
| 任务控制 | `HPX` `CancelPrintJob` / `IPPProtocol::CancelPrintJob`；`Resume` + `UserOptIn` 开关（@61855702） | `cancel_job` / `pause_job` / `resume_job` / `retry_job` | 我们多 `retry` | — |
| 历史 | 未确认（未见 history MFE） | `docs\shot-history.png` 表明我们有历史页 | 未确认 | — |

---

## 7. 设置 / 语言

| 功能 | HP 应用 | 我们 | 差距 | 建议 |
|---|---|---|---|---|
| 打印机设置 | `react-printer-settings-mfe`、`HP.Framework.Extensions.PrinterSettings`、`RECON\recon_DevMgmt_MediaHandlingCap.xml` | 无独立设置页（未确认） | 可能缺 | P1 |
| 应用语言 | 每个 MFE 独立 `assets\locale\*.json`，37 个语种（`ar_SA … zh_TW`），但照片 MFE 的 locale 只有 1 个 key `FileFormatErrorScreen` | 中文为主（`docs\i18n-strings.txt` 5,147 B） | HP 37 语种 | P2 |
| 特性开关 | LaunchDarkly：`printer-x-localprint`（`MFE\react-print-photos-mfe` @53818）、`Config\launchdarkly-flags.json`（1.44 MB） | 无 | 架构差异 | 不做 |

---

## 8. 云功能（明确不做）

| 功能 | HP 应用证据 | 我们 |
|---|---|---|
| 云打印 / 远程打印 | `roam-release-intent`（`HPX` @60076337）、`UploadToStorageAsync` / `storageUrl` / `upload_url` / `CreateJobAsync:PostAsync()`（@62686948）、`react-print-driver-install-mfe` | 不做 |
| 云端 AI 打印卡片 | `aiPrint/cardGeneration`、`assets/images/AIPopup.png`（`MFE\react-print-mfe`） | 不做 |
| Instant Ink / 纸张订阅 | `instant-paper`、`Paper add-on included`、`SUBSCRIBED_NO_PRINTER`（`MFE\react-print-mfe`） | 不做 |
| 账号 / 组织选择 | `react-account-mfe`、`react-orgselector-mfe`、`react-consents-mfe` | 不做 |
| 遥测 | `SendPrintBasicTasktoTelemetry`（`HPX` @61368050） | 不做 |
| 远程诊断 / 支持聊天 | `react-support-chat-mfe`、`react-support-va-mfe`、`react-cep-mfe` | 不做 |

---

## 9. 差距汇总（按影响排序）

| 级别 | 差距 | 影响 | 依据 |
|---|---|---|---|
| **P0** | Job 属性缺 `media-col`（`media-type`/`media-size{x,y}`/`margins`/`media-source`） | 打印机按普通纸成像 → 观感/亮度不一致 | `HPX` @60083954 vs `ipp.py:936` |
| **P0** | 图像增强默认开启（gamma 0.92 提亮 + autocontrast） | 与 HP 无增强路径相反，掩盖真实差异、难以对齐 | `options.js` `auto_enhance !== false` vs `HPX` 无打印增强 |
| **P0** | 编码格式 JPEG 直传 vs `application/PCLm`@300 | 固件成像分支不同 | `ipp.py` vs `HPX` @60117798 |
| **P1** | 缺 `print-scaling` / `ipp-attribute-fidelity` / `sides` / `orientation-requested` / `hp-print-quality` | 缩放与双面行为由固件默认决定 | `HPX` @61855702 / @60076337 |
| **P1** | 缺照片尺寸独立维度（14 个「尺寸 on 纸张」预设） | 小尺寸排版语义不明确 | `TRANSLATIONS` |
| **P1** | 缺页范围 Range（`1,3,5-8`） | 文档打印粒度不足 | `TRANSLATIONS` `PrintService_PrintRange*` |
| **P1** | 不能执行校准/清洗/对齐（只读状态） | 维护能力不完整 | `ledm.py::calibration_state` vs `HPX` `SetCalibrationState` |
| **P1** | 不读 `urf-supported` / `epcl-version-supported` | 无法按设备能力选格式 | `HPX` @60081078 |
| **P2** | 无边距 / 进纸盒 / 双面 / 多图每页 / PDF 密码 / 扫描后直打 / 手动扫描编辑 | 体验完整度 | 见各节 |
| **P2** | 37 语种 vs 中文单语 | 国际化 | `LOCALE` |

---

## 10. 未确认项

| ID | 内容 |
|---|---|
| F-1 | 份数是否在 My Print UI 中可调（`TRANSLATIONS` 无文案，但 `PrintSettings.NumberOfCopies` 存在） |
| F-2 | 新版 myHP 是否有「复印」入口（MFE 列表无 copy，但设备侧 `CopyManifest.xml` 存在） |
| F-3 | 任务历史页是否存在（未见 history MFE；`shot-history.png` 是我们的实现） |
| F-4 | 打印机设置页覆盖范围（`react-printer-settings-mfe` 未展开读） |
| F-5 | 扫描 `OCR` 用的是本地引擎还是云（`scan-results-mfe` 有 29 次命中但未定位实现） |
| F-6 | `react-print-shortcuts-mfe`（打印快捷方式）的具体能力 |
