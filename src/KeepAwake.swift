import AppKit
import Foundation
import SwiftUI
import Darwin

enum LidPower {
    static func command(_ arguments: [String]) throws -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: arguments[0])
        process.arguments = Array(arguments.dropFirst())
        let output = Pipe()
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        try process.run()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else { throw failure("系统电源操作未成功") }
        return String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func failure(_ message: String) -> NSError {
        NSError(domain: "DJOneHub.LidPower", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }

    static func parseDisabled(_ output: String) throws -> Bool {
        for row in output.split(separator: "\n") {
            let fields = row.split(whereSeparator: { $0.isWhitespace })
            if fields.count == 2 && fields[0] == "SleepDisabled" {
                if fields[1] == "0" { return false }
                if fields[1] == "1" { return true }
            }
        }
        throw failure("系统未提供合盖休眠控制状态，未修改设置")
    }

    static func disabled() throws -> Bool { try parseDisabled(command(["/usr/bin/pmset", "-g"])) }

    static func setDisabled(_ value: Bool) throws {
        _ = try command(["/usr/bin/pmset", "-a", "disablesleep", value ? "1" : "0"])
        guard try disabled() == value else { throw failure("系统没有接受休眠设置") }
    }

    static func quote(_ value: String) -> String { "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'" }

}

final class ClosedLidController: ObservableObject {
    static let shared = ClosedLidController()
    @Published private(set) var enabled = false
    @Published private(set) var busy = false
    @Published private(set) var message = "首次配置授权一次，之后开关无需登录密码"
    @Published private(set) var needsRestore = false
    var changed: (() -> Void)?
    private var connection: NSXPCConnection?
    private let queue = DispatchQueue(label: "djonehub.closed-lid.install")
    private var operation = UUID()

    func start() {
        if LidHelperInstallation.installed { message = "已完成首次配置，开关无需登录密码" }
    }

    func toggle() {
        guard !busy else { return }
        let turnOn = !enabled && !needsRestore
        busy = true
        message = LidHelperInstallation.installed ? "正在更新合盖保护…" : "首次配置，等待一次系统授权…"
        changed?()
        let token = UUID()
        operation = token
        queue.async {
            let result = Result { try LidHelperInstallation.ensure() }
            DispatchQueue.main.async {
                guard self.operation == token else { return }
                switch result {
                case .failure:
                    self.fail("首次配置未完成；请允许系统管理员授权", restoring: !turnOn)
                case .success:
                    self.send(turnOn, token: token)
                }
            }
        }
    }

    private func send(_ turnOn: Bool, token: UUID) {
        if connection == nil {
            let client = NSXPCConnection(machServiceName: LidHelperInstallation.label, options: .privileged)
            client.remoteObjectInterface = NSXPCInterface(with: DJLidPowerProtocol.self)
            let disconnected = { [weak self, weak client] in
                DispatchQueue.main.async {
                    guard let self = self, self.connection === client else { return }
                    self.connection = nil
                    self.fail("合盖服务已中断，请重新开启或恢复休眠", restoring: self.enabled)
                }
            }
            client.interruptionHandler = disconnected
            client.invalidationHandler = disconnected
            client.resume()
            connection = client
        }
        guard let proxy = connection?.remoteObjectProxyWithErrorHandler({ [weak self] _ in
            DispatchQueue.main.async {
                guard let self = self, self.operation == token else { return }
                self.fail("合盖服务未就绪，请稍后重试", restoring: !turnOn)
            }
        }) as? DJLidPowerProtocol else {
            fail("无法连接合盖服务", restoring: !turnOn); return
        }
        proxy.setEnabled(turnOn) { [weak self] actual, error in
            DispatchQueue.main.async {
                guard let self = self, self.operation == token else { return }
                guard error.isEmpty, actual == turnOn else {
                    self.fail(error.isEmpty ? "系统未能应用合盖设置" : error, restoring: !turnOn); return
                }
                self.busy = false
                self.enabled = actual
                self.needsRestore = false
                self.message = actual ? "合盖保持联网；关闭或退出 App 后恢复休眠" : "已关闭；系统休眠已恢复，后续开关无需密码"
                self.changed?()
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 10) { [weak self] in
            guard let self = self, self.operation == token, self.busy else { return }
            self.fail("合盖服务响应超时，请重试", restoring: !turnOn)
        }
    }

    private func fail(_ message: String, restoring: Bool) {
        operation = UUID()
        stop()
        busy = false
        enabled = false
        needsRestore = restoring
        self.message = message
        changed?()
    }

    func stop() {
        // The service restores power settings when this XPC connection closes,
        // including normal quit, force quit and loss of the user session.
        connection?.invalidationHandler = nil
        connection?.interruptionHandler = nil
        connection?.invalidate()
        connection = nil
    }
}

struct ClosedLidSection: View {
    @ObservedObject private var power = ClosedLidController.shared
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            MoreSectionTitle("电源")
            VStack(alignment: .leading, spacing: 10) {
                Toggle("合盖不休眠", isOn: Binding(get: { power.enabled }, set: { _ in power.toggle() }))
                    .toggleStyle(.switch).tint(.green).disabled(power.busy || power.needsRestore)
                Text(power.message).font(.caption).foregroundStyle(power.needsRestore ? Color.red : Color.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if power.needsRestore {
                    Button("恢复系统休眠") { power.toggle() }
                        .buttonStyle(SettingsActionButtonStyle()).disabled(power.busy)
                }
                Text("接电或电池均生效，允许屏幕熄灭；同时会阻止手动睡眠。开启后保持散热，装包携带前请关闭。")
                    .font(.caption2).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }.padding(12).modifier(PhoneCard())
        }
    }
}

func closedLidSelfTest() {
    precondition(try! LidPower.parseDisabled("System-wide power settings:\n SleepDisabled\t0\nAC Power:\n sleep 1") == false)
    precondition(try! LidPower.parseDisabled(" SleepDisabled 1") == true)
    do { _ = try LidPower.parseDisabled("sleep 0"); preconditionFailure("Missing state accepted") } catch {}
    precondition(LidPower.quote("/tmp/a'b") == "'/tmp/a'\\''b'")
    print("Closed-lid power parsing checks passed")
}
