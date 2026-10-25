# 官方应用的云依赖证据链（为什么离线不可用）

> 取证对象：本机安装的两个 MSIX 应用 + 其运行时数据。
> **本文件不含任何对 HP 服务器的请求**：全部结论来自磁盘上的静态文件与本地运行时缓存。
>
> 简写同 `spec-features.md`：`SMART` / `MYHP` / `MFE` / `ROOT` / `LS_SMART` / `LS_MYHP` / `RECON`。

---

## 0. 一句话结论

两个应用都是**「本地功能 + 云端外壳」的混合体**：
打印、扫描、状态、耗材、设备信息这些**动作本身完全在局域网内完成**（IPP / eSCL / LEDM），
但**应用外壳、登录、特性开关、埋点、内容、商店、固件、传真、云扫描、OCR 转文本**全部指向 HP 云。
所以「离线不能用」不是能力问题，而是**产品设计上的强制联网**：
外壳从远程加载、登录走 OIDC、每个 UI 区块是否显示由 LaunchDarkly 决定、每次操作都上报 Splunk/Datadog。

关键量化：

| 指标 | 数值 | 来源 |
|---|---|---|
| myHP 声明的允许外联域名（AppxManifest） | **64 条** `uap:Rule Type="include"` | `MYHP\AppxManifest.xml` |
| HP Smart 声明的允许外联域名 | **40 条** | `SMART\AppxManifest.xml` |
| 两个应用 JS/JSON 中出现的 HP 域名 | **34 个**（688 次 `static.hpsmart.com`） | 全量扫描 `ROOT` 下 3667 个文件 / 73.6 MB |
| 全量绝对 URL 中出现的不同主机 | **118 个** | 同上 |
| 打包进安装包的 LaunchDarkly 开关 | **373 个** | `MYHP\Config\launchdarkly-flags.json` |
| 运行时生效的特性开关 | **367 个** | `LS_MYHP\AsyncStorage.db` → `@hp-af/feature-switch/features` |
| Web 层 GraphQL 操作（全部） | **483 个**（其中 `localPrint*` **127 个**） | `ROOT` 下 381 个 JS |
| Windows 端被显式封禁的云路由 | **28 条** | `MYHP\Config\webapps_prod\manifest.json` → `services.navigation.blockNavigation.pathList` |

---

## 1. 端点清单（按用途分组）

### 1.1 认证 / 身份（auth）

**两个令牌签发方**，由 JWT `iss` 区分（`MFE\@clientos\commons-northbound-api\…js`）：

```js
Cr = token => { const iss = decodeJWTPayload(token)?.iss;
  return iss.includes("authz.wpp.api.hp.com") ? "authz"
       : iss.includes("oc.hp.com")            ? "coptor" : null }
```
`manifest.json` 指定 `services.login.authenticationProvider = "coptor"`。

| 主机 | 角色 | 依据 |
|---|---|---|
| `login3.id.hp.com` / `login3.stg.cd.id.hp.com` | OIDC 登录页 | `MYHP\AppxManifest.xml` |
| `directory.id.hp.com` / `directory.stg.cd.id.hp.com` | 身份目录 | 同上 |
| `oauth-auth.oc.hp.com` / `oauth-auth.stg.oc.hp.com` | HP Connected (coptor) OAuth | 同上 |
| `authz.api.ws-hp.com` / `authz.stage.api.ws-hp.com` / `pie.authz.wpp.api.hp.com` / `authz.wpp.api.hp.com` | authz 签发方 + OIDC logout | `commons-northbound-api.js`（`configureLogoutUrl` 硬编码这三档） |
| `account.hp.com` / `myaccount.hp.com` / `stage.myaccount.hp.com` | 账号中心 | `MYHP\AppxManifest.xml` |
| `us1.api.ws-hp.com` / `stage-us1.api.ws-hp.com` / `pie-us1.api.ws-hp.com` / `dev-us1.api.ws-hp.com` | UC De 账号/租户/用户管理 | `commons-northbound-api.js` |
| `hpsa-redirectors.hpcloud.hp.com` | HP Smart 重定向器 | 域名扫描 |
| `jees.hp8.us` / `jees-stage.hp8.us` / `jees-pie.hp8.us` / `sws.hp8.us` / `sws.stage.hp8.us` | JWT/会话服务 | `MYHP\AppxManifest.xml` |

**路径**（全部从 JS 字符串常量提取）：

```
/api/session/v1/token              /api/session/v2/token
/api/session/v1/exchangetoken      /api/session/v2/exchangetoken
/api/session/v1/exchangetenanttoken  /api/session/v2/exchangetenanttoken
/api/session/v2/exchangetoken/tenants/
/api/session/v1/logout             /api/session/v1/provider
/session/v1/scopes                 /session/v1/validate-actions
/v1/sessions                       /v1/logout
/.well-known/openid-configuration  /id-config/v1
/openid/v1/logout?id_token_hint=…&post_logout_redirect_uri=…
```

