# 参与贡献

先阅读 LICENSE 与 THIRD_PARTY_NOTICES。主体采用 PolyForm Noncommercial 1.0.0，贡献需要允许按同一许可分发并保留第三方署名。

提交改动时说明现象、目标行为、验证方式与受影响硬件。优先用 Swift / Python 标准库与现有模块，避免新增无必要依赖。src 为菜单与逻辑，scripts 为安装/构建，vendor 为固定上游原生源码；上游集成请修改 scripts/integrate_native.py 的明确补丁，避免无记录地改 vendor。

运行 docs/BUILD.md 中两组测试。网络行为必须用真实设备复核，套餐解析用脱敏样本并覆盖不能确定余额的情况。不得自动发送短信、拨号或做新的模块永久授权来验证普通改动。

PR 不含用户 settings.json、quota.json、日志、录音、代理订阅、手机号、SIM 标识、PAT 或 .cache / build / dist。报告缺陷请使用模板，保持个人信息脱敏。
