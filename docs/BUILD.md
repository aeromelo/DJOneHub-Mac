# 架构、构建和发行

## 架构

```text
DJOneHub.app
 ├─ Contents/MacOS/DJOneHub
 │   ├─ 增强版 SwiftUI 拨号 / 短信 / 联系人 / GPS
 │   └─ NetworkMenu：菜单、信号、电源保护、异步网络操作
 └─ Contents/Resources
     ├─ python：固定版本 arm64 CPython
     ├─ network_control.py / quota_control.py
     ├─ upstream/djonehub：固定版本 Go 后端、libusb、许可
     └─ licenses / DEPENDENCIES.json

用户 LaunchAgent → App / 后端
本机 API 127.0.0.1:7575 → USB 模块
网络 helper → networksetup / route / 系统 DNS / 现有 Mihomo Unix socket
```

原生界面和网络菜单是同一可执行程序，不是通过开另一个 App 模拟合并。上游 native source 在 vendor/djonehub-enhanced 保留，scripts/integrate_native.py 在构建目录应用少量受检查的改动：注入网络菜单、同窗打开、默认手动启动显示窗口、删除重复蜂窝图标、转发退出清理。后端以用户级 launchd 服务运行，并由原生界面恢复服务。

src 的 Python 仅依赖标准库。App 用内置 Python 的 `-I -B` 隔离模式（禁止写入包内字节码缓存，保持签名完整）调用 helper，避免用户 PYTHONPATH 干扰；只显式加入本 App 的 helper 目录。网络操作串行执行，检测并行到选中站点。

物理出口切换后，使用现有 Mihomo 核心的当前配置重新加载 TUN / DNS，恢复原有模式和手动节点选择，并等待本地 DNS 与无线地址就绪。重新加载会重建旧连接，不替换订阅。

合盖保护由 `KeepAwake.swift` 与 `LidService.swift` 管理。首次通过系统 AppleScript 管理员授权将同一可执行文件复制为 root 拥有的辅助服务，之后使用 Foundation NSXPCConnection 的 privileged Mach 服务通信，无需每次授权。服务按连接有效 UID 限定首次授权用户，只接受布尔休眠操作；所有操作串行化、按连接记录所有权。连接断开恢复休眠；root 专属 journal 允许服务异常重启或系统重启后恢复。没有保存密码或开放通用命令接口。

## 构建环境

需要 Apple Silicon Mac、完整 Xcode / Swift 6 工具链（Swift 语言模式 5）、Python 3.9+ 运行构建脚本、hdiutil、codesign。编译目标 macOS 13.0。终端：

```sh
python3 -m unittest discover -s src -p 'test_*.py' -v
python3 -m unittest discover -s scripts -p 'test_*.py' -v
python3 scripts/build.py
```

首次构建下载 DEPENDENCIES.json 固定的 CPython 与增强版 DMG，每个下载以 SHA256 校验；后续使用 .cache。源码中已随附固定 v1.2.9 原生源码和许可。运行时版本不随“latest”变化。

构建使用 build.noindex 目录，避免 Spotlight 将临时 App 当成多个安装版本。

输出：build.noindex/DJOneHub.app、dist/DJOneHub-Mac-版本-macOS-arm64.dmg、dist/SHA256SUMS.txt。构建先给 Python 的 Mach-O 模块签名，再签名 App、执行严格校验与原生 self-test，最后生成压缩 DMG。Swift 构建使用 release 优化并关闭独立 dSYM，避免把调试符号带入发行 App。

在不允许挂载 DMG 的受限构建环境，可设置 `DJONEHUB_UPSTREAM_DIR` 指向已经校验安装的 `.../Contents/Resources/upstream`，复用同一份固定 v1.2.9 后端；正常公开构建仍按 `DEPENDENCIES.json` 下载并 SHA256 校验上游 DMG。

## 发行

公开目录仅包含源码、文档、上游许可和必要原生资源。排除 .cache、build.noindex、dist、用户日志、设置、套餐余额、短信、SIM 信息和安装备份。

先通过测试、真实设备与安装验证；更新 VERSION / CHANGELOG，再创建公开 GitHub tag 与 Release，上传 DMG 和校验和。GitHub 自动提供源代码压缩包。不把后台 token、代理配置、个人路径或认证资料提交到仓库。

第一版 ad-hoc 签名，没有 Developer ID / 公证凭证；有相应证书的发行者可以自行配置正式签名与 Apple notarization，本项目不虚构公证状态。macOS CI 检查 Python逻辑，真实 USB / SIM / 睡眠验证需要硬件，不能由 CI 代替。
