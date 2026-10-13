import AppKit
import Foundation
import IOKit.pwr_mgt

struct NetworkState: Decodable {
    var mode: String
    var device: String
    var wifi_available: Bool
    var cellular_available: Bool
    var cellular_connected: Bool
    var auto_switch: Bool
    var preferred_mode: String
    var wifi_power: Bool
    var automation_error: String?
    var signal_dbm: Int?
    var `operator`: String?
    var registration: String?
    var connectivity: ConnectivityState?
    var quota: QuotaState?
    var vpn_sites: [VPNSelection]
}

struct VPNSelection: Decodable {
    var id: String
    var label: String
    var enabled: Bool
}

struct QuotaState: Decodable {
    var carrier: String
    var carrier_name: String
    var remaining_bytes: Int64?
    var used_bytes: Int64
    var synced_at: String?
    var pending: Bool
    var status: String
    var shared: Bool?
    var query_command: String?
}

func dataSize(_ bytes: Int64) -> String {
    bytes >= 1_073_741_824 ? String(format: "%.2f GB", Double(bytes) / 1_073_741_824) :
                           String(format: "%.1f MB", Double(bytes) / 1_048_576)
}

struct ProbeResult: Decodable {
    var ok: Bool
    var http_status: Int?
    var latency_ms: Int
    var error: String?
    var label: String?
}

func failedVPNChecks(_ check: ConnectivityState) -> [(key: String, value: ProbeResult)] {
    check.tests.filter { $0.key != "internet" && !$0.value.ok }
        .sorted { ($0.value.label ?? $0.key) < ($1.value.label ?? $1.key) }
}

func failureMenuItem(_ title: String) -> NSMenuItem {
    let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
    item.isEnabled = false
    // A label view keeps the error red even when this informational row is disabled.
    let label = NSTextField(labelWithString: title)
    label.font = NSFont.menuFont(ofSize: 0)
    label.textColor = .systemRed
    label.sizeToFit()
    let view = NSView(frame: NSRect(x: 0, y: 0, width: label.frame.width + 32, height: 24))
    label.frame.origin = NSPoint(x: 16, y: (24 - label.frame.height) / 2)
    view.addSubview(label)
    item.view = view
    return item
}

struct ConnectivityState: Decodable {
    var mode: String
    var device: String
    var checked_at: String
    var network_changed: Bool
    var tests: [String: ProbeResult]
}

func signalLevel(_ dbm: Int?) -> Int {
    guard let dbm = dbm else { return 0 }
    return dbm >= -85 ? 4 : dbm >= -95 ? 3 : dbm >= -105 ? 2 : 1
}

func signalIcon(_ level: Int) -> NSImage {
    let image = NSImage(size: NSSize(width: 18, height: 16), flipped: false) { _ in
        for index in 0..<4 {
            let rect = NSRect(x: 1 + CGFloat(index) * 4.2, y: 2,
                              width: 2.8, height: 3.5 + CGFloat(index) * 3.1)
            let path = NSBezierPath(roundedRect: rect, xRadius: 0.9, yRadius: 0.9)
            if index < level {
                NSColor.black.setFill()
                path.fill()
            } else {
                NSColor.black.withAlphaComponent(0.28).setStroke()
                path.lineWidth = 0.7
                path.stroke()
            }
        }
        return true
    }
    image.isTemplate = true
    image.accessibilityDescription = "4G 信号 \(level) 格"
    return image
}

func runNetworkControl(_ action: String) throws -> Data {
    let process = Process()
    process.executableURL = Bundle.main.resourceURL!.appendingPathComponent("python/bin/python3")
    let resource = Bundle.main.resourceURL!.appendingPathComponent("network_control.py").path
    process.arguments = ["-I", "-B", resource, action]
    let pipe = Pipe()
    process.standardOutput = pipe
    process.standardError = FileHandle.nullDevice
    try process.run()
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    process.waitUntilExit()
    if process.terminationStatus != 0 {
        let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        throw NSError(domain: "NetworkMenu", code: 1, userInfo: [NSLocalizedDescriptionKey: object?["error"] as? String ?? "网络操作失败"])
    }
    return data
}

