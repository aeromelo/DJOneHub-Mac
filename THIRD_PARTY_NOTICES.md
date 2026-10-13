# 第三方声明与来源

## DJOneHub 原版

- 项目：https://github.com/ZenGeekLabs/DJOneHub
- 来源和基础模块控制能力归上游作者所有。
- 许可：PolyForm Noncommercial 1.0.0，完整文本见 licenses/DJOneHub.txt。
- 必须保留：Required Notice: Copyright iniwex5 (https://github.com/iniwex5/vohive)

## DJOneHub mac enhanced

- 项目：https://github.com/rogerbush007-a11y/DJOneHub-mac-enhanced
- 固定版本：v1.2.9。后端、libusb 和原生 App 资源来自官方发行 DMG；原生界面源码保留在 vendor/djonehub-enhanced，构建时应用整合补丁。
- 许可：PolyForm Noncommercial 1.0.0，见 licenses/DJOneHub-mac-enhanced.txt 与 vendor/djonehub-enhanced/LICENSE。
- 原有作者与上游贡献者版权保留。本项目整合贡献由 aeromelo 维护，采用同一非商业许可，不暗示上游或大疆官方认可。
- 发行 DMG 的 URL / SHA256 见 DEPENDENCIES.json；随包的 upstream/djonehub/LICENSE、licenses、THIRD_PARTY_NOTICES 仍保留。

## libusb

增强版发行内 libusb 1.0.30 采用 LGPL 2.1 或后续版本。随 upstream/djonehub 的完整 COPYING、第三方声明与源码链接一起保留。源码：https://github.com/libusb/libusb ，版本 v1.0.30。本项目不修改 libusb，运行时动态链接共享库。

## CPython / python-build-standalone

- CPython 3.13.16，Astral python-build-standalone 20261009 的 aarch64-apple-darwin install_only 发行。
- 项目：https://github.com/astral-sh/python-build-standalone ，CPython：https://github.com/python/cpython 。
- 固定下载与校验和：DEPENDENCIES.json。Python 与 OpenSSL 等完整声明在 licenses/python-runtime；运行时原有标准库/附带 pip 的许可证亦保留。
- 许可元数据从同日同版本 full 归档提取。full 归档 SHA256：70025edd2ed4bf0a333677928ded047368726954253b6e428732e71e9c5a163e。licenses/python-runtime/PYTHON.json 列出构建组成；该 full 归档不作为额外运行时分发。
- 随附声明可能覆盖构建元数据中的组件，不代表所有列出的库均被 App 加载。各组件许可分别适用，主体非商业许可不替代第三方许可。

## Clash Verge 检测方法参考

参考版本 v2.5.8 的 src-tauri/src/feat/clash.rs 中 test_delay：HTTPS CONNECT 后做 TLS 握手，不以首页 HTTP 403 判断网络不可达。

链接：https://github.com/clash-verge-rev/clash-verge-rev/blob/v2.5.8/src-tauri/src/feat/clash.rs 。该上游采用 GPL-3.0。本项目用 Python 标准库独立实现连接测试，没有复制该 Rust 源码或分发 Clash 二进制、订阅和节点。安装或使用 Clash 时请遵守其自身许可。

## 商标

DJI / 大疆、运营商和检测站点名称仅用于描述兼容对象。商标属于各自持有人。本项目无上述厂商的官方关联或背书。