**UC De 服务**（`us1.api.ws-hp.com`）：
```
/ucde/ucde/v1|v2|v3/ecosystem/accountmgtsvc
/ucde/ucde/v1|v2/ecosystem/uimgtsvc
/ucde/ucde/v1/ecosystem/configurationmgtsvc/programs
/ucde/ucde/v2/ecosystem/programmgtsvc
/ucde/ucde/v2/ecosystem/accountmgtsvc/accounts
/v2/sessionmgtsvc   /v2/tenantmgtsvc   /v2|v3/usermgtsvc
/v2/consentmgtsvc   /v2/consentmgtsvc/purposes
/v2/eventmgtsvc     /v2/grant-controller
/tenancy-registry/v1/person   /v1/person   /v1/collections
/users/me   /v3/usermgtsvc/userwithtenantdetails/me
/deviceauthgrant/v1   /v1/ownerships
/v3/solutionregistrysvc/{softwareproducts,uiextensioninfos,uiinfos}
/v2/catalogmgtsvc/{offerings,pricing-plans,deviceprogramsubscriptions}
/v3/commercemgtsvc
```

**OAuth 授权范围（硬编码在应用里）** —— `LS_MYHP\AsyncStorage.db` → `clientOSAdditionalAuthorizationParams`：
```json
{"config_id":"0c962637-6bfb-4acc-976d-8e2f6aa04dbc","theme_id":"hpapp",
 "consent":"groups=1:0,2:0,4:0,3:0",
 "appInstanceID":"8fcd7d20-8a5c-4d4e-91ce-70b7fcd4fcaf",
 "authorization_details":"[{\"type\":\"instantink_existing\",
   \"actions\":[\"instantink/comfe/billing-method.PUT\",\"instantink/comfe/shipping-address.PUT\",
                \"instantink/comfe/invoices.GET\",\"instantink/gemini/plan.PUT\"],
   \"locations\":[\"https://instant-ink.oc.hp.com\"]}]"}
```
→ **应用默认申请了「读取发票 + 修改账单方式 + 修改收货地址 + 修改套餐」的 Instant Ink 权限**，
即使你从不订阅。这是纯云端功能，与本地打印无关。

### 1.2 设备指令中继 / 设备云（device-command relay）

| 主机 | 角色 |
|---|---|
| `api.hpsmart.com` / `api.hpsmartstage.com` / `api.hpsmartdev.com` / `api.hpsmartpie.com` | 设备云 REST |
| `hpx.hpsmart.com` / `*.hpx.hpsmart.com` / `www.hpx.hpsmart.com` / `*.hpx.hpsmart.cn` / `hpx.*.portalshell.int.hp.com` | **应用外壳托管**（整个 SPA 从这里加载） |
| `portal.hpsmart.com` / `www.hpsmart.com` / `www.hpsmartpie.com` / `www.hpsmartstage.com` | 门户 |
| `*.hp-smart.cn` / `*.hp-smartstage.cn` | 中国区 |
| `*.hp-mns.com` / `hp-mns.com` | MNS（托管打印 / Instant Ink） |
| `*.hpinstantink.com` / `platinum.hpinstantink.com` | 订阅 |
| `mobilefax.{dev-,pie-,stage-,}us1.api.ws-hp.com` | 移动传真 |
| `scribble.ext.hp.com` (+`-dev`/`-pie`/`-stage`) / `scribble-mfe.stg.mobilefax.ext.hp.com` | 传真/图像标注服务 |
| `*.eprintsw.com` / `api.eprintsw.com` / `api-dev.eprintsw.com` / `api-test.eprintsw.com` / `static.eprintsw.com` | ePrint |
| `roam.api.hp.com` | HP Roam（异地打印） |
| `*.hpconnected.com` / `*.hpconnectedpie.com` / `*.hpconnectedstage.com` / `*.hp-connected.cn` / `*.hp-connectedstage.cn` | HP Connected（旧版） |
| `*.hpalpine.com` / `*.*.hpalpine.com` | HP 渠道服务 |
| `hpesign.com` / `fd-hpesignature-sdx.azurefd.net` / `fd-hpesignature-uat.azurefd.net` | 签名服务 |

**路径**：
```
/devices/v1                       /devices/v2
/devices/v1/FWUpdateCheck         /devices/v1/rtpCredentials
/devices/v1/models                /devicecache/v1
/device-transfer/transfer/v1      /hpip-devices-search/v1
/firmware-update-config/v1
/print-psamigration  /migrateduser  /addprinter  /psalauncher
/1/api/engagements/               /2/api/engagements/
/1/api/mastiff/offerClicked/      /2/api/secondary-page/
/api/aggregation/graphql
/atlas/v1/me/messages             /atlas/v1/me/messages/{messageId}
/atlas/v1/me/messages/{messageId}/setRead
```