final class NetworkMenu: NSObject, NSApplicationDelegate {
    var openManagement: (() -> Void)?
    private var status: NSStatusItem!
    private let menu = NSMenu()
    private let current = NSMenuItem(title: "正在读取网络…", action: nil, keyEquivalent: "")
    private let powerStatus = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private var idleSleepAssertion: IOPMAssertionID = 0
    private var wasCellularBeforeSleep = false
    private var lastWakeRecovery = Date.distantPast
    private let signal = NSMenuItem(title: "4G 信号：正在读取…", action: nil, keyEquivalent: "")
    private let internet = NSMenuItem(title: "普通联网：尚未检测", action: nil, keyEquivalent: "")
    private let vpn = NSMenuItem(title: "VPN 联网：尚未检测", action: nil, keyEquivalent: "")
    private var vpnFailures: [NSMenuItem] = []
    private let vpnSettings = NSMenu()
    private let testedAt = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private let quotaRemaining = NSMenuItem(title: "套餐剩余：首次使用，请短信同步", action: nil, keyEquivalent: "")
    private let quotaUsed = NSMenuItem(title: "本地累计：0 MB", action: nil, keyEquivalent: "")
    private let quotaUpdated = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private var quotaSync: NSMenuItem!
    private var carrierMenu: NSMenuItem!
    private var unicomCommandItem: NSMenuItem!
    private let unicomCommands = NSMenu()
    private var wifi: NSMenuItem!
    private var cellular: NSMenuItem!
    private var automatic: NSMenuItem!
    private var timer: Timer?
    private var refreshing = false
    private var switching = false
    private var lastState: NetworkState?
    private let queue = DispatchQueue(label: "djonehub.networkmenu.operations")

