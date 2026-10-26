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

    static func processStart(_ pid: pid_t) throws -> String {
        try command(["/bin/ps", "-p", String(pid), "-o", "lstart="])
    }

    static func alive(_ pid: pid_t) -> Bool { kill(pid, 0) == 0 || errno == EPERM }
    static func quote(_ value: String) -> String { "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'" }

    // Always restore after a failed enable as well: pmset can change state before
    // a subsequent read fails. Never take ownership of a pre-existing setting.
    static func session(read: () throws -> Bool, write: (Bool) throws -> Void,
                        wait: () -> Void) throws {
        guard try !read() else { throw failure("系统已经禁止休眠，未覆盖原设置") }
        do {
            try write(true)
            wait()
        } catch {
            try write(false)
            throw error
        }
        try write(false)
    }
}

// A small root child owns only this one power setting. It never executes files
// supplied by the user, installs a daemon, or reads module/account information.
// Parent death (including force quit) or deletion of the lease ends the session.
func runLidGuardIfRequested() -> Bool {
    let args = CommandLine.arguments
    guard args.count > 1 && args[1] == "--lid-guard" else { return false }
    guard args.count == 5, geteuid() == 0, let owner = pid_t(args[2]), owner > 1 else { exit(64) }
    let started = args[3], lease = args[4]
    func ownerPresent() -> Bool {
        FileManager.default.fileExists(atPath: lease) && LidPower.alive(owner)
            && (try? LidPower.processStart(owner)) == started
    }
    guard ownerPresent() else { exit(65) }
    let stopped = DispatchSemaphore(value: 0)
    var sources: [DispatchSourceSignal] = []
    for number in [SIGTERM, SIGINT, SIGHUP] {
        signal(number, SIG_IGN)
        let source = DispatchSource.makeSignalSource(signal: number, queue: .global())
        source.setEventHandler { stopped.signal() }
        source.resume()
        sources.append(source)
    }
    do {
        try LidPower.session(read: LidPower.disabled, write: LidPower.setDisabled) {
            while ownerPresent() && stopped.wait(timeout: .now() + 0.5) == .timedOut {}
        }
        for source in sources { source.cancel() }
        exit(0)
    } catch {
        fputs("DJOneHub lid guard: \(error.localizedDescription)\n", stderr)
        exit(1)
    }
}

final class ClosedLidController: ObservableObject {
    static let shared = ClosedLidController()
    @Published private(set) var enabled = false
    @Published private(set) var busy = false
    @Published private(set) var message = "仅本次运行生效；开启时需要管理员授权"
    @Published private(set) var needsRestore = false
    var changed: (() -> Void)?
    private var lease: URL?
    private var guardPID: pid_t?
    private var guardProcess: Process?
    private var timer: Timer?
    private let queue = DispatchQueue(label: "djonehub.closed-lid")
    private let recovery = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/DJOneHubNetworkMenu/lid-restore-needed")

    func start() {
        guard timer == nil else { return }
        timer = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { [weak self] _ in self?.check() }
        // A forced reboot or a separately killed root guard can interrupt cleanup.
        // Offer explicit recovery only for a session this App previously owned.
        queue.asyncAfter(deadline: .now() + 2) {
            guard FileManager.default.fileExists(atPath: self.recovery.path) else { return }
            if (try? LidPower.disabled()) == false {
                try? FileManager.default.removeItem(at: self.recovery)
            } else {
                DispatchQueue.main.async {
                    guard !self.enabled && !self.busy else { return }
                    self.needsRestore = true
                    self.message = "上次合盖保护未完成清理，请恢复系统休眠"
                    self.changed?()
                }
            }
        }
    }

    private func check() {
        guard !busy, let pid = guardPID else { return }
        queue.async {
            let active = LidPower.alive(pid) && (try? LidPower.disabled()) == true
            DispatchQueue.main.async {
                guard !self.busy, self.guardPID == pid else { return }
                if !active {
                    self.enabled = false
                    self.needsRestore = true
                    self.message = "合盖保护已中断，请点击恢复系统休眠"
                    self.changed?()
                }
            }
        }
    }