**「设备指令中继」的实际含义**：本机设备的控制不走这里 —— `localPrint*` 127 个操作全在原生层。
云端 `/devices/*` 只负责：**云端设备清单（`devices-x-discovery-cloud`）、固件检查、RTP 凭证（远程打印）、
模型元数据、设备迁移**。也就是说：**打印机可以被本地完全控制，但应用不让你只走本地。**

### 1.3 遥测（telemetry）—— 5 家第三方 + 2 套自研

| 厂商 | 主机 / 入口 | 证据 |
|---|---|---|
| **Splunk RUM** | `rum-ingest.us1.signalfx.com` | `manifest.json` → `services.splunk = {enabled:true, rumAuth:"UTOM3i-JMZLpo-rrAsC6Cw"}`（**令牌硬编码在发行包**） |
| **Datadog RUM** | `static.hpsmart.com/jarvis/shell-assets/1.0.2/datadog/6.28.1/datadog-rum.js` | `ROOT\index.html` 第 180 行，`<script src=… crossorigin="anonymous">` **无条件加载** |
| **LaunchDarkly** | `clientstream.launchdarkly.com` / `events.launchdarkly.com` / `app.launchdarkly.com` | `manifest.json` → `services.featureFlags.clients[0].clientId = "64e62df7c0fc221439184893"` |
| **DynamicYield** | `cdn.dynamicyield.com` / `st.dynamicyield.com` / `rcom.dynamicyield.com` | 域名扫描 |
| **Optimizely** | `cdn.optimizely.com` | 域名扫描 + `react-settings-mfe` 隐私页列出 |
| **Qualtrics** | `sjc1.qualtrics.com` / `hpcommunity.qualtrics.com` | 域名扫描（问卷/退出调查） |
| **Google Analytics** | — | `react-settings-mfe` 隐私页 `appImprovement.googleAnalytics` |
| **HP 自研** | `telemetry/v1`、`clienttelemetry/v1`、`telemetry/user`、`telemetry/client` | JS 路径常量 |
| **HP 分析 schema 注册** | `schemaregistry.analysis.ext.hp.com` | 域名扫描（10 次） |

埋点事件名：`manifest.json` → `services.analytics = {enable:true, customAnalyticsSubsystem:{eventName:"hpx-windows-analytics"}}`。
另有 `CEC`（Customer Engagement Center，内容个性化）：
`cec.hpsmart.com` / `cec.hpsmartstage.com` / `cec.hpsmartpie.com`，本机实际访问记录见 §3。

### 1.4 内容 / CDN

| 主机 | 用途 | 引用次数 |
|---|---|---|
| `static.hpsmart.com` | **微前端 + 框架 + 固件更新页 + Datadog** | 688 次 / 100 个文件 |
| `static.tropos-rnd.com` / `static-dev.tropos-rnd.com` / `*.tropos-rnd.com` | 静态资源（含 dev 环境） | 域名扫描 |
| `support.hp.com` / `uat.support.hp.com` / `www.support.hp.com` | 支持页 | 217 / 9 / 3 |
| `www.hp.com`（`/privacy`、`/hp-app-ai-terms-of-use`、`/go/sweula`） | 法律/隐私/AI 条款 | 199 |
| `product-images.www8-hp.com` / `www8.hp.com` / `h20195.www2.hp.com` | 产品图 | 10 / 6 / 1 |
| `virtualagent.hpcloud.hp.com` / `virtualagent-stg.hpcloud.hp.com` | 在线客服（Virtual Agent） | 2 / 2 |
| `api3-methone.hpcloud.hp.com` / `api5-methone.hpcloud.hp.com` (+`-itg`) | 支持侧分析 | 2+2 |
| `res.cloudinary.com` / `cdn.lottielab.com` / `vjs.zencdn.net` / `cdnjs.cloudflare.com` / `www.jsdelivr.com` | 图片/动效/视频播放器 | 1–2 |
| `api.whatsapp.com` / `m.me` / `web.whatsapp.com` / `twitter.com` / `zalo.me` | 客服联系方式 | 2–4 |

**最重要的单点**：`ROOT\index.html` 里硬编码
```html
<script src="https://static.hpsmart.com/jarvis/shell-assets/1.0.2/datadog/6.28.1/datadog-rum.js" crossorigin="anonymous"></script>
```
→ **应用外壳第一行就联网**，且是不可关闭的 RUM。

### 1.5 商店 / 订阅

| 主机 | 用途 |
|---|---|
| `*.hpinstantink.com` / `platinum.hpinstantink.com` | Instant Ink 订阅（套餐、发票、纸张附加包） |
| `*.hp-mns.com` / `hp-mns.com` | MNS 托管打印（HP+ / 企业） |
| `www.hpsmartpie.com` / `hpsmartpie.cso-hp.com` | 商店前端 |
| `hpsmart.com`（`/supplies`、`/suppliesv3`） | 耗材商店（**Windows 端已在 `blockNavigation` 里封禁**） |
| `instant-ink.oc.hp.com` | Instant Ink 账户（OAuth `locations` 白名单） |