    func applicationDidFinishLaunching(_ notification: Notification) {
        status = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        status.isVisible = false
        status.button?.title = "⇄ 网络"
        status.button?.toolTip = "点击切换 Wi-Fi / 4G，查看模块信号"
        menu.autoenablesItems = false
        current.isEnabled = false
        signal.isEnabled = false
        menu.addItem(current)
        menu.addItem(signal)
        powerStatus.isEnabled = false
        menu.addItem(powerStatus)
        for item in [internet, vpn, testedAt] {
            item.isEnabled = false
            menu.addItem(item)
        }
        menu.addItem(.separator())
        wifi = add("使用 Wi-Fi 上网", #selector(selectWifi))
        wifi.image = NSImage(systemSymbolName: "wifi", accessibilityDescription: "Wi-Fi")
        cellular = add("使用 4G 上网", #selector(selectCellular))
        cellular.image = NSImage(systemSymbolName: "antenna.radiowaves.left.and.right", accessibilityDescription: "4G")
        automatic = add("自动使用 4G：关", #selector(toggleAutomatic))
        automatic.image = NSImage(systemSymbolName: "bolt.circle", accessibilityDescription: "自动切换")
        menu.addItem(.separator())
        for item in [quotaRemaining, quotaUsed, quotaUpdated] {
            item.isEnabled = false
            menu.addItem(item)
        }
        quotaSync = add("首次短信同步剩余流量", #selector(syncQuota))
        quotaSync.image = NSImage(systemSymbolName: "arrow.triangle.2.circlepath", accessibilityDescription: "短信同步")
        carrierMenu = NSMenuItem(title: "查询运营商：自动识别", action: nil, keyEquivalent: "")
        let carriers = NSMenu()
        carriers.autoenablesItems = false
        for (key, title) in [("auto", "自动识别 SIM 卡"), ("telecom", "中国电信 · 108 → 10001"), ("unicom", "中国联通 · CXTCYL → 10010"), ("mobile", "中国移动 · CXLL → 10086")] {
            let item = NSMenuItem(title: title, action: #selector(selectCarrier(_:)), keyEquivalent: "")
            item.representedObject = key
            item.target = self
            carriers.addItem(item)
        }
        carriers.addItem(.separator())
        unicomCommandItem = NSMenuItem(title: "联通查询指令", action: nil, keyEquivalent: "")
        unicomCommands.autoenablesItems = false
        for (command, title) in [("CXTCYL", "套餐余量 · CXTCYL（默认）"), ("2082", "套餐余量 · 2082"), ("CXLL", "流量使用 · CXLL"), ("1071", "流量使用 · 1071"), ("CXLLJ", "地区流量详单 · CXLLJ")] {
            let item = NSMenuItem(title: title, action: #selector(selectUnicomCommand(_:)), keyEquivalent: "")
            item.representedObject = command
            item.target = self
            unicomCommands.addItem(item)
        }
        unicomCommandItem.submenu = unicomCommands
        carriers.addItem(unicomCommandItem)
        carrierMenu.submenu = carriers
        menu.addItem(carrierMenu)
        menu.addItem(.separator())
        _ = add("刷新网络与信号", #selector(refresh))
        _ = add("检测能否上网", #selector(testInternet))
        let sitesItem = NSMenuItem(title: "VPN 检测站点", action: nil, keyEquivalent: "")
        vpnSettings.autoenablesItems = false
        sitesItem.submenu = vpnSettings
        menu.addItem(sitesItem)
        _ = add("重新检测代理出口", #selector(refreshProxy))
        _ = add("打开 DJOneHub", #selector(openDJOneHub))
        menu.addItem(.separator())
        _ = add("退出 DJOneHub（恢复代理自动出口）", #selector(quit))
        status.menu = menu
        let notifications = NSWorkspace.shared.notificationCenter
        notifications.addObserver(self, selector: #selector(willSleep), name: NSWorkspace.willSleepNotification, object: nil)
        notifications.addObserver(self, selector: #selector(didWake(_:)), name: NSWorkspace.didWakeNotification, object: nil)
        notifications.addObserver(self, selector: #selector(didWake(_:)), name: NSWorkspace.screensDidWakeNotification, object: nil)
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.refresh() }
    }

    private func add(_ title: String, _ action: Selector) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: "")
        item.target = self
        menu.addItem(item)
        return item
    }

    @objc func refresh() {
        guard !refreshing && !switching else { return }
        refreshing = true
        queue.async {
            let result = Result { try JSONDecoder().decode(NetworkState.self, from: runNetworkControl("status")) }
            DispatchQueue.main.async {
                self.refreshing = false
                guard !self.switching else { return }
                switch result {
                case .success(let state): self.show(state)
                case .failure(let error): self.current.title = "状态读取失败：\(error.localizedDescription)"
                }
            }
        }
    }

    private func show(_ state: NetworkState) {
        lastState = state
        updateSleepProtection(state)
        status.isVisible = state.cellular_connected
        let label = state.mode == "4g" ? "4G" : state.mode == "wifi" ? "Wi-Fi" : "其他网络"
        status.button?.title = state.mode == "4g" ? "4G" : "\(label) · 4G"
        status.button?.image = signalIcon(signalLevel(state.signal_dbm))
        status.button?.imagePosition = .imageRight
        status.button?.toolTip = "点击选择 Wi-Fi / 4G；" + (state.cellular_available ? "4G 信号 \(state.signal_dbm.map { "\($0) dBm" } ?? "读取中")" : "Mac 尚未识别 4G 模块")
        current.title = "当前出口：\(label)（\(state.device)）"
        if let error = state.automation_error { current.title = "自动切换未完成：\(error)" }
        if !state.cellular_available {
            signal.title = "4G 模块未连接"
        } else if let dbm = state.signal_dbm {
            let quality = signalLevel(dbm) >= 3 ? "良好" : signalLevel(dbm) == 2 ? "一般" : "较弱"
            signal.title = "4G 信号：\(dbm) dBm · \(quality)"
        } else {
            signal.title = "4G 网卡已连接；信号暂未读到"
        }
        // Manual choices become available only after the auto-4G switch is off.
        wifi.isEnabled = !switching && !state.auto_switch
        cellular.isEnabled = !switching && !state.auto_switch
        wifi.state = state.mode == "wifi" ? .on : .off
        cellular.state = state.mode == "4g" ? .on : .off
        automatic.isEnabled = !switching
        automatic.state = state.auto_switch ? .on : .off
        automatic.title = state.auto_switch ? "自动使用 4G：开（固定 4G）" : "自动使用 4G：关（可手动切换）"
        cellular.title = "使用 4G 上网（关闭 Wi-Fi）"
        wifi.title = "使用 Wi-Fi 上网（开启 Wi-Fi）"
        quotaSync.isEnabled = state.cellular_connected && !switching && state.quota?.pending != true
        if let quota = state.quota {
            quotaRemaining.title = quota.remaining_bytes.map { "\(quota.shared == true ? "共享套餐" : "套餐")剩余：约 \(dataSize($0))（本地估算）" } ?? "套餐剩余：尚未同步"
            quotaUsed.title = "同步后本地累计：\(dataSize(quota.used_bytes))（收发合计）"
            quotaUpdated.title = quota.pending || quota.synced_at == nil ? quota.status :
                "上次短信同步：\(quota.synced_at!.prefix(16).replacingOccurrences(of: "T", with: " "))"
            if quota.shared == true && !quota.pending { quotaUpdated.title += " · 其他设备用量需短信更新" }
            if quota.status.contains("未返回") || quota.status.contains("未被") || quota.status.contains("跨月") || quota.status.contains("未识别") || quota.status.contains("未收到") { quotaUpdated.title = quota.status }
            quotaSync.title = quota.pending ? "等待运营商短信回复…" : quota.synced_at == nil ? "首次短信同步剩余流量" : "短信同步剩余流量"
            carrierMenu.title = "查询运营商：\(quota.carrier_name.isEmpty ? "自动识别" : quota.carrier_name)"
            unicomCommandItem.isEnabled = quota.carrier == "unicom" && !switching
            for item in unicomCommands.items {
                item.state = (item.representedObject as? String) == quota.query_command ? .on : .off
            }
        }
        if let check = state.connectivity {
            showChecks(check)
        } else {
            internet.title = "普通联网：尚未检测"
            vpn.title = "VPN 联网：尚未检测"
            testedAt.title = "点击下方“检测能否上网”"
            for item in vpnFailures { menu.removeItem(item) }
            vpnFailures.removeAll()
            for item in [internet, vpn] { item.image = nil }
        }
        vpnSettings.removeAllItems()
        for choice in state.vpn_sites {
            let item = NSMenuItem(title: choice.label, action: #selector(toggleVPN(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = choice.id
            item.state = choice.enabled ? .on : .off
            item.isEnabled = !switching
            vpnSettings.addItem(item)
        }
        auditMenu()
    }

    private func updateSleepProtection(_ state: NetworkState) {
        let needsProtection = state.mode == "4g" && state.cellular_connected
        if needsProtection && idleSleepAssertion == 0 {
            let result = IOPMAssertionCreateWithName(kIOPMAssertionTypePreventUserIdleSystemSleep as CFString,
                IOPMAssertionLevel(kIOPMAssertionLevelOn), "DJOneHub: keep USB 4G awake while display sleeps" as CFString, &idleSleepAssertion)
            if result != kIOReturnSuccess { idleSleepAssertion = 0 }
        } else if !needsProtection && idleSleepAssertion != 0 {
            IOPMAssertionRelease(idleSleepAssertion)
            idleSleepAssertion = 0
        }
        powerStatus.title = needsProtection ? (idleSleepAssertion != 0 ? "4G 保持联网：允许熄屏，防止自动整机睡眠" : "4G 保持联网：电源保护未生效") : "电源保护：随 4G 启用，Wi-Fi 时解除"
    }

    @objc private func willSleep() { wasCellularBeforeSleep = lastState?.mode == "4g" }
    @objc private func didWake(_ notification: Notification) {
        if notification.name == NSWorkspace.screensDidWakeNotification && !wasCellularBeforeSleep { refresh(); return }
        guard wasCellularBeforeSleep || lastState?.mode == "4g" else { refresh(); return }
        guard Date().timeIntervalSince(lastWakeRecovery) >= 15, !switching else { return }
        lastWakeRecovery = Date()
        wasCellularBeforeSleep = false
        act("wake-4g")
    }
    func applicationWillTerminate(_ notification: Notification) {
        timer?.invalidate()
        NSWorkspace.shared.notificationCenter.removeObserver(self)
        _ = try? runNetworkControl("automatic")
        if idleSleepAssertion != 0 { IOPMAssertionRelease(idleSleepAssertion) }
    }

    private func showChecks(_ check: ConnectivityState) {
        for (key, label, item) in [("internet", "普通联网", internet)] {
            guard let test = check.tests[key] else { continue }
            item.title = "\(label)：\(test.ok ? "可访问" : "不可访问")" + (test.http_status.map { " · HTTP \($0)" } ?? "")
            item.image = NSImage(systemSymbolName: test.ok ? "checkmark.circle" : "xmark.circle", accessibilityDescription: test.ok ? "可访问" : "不可访问")
        }
        for item in vpnFailures { menu.removeItem(item) }
        vpnFailures.removeAll()
        let failed = failedVPNChecks(check)
        let hasVPNTests = check.tests.keys.contains { $0 != "internet" }
        vpn.title = check.network_changed ? "VPN 联网：网络已改变，请重试" :
            !hasVPNTests ? "VPN 联网：未选择检测站点" : failed.isEmpty ? "VPN 联网：正常" : "VPN 联网：\(failed.count) 个站点异常"
        vpn.image = hasVPNTests ? NSImage(systemSymbolName: failed.isEmpty ? "checkmark.circle" : "exclamationmark.triangle", accessibilityDescription: failed.isEmpty ? "VPN 联网正常" : "部分站点访问异常") : nil
        if !check.network_changed {
            for (offset, entry) in failed.enumerated() {
                let item = failureMenuItem("⚠ \(entry.value.label ?? entry.key)：\(entry.value.error ?? "连接失败")")
                menu.insertItem(item, at: menu.index(of: vpn) + 1 + offset)
                vpnFailures.append(item)
            }
        }
        let clock = check.checked_at.dropFirst(11).prefix(8)
        testedAt.title = check.network_changed ? "检测时网络改变，请重试" : "最近检测：\(clock) · \(check.mode == "4g" ? "4G" : "Wi-Fi")"
        auditMenu()
    }

    private func auditMenu() {
        // Read-only evidence of the actual live NSMenu, with no personal data.
        let directory = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/DJOneHubNetworkMenu")
        let data: [String: Any] = ["version": Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") ?? "",
                                  "visible": status.isVisible,
                                  "idle_sleep_protection": idleSleepAssertion != 0,
                                  "title": status.button?.title ?? "",
                                  "vpn_sites": vpnSettings.items.map { ["title": $0.title, "checked": $0.state == .on, "enabled": $0.isEnabled] },
                                  "items": menu.items.filter { !$0.isSeparatorItem }.map { item in
                                      ["title": item.title, "enabled": item.isEnabled, "checked": item.state == .on,
                                       "red": item.view?.subviews.contains { ($0 as? NSTextField)?.textColor == .systemRed } ?? false,
                                       "action": item.action.map(NSStringFromSelector) ?? ""] as [String: Any]
                                  }]
        if let encoded = try? JSONSerialization.data(withJSONObject: data, options: [.prettyPrinted]) {
            try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try? encoded.write(to: directory.appendingPathComponent("menu-state.json"), options: .atomic)
        }
    }

    private func act(_ action: String, then completion: (() -> Void)? = nil) {
        guard !switching else { return }
        switching = true
        wifi.isEnabled = false
        cellular.isEnabled = false
        automatic.isEnabled = false
        quotaSync.isEnabled = false
        for item in vpnSettings.items { item.isEnabled = false }
        current.title = action == "quota-sync" ? "正在发送流量查询短信…" : action == "test" ? "正在检测联网，请稍候…" : "正在更新网络，请稍候…"
        queue.async {
            let result = Result { () throws -> Data in
                let response = try runNetworkControl(action)
                if ["wifi", "4g", "refresh-proxy"].contains(action) {
                    return try runNetworkControl("test")
                }
                return response
            }
            DispatchQueue.main.async {
                self.switching = false
                if case .failure(let error) = result {
                    self.current.title = error.localizedDescription
                    if action == "wake-4g" { self.refresh(); return }
                    let alert = NSAlert()
                    alert.messageText = "操作未完成"
                    alert.informativeText = error.localizedDescription
                    NSApp.activate(ignoringOtherApps: true)
                    alert.runModal()
                } else if let completion = completion {
                    completion()
                    return
                }
                self.refresh()
            }
        }
    }

    @objc private func selectWifi() { act("wifi") }
    @objc private func selectCellular() { act("4g") }
    @objc private func toggleAutomatic() { act(lastState?.auto_switch == true ? "auto-off" : "auto-on") }
    @objc private func refreshProxy() { act("refresh-proxy") }
    @objc private func testInternet() { act("test") }
    @objc private func toggleVPN(_ sender: NSMenuItem) {
        if let key = sender.representedObject as? String { act("vpn-toggle-" + key) }
    }
    @objc private func syncQuota() { act("quota-sync") }
    @objc private func selectUnicomCommand(_ sender: NSMenuItem) {
        if let command = sender.representedObject as? String { act("quota-command-" + command) }
    }
    @objc private func selectCarrier(_ sender: NSMenuItem) {
        if let carrier = sender.representedObject as? String { act("quota-carrier-" + carrier) }
    }
    @objc private func openDJOneHub() {
        openManagement?()
    }
    @objc private func quit() { act("automatic") { NSApp.terminate(nil) } }
}

func networkMenuSelfTest() {
    assert(signalLevel(nil) == 0)
    assert(signalLevel(-73) == 4)
    assert(signalLevel(-90) == 3)
    assert(signalLevel(-100) == 2)
    assert(signalLevel(-115) == 1)
    let good = ProbeResult(ok: true, http_status: 200, latency_ms: 1, error: nil, label: "Google")
    let bad = ProbeResult(ok: false, http_status: 403, latency_ms: 1, error: "访问受限 · HTTP 403", label: "Claude")
    let check = ConnectivityState(mode: "4g", device: "en9", checked_at: "", network_changed: false, tests: ["internet": bad, "google": good, "claude": bad])
    assert(failedVPNChecks(check).map { $0.key } == ["claude"])
    let item = failureMenuItem("Claude：访问受限")
    assert((item.view?.subviews.first as? NSTextField)?.textColor == .systemRed)
    assert(failedVPNChecks(ConnectivityState(mode: "wifi", device: "en0", checked_at: "", network_changed: false, tests: ["google": good])).isEmpty)
    print("Signal display checks passed")
}
