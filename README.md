# DJOneHub Mac

**一个 Mac App：DJOneHub 原生管理界面 + Wi-Fi / 4G 菜单栏。**

[下载第一版](https://github.com/aeromelo/DJOneHub-Mac/releases/latest) · [使用说明](docs/USER_GUIDE.md) · [安装与卸载](docs/INSTALL.md) · [故障排查](docs/FAQ.md) · [第三方声明](THIRD_PARTY_NOTICES.md)

打开 **DJOneHub.app** 即可管理模块，同时启动网络切换菜单。关闭管理窗口仍保留菜单和通知。连接 4G 模块后显示菜单，拔下模块后隐藏。原生拨号、短信、通讯录、来电提醒和 GPS 界面沿用增强版；本项目新增的网络功能编译在同一 App 进程中。

## 第一版支持范围

- Apple Silicon（M 系列），macOS 13 或更新系统；安装包只包含 arm64 原生 App / Python。尚未发布 Intel 版本。
- 大疆第一代 4G 模块 / Baiwang USB ECM 网络接口，已插入可用 SIM 卡；需要支持数据传输的线材。
- 自带增强版 v1.2.9 后端、libusb 和 Python，无需为使用本 App 安装 Xcode、Homebrew 或 Python。
- 代理联动针对已安装并运行的 Clash Verge / Mihomo。App 不提供 VPN、代理节点、订阅或套餐。
- macOS 权限仍由系统批准；有线配件、麦克风、通讯录授权不能由程序绕过。

## 功能

| 功能 | 行为 |
| --- | --- |
| 网络选择 | 手动使用 4G 时关闭 Wi-Fi；选择 Wi-Fi 时恢复无线网络 |
| 自动使用 4G | 开启后，只要模块可用就优先 4G，锁定手动切换；关闭后恢复手动选择 |
| 信号 | 显示实际模块信号的 dBm 和四格图标，未读到时明确显示状态 |
| 熄屏联网 | 使用 4G 时防止自动整机闲置睡眠，仍允许屏保和显示器熄屏 |
| 唤醒恢复 | 整机唤醒后等待 USB 重新枚举，恢复 4G 出口并清理失效代理连接 |
| 联网检测 | 一次检测普通联网与选中的 VPN 站点，仅异常站点逐项红色提示 |
| 流量 | 用户点击短信同步建立额度基线，之后以模块 RX + TX 做本地估算 |
| 单 App | 原生 DJOneHub 窗口、短信与通话通知、网络菜单共用一个 App |

VPN 检测参考 Clash Verge v2.5.8：HTTPS 代理 CONNECT + 验证证书的 TLS 握手，避免网页 403 被误判为断网。握手成功代表网络可达，不代表账号已登录或某项业务可用。

## 快速安装

1. 在 [Releases](https://github.com/aeromelo/DJOneHub-Mac/releases) 下载最新版 arm64 DMG（当前为 `DJOneHub-Mac-1.0.1-macOS-arm64.dmg`）。
2. 打开 DMG，运行“安装或升级 DJOneHub.command”（会打开原生安装窗口），阅读许可后点击“同意并安装”。请使用随包安装流程，而不是直接拖到系统 Applications。
3. 安装到 `~/Applications/DJOneHub.app`，启动原生窗口；后台服务与 App 在登录时启动。插上模块并允许有线配件连接，网络菜单随即出现。
4. 手动切换时先关闭“自动使用 4G”，再选择“使用 Wi-Fi 上网”或“使用 4G 上网”。

安装保留原有 DJOneHub 磁盘配置和菜单流量统计，旧 App 与启动项备份到当前用户的数据目录。不会在安装流程中执行 USB 模式写入、ADB 授权或发送套餐短信。完整说明见 [安装指南](docs/INSTALL.md)。

**发行包为 ad-hoc 签名，未经过 Apple Developer ID 签名或公证。** 如果系统阻止首次打开，请按 [安装指南](docs/INSTALL.md) 在系统设置中允许这一个下载的 App；不要关闭系统的安全机制。

## 引用与许可

本项目是上游的非商业衍生整合，不是大疆官方产品。

1. 原版：[ZenGeekLabs/DJOneHub](https://github.com/ZenGeekLabs/DJOneHub)。
2. 增强版：[rogerbush007-a11y/DJOneHub-mac-enhanced](https://github.com/rogerbush007-a11y/DJOneHub-mac-enhanced)，原生界面源码和随包后端固定为 v1.2.9。
3. 原始必保留声明：**Required Notice: Copyright iniwex5 (https://github.com/iniwex5/vohive)**。
4. HTTPS 检测方法参考：[Clash Verge v2.5.8 test_delay](https://github.com/clash-verge-rev/clash-verge-rev/blob/v2.5.8/src-tauri/src/feat/clash.rs)。本项目以 Python 标准库独立实现；未打包 Clash 软件或节点。

主体沿用 **PolyForm Noncommercial 1.0.0**，只授予许可范围内的非商业使用；不属于可任意商用的 MIT / Apache 许可项目。Python、libusb 等各自的许可一并保留，详见 [LICENSE](LICENSE)、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 [licenses](licenses)。

## 文档与开发

- [完整使用说明](docs/USER_GUIDE.md)：自动开关、检测站点、流量、iPad、通话、熄屏。
- [安装 / 升级 / 卸载](docs/INSTALL.md)：备份、登录启动、恢复原有设置。
- [FAQ](docs/FAQ.md)：网卡、Wi-Fi、代理、联通短信及权限问题。
- [构建与架构](docs/BUILD.md)：固定依赖、原生合并、校验和、发行流程。
- [验证范围](docs/VALIDATION.md)：实际验证与尚未覆盖的场景。
- [隐私和安全](SECURITY.md)、[贡献规则](CONTRIBUTING.md)、[变更记录](CHANGELOG.md)。

提交问题时只需说明机型、系统、版本、连接方式和现象。请隐藏手机号、SIM 标识、短信正文、验证码、代理订阅和认证信息。

统一版使用独立的 App 标识，避免与旧增强版窗口混淆；首次通话或通讯录读取可能需要重新批准相应系统权限。升级入口仅启动同一个 App 的安装界面，不安装第二个 App。