    func toggle() {
        guard !busy else { return }
        let turnOn = !enabled && !needsRestore
        busy = true
        message = turnOn ? "等待系统授权并开启…" : "正在恢复系统休眠…"
        changed?()
        let previousLease = lease
        queue.async {
            var newLease: URL?
            let result = Result { () throws -> Process? in
                if turnOn {
                    guard try !LidPower.disabled() else {
                        throw LidPower.failure("系统已由其他设置禁止休眠；DJOneHub 未修改")
                    }
                    let directory = FileManager.default.homeDirectoryForCurrentUser
                        .appendingPathComponent("Library/Application Support/DJOneHubNetworkMenu/lid-sessions")
                    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                           attributes: [.posixPermissions: 0o700])
                    let file = directory.appendingPathComponent(UUID().uuidString)
                    try Data().write(to: file, options: .atomic)
                    newLease = file
                    let owner = ProcessInfo.processInfo.processIdentifier
                    let executable = Bundle.main.executableURL!.path
                    let command = [LidPower.quote(executable), "--lid-guard", String(owner),
                                   LidPower.quote(try LidPower.processStart(owner)), LidPower.quote(file.path)]
                        .joined(separator: " ")
                    // Keep the authorized command in the foreground of our
                    // osascript child. Detached children of the authorization
                    // shell can be terminated when that shell exits on macOS.
                    let process = try Self.authorizedProcess(command)
                    for _ in 0..<1200 {
                        if !process.isRunning { throw Self.authorizationError(process) }
                        if (try? LidPower.disabled()) == true { return process }
                        Thread.sleep(forTimeInterval: 0.1)
                    }
                    process.terminate()
                    throw LidPower.failure("合盖保护未生效，已取消")
                } else {
                    if let file = previousLease, FileManager.default.fileExists(atPath: file.path) {
                        try FileManager.default.removeItem(at: file)
                    }
                    for _ in 0..<30 {
                        if (try? LidPower.disabled()) == false { return nil }
                        Thread.sleep(forTimeInterval: 0.1)
                    }
                    // Used only if the guard was interrupted and could not clean up.
                    let process = try Self.authorizedProcess("/usr/bin/pmset -a disablesleep 0")
                    process.waitUntilExit()
                    guard process.terminationStatus == 0 else { throw Self.authorizationError(process) }
                    guard try !LidPower.disabled() else { throw LidPower.failure("未能恢复系统休眠，请重试") }
                    return nil
                }
            }
            if case .failure = result, let file = newLease { try? FileManager.default.removeItem(at: file) }
            DispatchQueue.main.async {
                self.busy = false
                switch result {
                case .success(let process):
                    self.guardProcess = process
                    self.guardPID = process?.processIdentifier
                    self.lease = turnOn ? newLease : nil
                    self.enabled = turnOn
                    self.needsRestore = false
                    if turnOn { try? Data("restore SleepDisabled to 0".utf8).write(to: self.recovery, options: .atomic) }
                    else { try? FileManager.default.removeItem(at: self.recovery) }
                    self.message = turnOn ? "合盖保持运行；关闭或退出 App 后恢复休眠" : "已关闭；系统休眠设置已恢复"
                case .failure(let error):
                    self.message = error.localizedDescription
                    if !turnOn { self.enabled = false; self.needsRestore = true }
                }
                self.changed?()
            }
        }
    }

    private static func authorizedProcess(_ command: String) throws -> Process {
        let literal = command.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", "do shell script \"\(literal)\" with administrator privileges"]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = Pipe()
        try process.run()
        return process
    }

    private static func authorizationError(_ process: Process) -> Error {
        let data = (process.standardError as? Pipe)?.fileHandleForReading.readDataToEndOfFile() ?? Data()
        let detail = String(decoding: data, as: UTF8.self)
        return LidPower.failure(detail.contains("(-128)") ? "已取消管理员授权，未开启合盖保护" : "系统未能开启合盖保护：\(detail.prefix(300))")
    }

    func stop() {
        timer?.invalidate()
        // No authorization is needed to stop: the already-authorized guard
        // restores the original value within its next half-second poll.
        if let file = lease { try? FileManager.default.removeItem(at: file) }
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
    var values: [Bool] = []
    try! LidPower.session(read: { false }, write: { values.append($0) }, wait: {})
    precondition(values == [true, false])
    values = []
    do { try LidPower.session(read: { true }, write: { values.append($0) }, wait: {}); preconditionFailure("Overrode existing state") } catch {}
    precondition(values.isEmpty)
    values = []
    do {
        try LidPower.session(read: { false }, write: { value in
            values.append(value)
            if value { throw LidPower.failure("Simulated enable/read failure") }
        }, wait: { preconditionFailure("Waited after failed enable") })
        preconditionFailure("Ignored enable failure")
    } catch {}
    precondition(values == [true, false])
    do {
        try LidPower.session(read: { false }, write: { if !$0 { throw LidPower.failure("Simulated restore failure") } }, wait: {})
        preconditionFailure("Ignored restore failure")
    } catch {}
    precondition(LidPower.quote("/tmp/a'b") == "'/tmp/a'\\''b'")
    print("Closed-lid power parsing, ownership and restoration checks passed")
}