### 1.6 开发/测试遗留（攻击面）

以下**生产发行包**里存在，但只应用于内部环境：

| 主机 | 风险 |
|---|---|
| `http://localhost:8080` | WebView `ContentUriRule` 允许明文 localhost。**本机任何进程监听 :8080 即可向 WebView 注入内容。** |
| `test.pro.portalshell.int.hp.com` | **本机 myHP 实际从这里加载外壳**（见 §3） |
| `*.portalshell.int.hp.com` / `*.stg.` / `*.stage.` / `*.pie.` / `*.pro.` | 内部环境全量放行 |
| `static-dev.tropos-rnd.com` / `*.tropos-rnd.com` | 开发静态站 |
| `login3.stg.cd.id.hp.com` / `directory.stg.cd.id.hp.com` / `oauth-auth.stg.oc.hp.com` / `stage-us1.api.ws-hp.com` / `authz.stage.api.ws-hp.com` | 预发布认证链 |
| `api-dev.eprintsw.com` / `api-test.eprintsw.com` / `scribble-dev` / `scribble-stage` / `scribble-pie` | 开发/预发布 API |
| `github.azc.ext.hp.com` / `pages.github.azc.ext.hp.com` / `npm.github.azc.ext.hp.com` | 112 次引用（bundle 内残留的仓库/包链接） |
| `hpx.stg.hpsmart.com` / `hpx.stage.hpsmart.com` | 预发布外壳 |

> 通配规则 `https://*.hp.com` 与 `https://*.*.hpsmart.com` 意味着**任意** hp.com 子域都能在 WebView 内渲染。
> `WindowsRuntimeAccess="none"` 限制了 WinRT 能力，但**内容注入/钓鱼面仍然存在**。

---

## 2. 被服务端往返 gate 的用户动作（Top 证明清单）

判定方法：① 路由被 `blockNavigation` 封禁；② 功能开关为 `false`；③ 文案自证需登录/需云；④ 代码里存在 401/token 刷新/离线对话框分支。

