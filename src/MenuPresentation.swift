import AppKit
import Darwin
import Foundation
import SwiftUI

struct InterfaceCounters {
    let name: String
    let index: UInt32
    let received: UInt64
    let sent: UInt64

    static func read(_ name: String) -> InterfaceCounters? {
        let index = if_nametoindex(name)
        guard index != 0 else { return nil }
        var mib = [CTL_NET, PF_ROUTE, 0, 0, NET_RT_IFLIST2, Int32(index)]
        var size = 0
        guard sysctl(&mib, UInt32(mib.count), nil, &size, nil, 0) == 0, size > 0 else { return nil }
        var bytes = [UInt8](repeating: 0, count: size)
        let result = bytes.withUnsafeMutableBytes {
            sysctl(&mib, UInt32(mib.count), $0.baseAddress, &size, nil, 0)
        }
        guard result == 0 else { return nil }
        return bytes.withUnsafeBytes { buffer in
            var offset = 0
            while offset + MemoryLayout<if_msghdr2>.size <= size {
                var header = if_msghdr2()
                memcpy(&header, buffer.baseAddress!.advanced(by: offset), MemoryLayout<if_msghdr2>.size)
                let length = Int(header.ifm_msglen)
                guard length > 0, offset + length <= size else { return nil }
                if header.ifm_type == RTM_IFINFO2 && header.ifm_index == index {
                    guard header.ifm_flags & IFF_UP != 0 else { return nil }
                    return InterfaceCounters(name: name, index: index,
                        received: header.ifm_data.ifi_ibytes, sent: header.ifm_data.ifi_obytes)
                }
                offset += length
            }
            return nil
        }
    }
}

struct TransferRate {
    let download: Double
    let upload: Double

    static func format(_ bytesPerSecond: Double) -> String {
        var value = max(0, bytesPerSecond)
        let units = ["B/s", "KB/s", "MB/s", "GB/s"]
        var unit = 0
        while value >= 1024 && unit < units.count - 1 {
            value /= 1024
            unit += 1
        }
        return String(format: value < 10 && unit > 0 ? "%.1f %@" : "%.0f %@",
                      locale: Locale(identifier: "en_US_POSIX"), value, units[unit])
    }

    var title: String { "↓\(Self.format(download)) ↑\(Self.format(upload))" }
}

struct TransferSampler {
    private var previous: InterfaceCounters?
    private var timestamp: TimeInterval?

    mutating func reset() { previous = nil; timestamp = nil }

    mutating func update(_ sample: InterfaceCounters?, at time: TimeInterval) -> TransferRate? {
        defer { previous = sample; timestamp = sample == nil ? nil : time }
        guard let sample = sample, let old = previous, let start = timestamp,
              sample.name == old.name, sample.index == old.index,
              sample.received >= old.received, sample.sent >= old.sent,
              time > start, time - start <= 3 else { return nil }
        return TransferRate(download: Double(sample.received - old.received) / (time - start),
                            upload: Double(sample.sent - old.sent) / (time - start))
    }
}

func signalAndSpeedIcon(_ level: Int, rate: TransferRate?) -> NSImage {
    let lines = ["↓" + (rate.map { TransferRate.format($0.download) } ?? "--"),
                 "↑" + (rate.map { TransferRate.format($0.upload) } ?? "--")]
    let attributes: [NSAttributedString.Key: Any] = [
        .font: NSFont.monospacedDigitSystemFont(ofSize: 9, weight: .medium),
        .foregroundColor: NSColor.black
    ]
    let textWidth = ceil(lines.map { ($0 as NSString).size(withAttributes: attributes).width }.max() ?? 0)
    let signal = signalIcon(level)
    let image = NSImage(size: NSSize(width: 23 + textWidth, height: 22), flipped: false) { _ in
        signal.draw(in: NSRect(x: 0, y: 3, width: 18, height: 16))
        for (index, line) in lines.enumerated() {
            (line as NSString).draw(at: NSPoint(x: 23, y: index == 0 ? 11 : 0), withAttributes: attributes)
        }
        return true
    }
    image.isTemplate = true
    image.accessibilityDescription = "4G 信号 \(level) 格，下载 \(lines[0])，上传 \(lines[1])"
    return image
}

