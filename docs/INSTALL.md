# 安装、升级与卸载

## 安装

下载 Releases 中的 arm64 DMG 与 SHA256SUMS.txt，在终端执行 `shasum -a 256 下载的DMG路径`，与公布值比对。打开 DMG，运行“安装或升级 DJOneHub.command”，会打开同一 DJOneHub.app 的原生安装窗口，接受 PolyForm 非商业许可后安装。

首次被系统阻止时，在“系统设置 → 隐私与安全性”查看这一次下载的 App 的“仍要打开”提示，再确认打开。系统版本不同文字可能不同。仅允许你核实过来源和校验和的文件。此发行仅 ad-hoc 签名、未公证，不能宣称通过 Apple 安全认证。

安装路径：`~/Applications/DJOneHub.app`。所有原生界面、网络菜单、Python、增强版后端与 libusb 均在这个 bundle 中。无需另装 DJOneHub 或 Python；不会安装 Clash 或代理订阅。

安装器将旧 DJOneHub.app 快捷链接、旧网络菜单 App 和相关 LaunchAgent 备份，再注册合并后的服务：

| 文件 / 目录 | 用途 |
| --- | --- |
| ~/Applications/DJOneHub.app | 唯一用户 App |
| ~/Library/LaunchAgents/com.jonyyan.djonehub.networkmenu.plist | 登录启动原生 App，--background 不弹主窗口 |
| ~/Library/LaunchAgents/com.jamie.djonehub.plist | 启动 App 内模块后端，仅监听 127.0.0.1:7575 |
| ~/Library/Application Support/DJOneHub | 上游模块配置，保持原有数据 |
| ~/Library/Application Support/DJOneHubNetworkMenu | 菜单配置、流量统计、安装备份 |
| ~/Library/Logs/DJOneHub | 本机运行日志 |

旧 notifier 登录项被合并停用，避免两个原生窗口或两个 4G 信号图标。GPS 图标是上游独立功能，不是重复网络菜单。

安装失败会尝试恢复之前的 App 与启动配置。没有覆盖未知同名 App 的权限：若目标 bundle 标识不属于 DJOneHub，安装器停止。安装不需要 sudo。选择更改系统网络设置时，macOS 可能要求管理员授权。

## 升级

从新的 DMG 运行“安装或升级 DJOneHub.command”，保留同一数据目录。不要删除流量记录来升级。安装备份只留在本机，不会上传 GitHub。

以前的增强版 runtime / notifier 副本可能继续留在上游数据目录作为回退资料，新的 LaunchAgent 指向合并 App 内的后端。不会删除旧模块配置、SIM 授权或录音。后台重启会重置上游只保存在进程内的临时短信/通话列表；请先保存尚未持久化的重要内容。

## 登录启动与窗口

默认设置登录时启动。登录启动不弹主窗口；手动打开 DJOneHub.app 会打开原生窗口。关闭窗口保持来电通知、菜单和流量累计。取消登录启动可在“系统设置 → 通用 → 登录项”管理后台项目；如系统未列出对应项，可退出后移除本 App 的 native LaunchAgent。再次安装会重新建立启动项。

## 卸载

1. 先关闭「合盖不休眠」，确认系统休眠已恢复。模块仍连接时再关闭“自动使用 4G”，选“使用 Wi-Fi 上网”，从网络菜单退出 DJOneHub，让本工具恢复所添加的代理和 DNS。若显示「恢复系统休眠」，先点击恢复并完成系统授权。
2. 在终端停止这两个用户服务：

```sh
launchctl bootout gui/$(id -u)/com.jonyyan.djonehub.networkmenu
launchctl bootout gui/$(id -u)/com.jamie.djonehub
```

如果显示服务未加载，可继续下一步。

3. 移除 `~/Library/LaunchAgents/com.jonyyan.djonehub.networkmenu.plist`、`~/Library/LaunchAgents/com.jamie.djonehub.plist` 与 `~/Applications/DJOneHub.app`。
4. 默认保留两个 Application Support 数据目录。确认不再需要配置、短信、通话记录、流量与回退备份后，再自行删除相应资料和 Logs。

菜单退出恢复的是本工具添加的网络设置；系统服务优先顺序如需完全还原，可参照 settings.json 的 original_order 在系统网络设置里调整。不得把数据目录随意公开。

卸载 Mac App 不会撤销模块上已授权的 ADB，也不移除模块内通话或联网组件。修改模块固件、恢复模块组件是独立硬件操作，需要单独确认具体目标。

统一版使用独立的 App 标识，避免与旧增强版窗口混淆；首次通话或通讯录读取可能需要重新批准相应系统权限。升级入口仅启动同一个 App 的安装界面，不安装第二个 App。

升级重启了 USB 控制后台；若已有模块保持连接但数据请求超时，拔下等 10 秒再接回后复测。首次连接请以实际联网检测为准，而不仅查看网卡图标。