| # | 动作 | 卡在哪 | 证据 |
|---|---|---|---|
| **1** | **登录 / 创建账号** | `/api/session/v2/token` → 失败即弹「无网络连接」 | `react-account-mfe\assets\locale\zh_CN.json`：`modal.title="无网络连接"`、`modal.description="我们现在无法为您登录。请检查您的连接并重试。"`；`react-offlinedialog-mfe` 同文案；`commons-northbound-api.js` 的 `isTokenExpiredOrExpiringSoon()` / `refreshToken()` → `POST /api/session/v2/token`（失败回落 `/api/session/v1/token`） |
| **2** | **扫描到云 / Cloud Scan** | 路由直接封禁 + 开关关闭 | `manifest.json` → `blockNavigation.pathList` 含 `/app.action.scan-to-cloud`、`/app.bell.cloud-scan`；`AsyncStorage` → `communications-x-bell-cloudscan: False`；HP Smart `ApplicationItems.xml` → `CloudScan` 带 `LockedWhenNoLogin` + `EnableWhenCloudScanEntitlementPresent` |
| **3** | **可搜索 PDF / TXT / DOCX 导出** | 文案自证「在 HP 安全云中创建」 | `react-print-scan-results-mfe\assets\locale\zh_CN.json`：`ConvertToTextFileTypes.Title="转换为文本文件类型"`、`ConvertToTextFileTypes.Desc="这些文件类型在 HP 安全云中创建"`；`LanguageDownloadFailedNetworkError.Text="由于网络错误，无法下载所选的语言。"` |
| **4** | **固件更新检查/安装** | UI 本身是一个远程网页 + 云端检查接口 | `LS_SMART\EBWebView\Default\History`：`https://static.hpsmart.com/jarvis/react-firmware-update-controller-pro/latest/index.html?appInstanceId=…`（访问 2 次）；JS 路径 `/devices/v1/FWUpdateCheck`、`/firmware-update-config/v1`；`printer-x-fwupdate: True` 但执行体在云 |
| **5** | **保修 / 订阅 / 金牌服务** | 需账号 token | `react-product-information-mfe\assets\locale\zh_CN.json`：`subscription_status.signIn="登录以查看范围状态"`、`subscription_status.notAssociated="订阅与此帐户无关"`、`warranty_status.pending="待定"`、`carepack_status.start="金牌服务"` |
| **6** | **移动传真** | 独立云端 API + 登录锁 | `mobilefax.{dev-,pie-,stage-,}us1.api.ws-hp.com`；`react-print-mobilefax-mfe`；`ApplicationItems.xml` → `SoftFax` 带 `LockedWhenNoLogin` + `EnableForHpcRegion`；`blockNavigation` 含 `/fax` |
| **7** | **私人取件 / Print Anywhere / 远程打印** | 三个路由封禁 + 云端凭证 | `blockNavigation` 含 `/app.printer.settings-private-pickup`、`/app.printer.settings-print-anywhere`、`/app.private-pickup-flow`、`/app.bell.print-anywhere`；`/devices/v1/rtpCredentials`（Remote Print 凭证）；`roam.api.hp.com`；`react-print-printerinfo-mfe` 文案「在远程连接状态下，您可以从任何位置进行打印…无法扫描或更改打印机设置」 |
| **8** | **快捷方式（Smart Tasks）到云端目的地** | 云端目的地 + 登录锁 | `SMART\...\ScanCapture\...xr.xml` → `SmartTaskHasCloudDestination`；`ApplicationItems.xml` → `SmartTasks` 带 `LockedWhenNoLogin`；`@shortcuts\react-bell-shortcuts-notifications-mfe\…js` 出现 `OneDrive` / `Google Drive` / `Dropbox` / `SharePoint`；`blockNavigation` 含 `/shortcuts` |
| **9** | **通知正文** | 本地只有计数，正文在 Atlas | `localNotificationChannels { attentionNeededCount, type }`（本地只有 badge 数）；正文走 `/atlas/v1/me/messages`、`/atlas/v1/me/messages/{id}/setRead`；`communications-x-bell-*` 系列开关；`react-bell-notifications-mfe` |
| **10** | **耗材购买 / 商店 / 订单跟踪** | 纯电商 | `blockNavigation` 含 `/supplies`、`/suppliesv3`；`ApplicationItems.xml` → `ShopForSupplies`；`devices.components.trackingCard.statusLabel={已确认/正在处理/已发货/已送达}`；`*.hpinstantink.com`、`*.hp-mns.com` |
| 11 | PC 软件/驱动更新 | HP SoftPaq 云 | `react-device-updates-mfe` 全量文案为 SoftPaq/BIOS/驱动；`updates.status.upToDate="您的软件和驱动程序已是最新版。"` |
| 12 | AI 助手 | 后端推理 | `localSendRequest(request)` 只是本地转发；`ai-x-core: False`（当前关闭） |
| 13 | 支持 / 在线客服 / 案例 / 保修 | 云 | `virtualagent.hpcloud.hp.com`、`support.hp.com`、`/support/{va,vaintents,omnichat,create-case,warranty,instantink}` |
| 14 | 云端设备发现 | `devices-x-discovery-cloud: True` | `api.hpsmart.com/devices/*`、`/hpip-devices-search/v1` |
| 15 | 个性化推荐 / 为你推荐 Tab | CEC + DynamicYield | `cec.hpsmart.com/1?appInstanceId=…&property=Smart%2bApp%2bWin&location=JWeb%2bView`（本机历史 2 次）；`/1/api/engagements/`、`/1/api/mastiff/offerClicked/` |
| 16 | 所有功能开关与埋点 | LD + Splunk + Datadog | 见 §1.3 |

---

## 3. 已经存在的「本地优先」回退路径（克隆应照抄这些行为）

这一节是**最重要的可实现性证据**：官方自己也留了离线路径，只是把入口藏在了登录之后。

### 3.1 路由层完全不拦登录

`manifest.json` 中 **80/80 条路由** 都是 `"public": true`。
`commons-northbound-api.js` 的判定逻辑：
```js
isLoginRequired(service) {
  if (service?.public) return false;              // 公开路由永不要求登录
  return !this._sessionService?.isLoggedIn?.();
}
```
→ **打印 / 扫描 / 设备页在协议上允许未登录访问。**

**实测佐证**：`LS_MYHP\LocalState\xfiles-session-snapshot.json`
```json
{"isSignedIn": false,
 "trail": "…~ready : devices:11:00:57,/devices:11:00:57,/print:11:00:59,…"}
```
→ 未登录状态下，启动流程走完了 `/devices` → `/print`。

### 3.2 开关已随包分发（离线可判定）

- `MYHP\Config\launchdarkly-flags.json`：**373 个** flag 的完整 bootstrap（含 `on`/`variations`/`segments`），安装包自带。
- `LS_MYHP\AsyncStorage.db` → `@hp-af/feature-switch/features` / `-native/processed-flags` / `@settings-local/…`：**367 个** 已解析值，三份副本互相兜底。
- `FEATURE_VISIBILITY_CACHE`：13 786 B，另一份 UI 可见性缓存。
- `featureVisibilityLastEventSentTimestamp`：上报时间戳 —— 说明有「离线期间先攒着」的机制。

### 3.3 外壳有本地副本