final class DockVisibilityController: ObservableObject {
    static let shared = DockVisibilityController()
    static let preferenceKey = "showInDock"
    @Published private(set) var visible: Bool
    @Published private(set) var error = ""
    var changed: (() -> Void)?

    private init() { visible = Self.savedValue(in: .standard) }

    static func savedValue(in defaults: UserDefaults) -> Bool {
        defaults.object(forKey: preferenceKey) == nil || defaults.bool(forKey: preferenceKey)
    }

    func applySaved() { setVisible(visible) }

    func setVisible(_ value: Bool) {
        let policy: NSApplication.ActivationPolicy = value ? .regular : .accessory
        if NSApp.activationPolicy() != policy { _ = NSApp.setActivationPolicy(policy) }
        guard NSApp.activationPolicy() == policy else {
            error = "系统未能更改 Dock 显示，请重试"
            changed?()
            return
        }
        visible = value
        error = ""
        UserDefaults.standard.set(value, forKey: Self.preferenceKey)
        changed?()
    }
}

struct MenuPresentationSection: View {
    @ObservedObject private var dock = DockVisibilityController.shared
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            MoreSectionTitle("菜单栏与 Dock")
            VStack(alignment: .leading, spacing: 10) {
                Toggle("在 Dock 中显示", isOn: Binding(get: { dock.visible }, set: dock.setVisible))
                    .toggleStyle(.switch).tint(.green)
                Text("关闭后仍在后台运行，可通过菜单栏或聚焦搜索重新打开窗口。")
                    .font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Text("菜单栏每秒更新当前出口的下载 ↓ / 上传 ↑ 速度。")
                    .font(.caption).foregroundStyle(.secondary)
                if !dock.error.isEmpty { Text(dock.error).font(.caption).foregroundStyle(.red) }
            }.padding(12).modifier(PhoneCard())
        }
    }
}

func menuPresentationSelfTest() {
    func counters(_ received: UInt64, _ sent: UInt64, name: String = "en0", index: UInt32 = 1) -> InterfaceCounters {
        InterfaceCounters(name: name, index: index, received: received, sent: sent)
    }
    var sampler = TransferSampler()
    precondition(sampler.update(counters(5_000_000_000, 7_000_000_000), at: 1) == nil)
    let rate = sampler.update(counters(5_002_097_152, 7_001_048_576), at: 3)!
    precondition(rate.download == 1_048_576 && rate.upload == 524_288)
    precondition(sampler.update(counters(0, 0, name: "en9", index: 9), at: 4) == nil)
    precondition(sampler.update(counters(100, 200, name: "en9", index: 9), at: 5)!.download == 100)
    precondition(sampler.update(counters(0, 0, name: "en9", index: 9), at: 6) == nil)
    precondition(sampler.update(nil, at: 7) == nil)
    precondition(sampler.update(counters(100, 200), at: 8) == nil)
    precondition(sampler.update(counters(200, 300), at: 15) == nil)
    precondition(sampler.update(counters(200, 300), at: 16)!.download == 0)
    precondition(TransferRate.format(0) == "0 B/s")
    precondition(TransferRate.format(1024) == "1.0 KB/s")
    precondition(TransferRate.format(1_572_864) == "1.5 MB/s")
    let suite = "DJOneHub-menu-test-" + UUID().uuidString
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    precondition(DockVisibilityController.savedValue(in: defaults))
    defaults.set(false, forKey: DockVisibilityController.preferenceKey)
    precondition(!DockVisibilityController.savedValue(in: defaults))
    print("64-bit transfer sampling and Dock preference checks passed")
}