`ROOT\index.html` 内嵌 base64 manifest（解出后）：
```json
{"disablePrefetch":true,
 "portal":{"appName":"HPX Windows App","basePath":"/webapps/root-web-mfe",
           "fallbackRoute":"/index.html","stack":"prod","platform":"native-only"},
 …}
```
`platform: "native-only"` + 相对 `basePath` + 磁盘上完整的 `Weblets\webapps\root-web-mfe\`（含 381 个 JS、全部 locale）
→ **本地副本是完整可用的，只是默认没被用**（见 §3.4）。

### 3.4 设备数据全部落盘

| 文件 / key | 大小 | 内容 | 离线价值 |
|---|---|---|---|
| `LS_MYHP\RecentDeviceList.xml` | 5 430 B | 完整设备模型：身份、固件、MAC、IP、**两条 SupplyData**（含 `LevelState`/`SupplySeverity`）、`NetworkList` | 可完全离线渲染设备卡 + 耗材 |
| `LS_MYHP\SavedConsumables.json` | 869 B | 4 条耗材 + `LastSavedAt` | 耗材快照 |
| `LS_MYHP\scanSettings.json` | 364 B | 15 个扫描设置字段 | 扫描页可离线恢复上次设置 |
| `LS_MYHP\HPPrinterControlSettings.xml` | 1 539 B | 7 条设置（含 consent URL 路径、`AlpacaId`） | 应用设置 |
| `AsyncStorage` → `HP.DeviceController.LocalDevicesCache` | 2 764 B | 设备 + `SmsStatusMessages`（中文标题/描述） | 设备卡 + 状态消息 |
| `AsyncStorage` → `HP.DeviceController.DeviceNicknames` | 120 B | 昵称映射 | 昵称 |
| `AsyncStorage` → `HP.DeviceController.DeviceTypeCounters` | 20 B | `{"PRINTER":1,"PC":1}` | 设备计数 |
| `LS_SMART\ModelNameMapper.xml` | 269 611 B | 型号 → 名称/能力映射表 | 本地型号识别 |
| `HashStore.json` | 163 B | `ModelNameMapperFile_SHA1_hash`、`SortedTilesFile_SHA1_hash` | 本地文件完整性校验（说明设计上支持离线使用本地副本） |
| `SortedTilesSha1.txt` | 40 B | `SortedTiles.xml` 的 SHA1 | 同上 |

### 3.5 状态文案本地化（不依赖云）

`AsyncStorage` → `LocalDevicesCache`：
```json
"SmsStatusMessages":[{"Id":"65640","StatusName":"eProductStatusAlertID_InPowerSave",
 "Severity":2,"IsBlocking":false,
 "Title":{"Value":"打印机处于休眠状态"},"Description":{"Value":"打印机处于休眠状态"}}]
```
→ 中文文案由**原生 SMS ID 表**产生，非云端下发。克隆应内置同构的 ID → 文案表。

### 3.6 打印/扫描动作零云依赖

127 个 `localPrint*` GraphQL 操作全部由原生实现（`window.JWeb.Plugins.*` / `window.Shell.v1.graphql`），
底层是 IPP / eSCL / LEDM，**不出局域网**。已在 `docs\protocol.md` 真机验证。

### 3.7 应用确实能在长期离线后启动

- `LS_MYHP\LastServerAccessTime` = `2026/10/10 20:41:59 +08:00`
- 取证当日 = `2026-10-24`
- 期间 `AsyncStorage` → `app-lifecycle/launch-count = 13`，`@analytics/audience-instance/sent-time-stamp = 2026/10/24 9:46:06`
- `.hpscan\` 有 `2026/10/24 18:37` 的真实扫描输出

→ **已离线 14 天，应用仍可启动、可扫描。** 所以「完全离线不可用」是**功能被裁**，不是**进程起不来**。

### 3.8 专门的离线对话框

`MFE\@hpx-core-experiences\react-offlinedialog-mfe\`（38 个语言文件）：
`modal.title="无网络连接"`、`modal.retry="重试"`、`modal.dismiss="退出"`。
→ 官方明确承认存在「无网络」这一状态，只是把它当成错误而非正常模式。

### 3.9 遗留的反向证据：`localhost:8080`

`MYHP\AppxManifest.xml` → `uap:ApplicationContentUriRules` 第一条即 `http://localhost:8080`。
这是开发期的本地服务端口 —— **证明架构上完全支持「从本地 HTTP 服务加载整个 UI」**。
克隆可以直接复用这个模式（本地起一个 HTTP 服务托管 SPA）。

---

## 4. 攻击面 / 隐私：应用到底上传了什么

### 4.1 每次启动上传的会话快照（最完整的样本）

`LS_MYHP\LocalState\xfiles-session-snapshot.json`（原文）：

```json
{"hasPrivacyConsent":true,"country":"CN",
 "sessionId":"7005932808f54ea1a0f7cd5990704e31",
 "appVersion":"61.52637.14262.0","platform":"Windows",
 "startTime":"2026-10-24T11:00:52.8516033Z","endTime":"2026-10-24T11:02:34.0606278Z",
 "startupDurationMs":4750,
 "trail":"…onboarding:11:00:56,markstartupcomplete:11:00:57@parseshellurlchangede,
          ~ready : devices:11:00:57,/devices:11:00:57,/print:11:00:59,
          ~ishpccountry (scan): region=cn:11:01:01",
 "system":{"deviceId":"3eb3e026783382cf26d451db1885d9368177895a841999d64fe7f8723c85444a",
           "machineName":null,"osVersion":"Microsoft Windows NT 10.0.26200.0","osBuild":"26200",
           "architecture":"X64","totalMemoryMb":16211,"availableMemoryMb":5462,
           "processorCount":20,"dotNetVersion":".NET Native 4.6.29511.0",
           "diskType":null,"displayScaleFactor":null,"locale":"zh-CN","country":"CN"},
 "manufacturer":"Colorful Technology And Development Co.,LTD",
 "model":"BATTLE-AX B760M-G WIFI",
 "selectedPrinter":null,"printerModel":null,"printerConnectionType":null,
 "appLanguage":null,"networkStatus":null,"isSignedIn":false,
 "context":"{\"FWUCtrl\":\"Ready\"}","status":null,"hasLog":false}
```

**上传字段清单（未登录状态就采集）**：
`deviceId`（64 hex，机器指纹）、OS 版本/构建、架构、**总内存与可用内存**、CPU 核数、.NET 版本、
**系统 locale + 国家**、**主板厂商**、**主板型号**、打印机型号、连接类型、网络状态、登录态、
启动耗时、**逐秒的页面访问轨迹**（`trail`）、功能开关状态。

→ 即使不登录、不使用任何云功能，**机器指纹 + 硬件配置 + 使用轨迹**都已采集。
`deviceId` 的推导方式未在包内暴露（64 hex，疑似 SHA-256 派生的机器标识）。

### 4.2 用于开关定向的设备令牌

`AsyncStorage` → `@hp-af/feature-switch-native/global-tokens/69`（2 458 B）：
```
Manufacturer / Architecture / Country("{dataType:1,valueData:00000804}")
SSID  ← 实际取值表达式为 @wmi/ROOT\CIMV2/Win32_BaseBoard/Product（主板型号，字段名误导）
FeatureBytes (@smbios/11) / CommercialPlatform / ConsumerPlatform / GamingPlatform
ManagedExperience / AppHelperCapRegKey / NetworkCapRegKey / SysInfoCapRegKey
Pen / Dock / Audio / Battery / Display / Ecometer / HPGO / Gestures / PresenceDetection
```
`MYHP\Config\feature_filters_v2.2.json` 显示这些 token 全部来自**注册表探测**
（`HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Enum\ACPI\HPIC0003|HPIC000C` 等）。
→ 这些是**机器型号识别特征**，随 LaunchDarkly 上下文一起上报（`manifest.json` → `featureFlags.contextList` 明确把
`tenantId` / `portalName` / `email` 作为 `attributes` 上报）。

### 4.3 地理位置推断

`AsyncStorage`：
```
USER_CURRENT_ONLINE_COUNTRY = "China"
GEOIP_IS_COUNTRY_RESTRICTED = "false"
HpcCountriesList = ["CI","KW","GB",…,"CN","TW",…]   ← 191 个国家，决定 HPC(HP Connected) 功能可见性
```
→ 存在 **GeoIP 查询**（`~ishpccountry (scan): region=cn` 在启动轨迹里），结果落盘并影响功能裁剪。

### 4.4 推送通道

`localPushNotificationServices { __typename, type, ... on LocalFcmService { token }
  ... on LocalApnsService { token } ... on LocalWnsService { channelUri } }`
→ 应用会拿到 **WNS channel URI** 并注册到 HP 推送服务（`localPushNotificationServices` 被
`consents-northbound-api` 与 `settings-northbound-api` 同时调用）。
这意味着**HP 可以在应用未运行时通过 WNS 推送消息**。

### 4.5 数据主体 / 同意

`LS_MYHP\HPPrinterControlSettings.xml`：
```
AppUsageDataOptin                    = True          ← 默认开启使用数据
AppUsageConsentUrlSetting            = /in-app/windows/v1_0/user-consents
AppUsageConsentUpdateUrlSetting      = /in-app/windows/v1_0/user-consents-update
PrinterUsageConsentUrlSetting        = /in-app/windows/v1_0/printer-consents
PrinterUsageConsentUpdateUrlSetting  = /in-app/windows/v1_0/printer-consents-update
AlpacaId                             = 8fcd7d20-8a5c-4d4e-91ce-70b7fcd4fcaf   ← 与 appInstanceId 同一个 UUID
```
`AsyncStorage`：`@hp-af-privacy/privacy_initialized = true`、`@hp-af-privacy/managed_consent = false`、
`consentBasisId = 8fcd7d20-…`（又是同一个 UUID）。

→ **同意状态本身也是云端的**（`/user-consents` 需要联网读写）。离线时 `hasPrivacyConsent:true` 来自本地缓存。

### 4.6 硬件与网络指纹残留

- `LS_SMART\AssociatedDeviceList.xml` / `LS_MYHP\RecentDeviceList.xml`：
  打印机 IP `192.168.1.100`、MAC `000000000000`、序列号 `000000000010`、UUID、WSD 端口 GUID、**局域网网段 `3F`**，
  全部明文，且会被上报（`printerModel` / `printerConnectionType`）。
- `LS_SMART\LocalState\NetworkMap.dat`（390 B，二进制，疑似网络拓扑缓存）。
- `LS_MYHP\AsyncStorage.db` → `@hp-support/device-info/UUID` 的值被**错误地存成了 Python bytes 字面量**：
  `"b'4b2e8ee1-5a13-4c48-902a-ae0e60825292'"` —— 序列化 bug，会导致该 UUID 去重失效（每次上报都被当作新设备）。

### 4.7 凭据/令牌处理

| 项 | 观察 |
|---|---|
| Splunk RUM 令牌 | `UTOM3i-JMZLpo-rrAsC6Cw` 明文硬编码在 `Config\webapps_prod\manifest.json`，**发行包内** |
| LaunchDarkly clientId | `64e62df7c0fc221439184893` 明文 |
| 访问令牌 | 存于 WebView cookie/`AsyncStorage`，JWT 明文可解（`decodeJWTPayload` 直接 base64 解） |
| 设备 EWS 口令 | 走 `localPrintEsclSubmitCredential(userName, passWord)`；HP Smart 有 `PasswordPromptPage`，**未见本地加密存储**（无证据表明持久化） |
| 证书 | 包内 `DM_PIE.cer`、`HPInc_Private_SSL_CA.cer`、`HP_Inc_Private_Root_CA.base64.cer` —— **HP 私有根 CA 随包分发**（用于锁定自家服务端证书） |

### 4.8 对克隆的直接结论

1. **克隆必须把网络出口收窄到「打印机 IP + 127.0.0.1」**，不保留任何 HP 域名。
2. **不要复制 `localhost:8080` 这种无鉴权明文入口**——若用本地 HTTP 托管 SPA，只绑 `127.0.0.1` 且加随机端口。
3. **不要内置任何第三方 RUM/AB 测试 SDK**（Splunk/Datadog/LD/DY/Optimizely/Qualtrics）。
4. **不要采集机器指纹**；设备识别只用打印机序列号/UUID。
5. **不要申请 Instant Ink 那组 OAuth scope**（发票/账单/地址/套餐写入）。
6. **同意状态本地存**（`consent.json`），不设计云端往返。
7. 若要保留「导出可搜索 PDF」，必须自己实现本地 OCR（HP 的做法是云 + 本地语言包两条路并存，见下）。

---

## 5. 附：两个应用在「云 vs 本地」上的关键差异（易被忽略）

| 能力 | HP Smart | myHP | 说明 |
|---|---|---|---|
| 打印选项面板 | **自带完整面板**（份数/双面/无边距/缩放/小册子/水印） | **交给 Windows 原生对话框** | 克隆应取 HP Smart 的 |
| 扫描 OCR | **本地**（`en.zip` 8.67 MB 语言包 + PhotoEditorSDK） | **云端**（文案自证） | 两代产品实现不同，别混淆 |
| 扫描输出 | 本地（JPEG/PDF） | 本地 JPEG/PDF，云 PDF/txt/docx | |
| 外壳 | UWP XAML + JWebView 混合 | WebView2 + React 微前端，外壳从远程加载 | |
| 维护/报告 | 有 UI 但**对喷墨隐藏**，导向 EWS | 有 `printer-x-productmaintenance` 开关（`True`）但 Windows 路由封禁 | 两者最终都靠 EWS |
| 固件更新 | 远程网页 `react-firmware-update-controller-pro` | 同一远程网页（历史记录证明） | 完全一致 |

> OCR 的本地证据：`SMART\HP.Framework.Extensions.ScanCapture\en.zip`（8 679 072 B）、
> `AvailableOCRLanguages` / `InstalledOCRLanguages` / `OCRLangInstallCommand` / `OCRLangDownloadCancelCommand`（`…ScanCapture.xr.xml`）、
> `LS_MYHP\OCRInstalledLanguageList.xml` → `<SelectedLanguage>en</SelectedLanguage>`、
> `<InstalledLanguages><string>English (US)</string></InstalledLanguages>`。
> 但 myHP 的 `ConvertToTextFileTypes.Desc` 明说「在 HP 安全云中创建」→ **语言包本地，转换在云**。
