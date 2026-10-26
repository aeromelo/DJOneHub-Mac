import Foundation
import Darwin

@objc protocol DJLidPowerProtocol {
    func setEnabled(_ value: Bool, reply: @escaping (Bool, String) -> Void)
}

enum LidHelperInstallation {
    static let label = "io.github.aeromelo.djonehub.lidpower"
    static let executable = "/Library/PrivilegedHelperTools/" + label
    static let plist = "/Library/LaunchDaemons/" + label + ".plist"
    static var installed: Bool {
        FileManager.default.fileExists(atPath: executable) && FileManager.default.fileExists(atPath: plist)
    }

    static func ensure() throws {
        guard !installed else { return }
        let temporary = FileManager.default.temporaryDirectory.appendingPathComponent("DJOneHub-lid-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: temporary, withIntermediateDirectories: false,
                                               attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: temporary) }
        let source = temporary.appendingPathComponent("service.plist")
        let config: [String: Any] = ["Label": label,
            "ProgramArguments": [executable, "--lid-service", String(getuid())],
            "MachServices": [label: true], "RunAtLoad": true, "KeepAlive": true,
            "ThrottleInterval": 3]
        try PropertyListSerialization.data(fromPropertyList: config, format: .xml, options: 0).write(to: source)
        let script = "set -e\n/usr/bin/codesign --verify --strict " + LidPower.quote(Bundle.main.executableURL!.path)
            + "\n/bin/mkdir -p /Library/PrivilegedHelperTools"
            + "\n/usr/bin/install -o root -g wheel -m 755 " + LidPower.quote(Bundle.main.executableURL!.path) + " " + LidPower.quote(executable)
            + "\n/usr/bin/codesign --force --sign - " + LidPower.quote(executable)
            + "\n/usr/bin/codesign --verify --strict " + LidPower.quote(executable)
            + "\n/usr/bin/install -o root -g wheel -m 644 " + LidPower.quote(source.path) + " " + LidPower.quote(plist)
            + "\n/bin/launchctl bootstrap system " + LidPower.quote(plist)
        let literal = script.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"").replacingOccurrences(of: "\n", with: "\\n")
        _ = try LidPower.command(["/usr/bin/osascript", "-e", "do shell script \"" + literal + "\" with administrator privileges"])
        guard installed else { throw LidPower.failure("首次配置未完成，请重新开启并批准系统授权") }
    }
}

final class LidPowerService {
    private let queue = DispatchQueue(label: "djonehub.lidpower.service")
    private var owner: UUID?
    private let journal: URL
    private let read: () throws -> Bool
    private let write: (Bool) throws -> Void

    init(journal: URL = URL(fileURLWithPath: "/var/db/io.github.aeromelo.djonehub.lidpower/active"),
         read: @escaping () throws -> Bool = LidPower.disabled,
         write: @escaping (Bool) throws -> Void = LidPower.setDisabled) {
        self.journal = journal
        self.read = read
        self.write = write
    }

    func recover() throws {
        if FileManager.default.fileExists(atPath: journal.path) {
            try write(false)
            try FileManager.default.removeItem(at: journal)
        }
    }

    func set(_ enabled: Bool, token: UUID, reply: @escaping (Bool, String) -> Void) {
        queue.async {
            do {
                if enabled {
                    if self.owner == token { reply(true, ""); return }
                    guard self.owner == nil, try !self.read() else {
                        throw LidPower.failure("系统已由其他设置禁止休眠，未覆盖原设置")
                    }
                    try FileManager.default.createDirectory(at: self.journal.deletingLastPathComponent(),
                        withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
                    try Data("restore SleepDisabled to 0".utf8).write(to: self.journal, options: .atomic)
                    self.owner = token
                    try self.write(true)
                } else {
                    try self.restore(token)
                }
                reply(self.owner == token, "")
            } catch {
                // An enable may fail after pmset has changed the setting.
                if enabled { try? self.restore(token) }
                reply(false, error.localizedDescription)
            }
        }
    }

    private func restore(_ token: UUID) throws {
        guard owner == token else { return }
        try write(false)
        try FileManager.default.removeItem(at: journal)
        owner = nil
    }

    func close(_ token: UUID) { queue.async { try? self.restore(token) } }
    func shutdown() { queue.sync { if let token = self.owner { try? self.restore(token) } } }
}

private final class LidPowerSession: NSObject, DJLidPowerProtocol {
    let token = UUID()
    let service: LidPowerService
    init(_ service: LidPowerService) { self.service = service }
    func setEnabled(_ value: Bool, reply: @escaping (Bool, String) -> Void) {
        service.set(value, token: token, reply: reply)
    }
}

private final class LidPowerListener: NSObject, NSXPCListenerDelegate {
    let allowedUser: uid_t
    let service: LidPowerService
    init(user: uid_t, service: LidPowerService) { allowedUser = user; self.service = service }
    func listener(_ listener: NSXPCListener, shouldAcceptNewConnection connection: NSXPCConnection) -> Bool {
        guard connection.effectiveUserIdentifier == allowedUser else { return false }
        let session = LidPowerSession(service)
        connection.exportedInterface = NSXPCInterface(with: DJLidPowerProtocol.self)
        connection.exportedObject = session
        connection.invalidationHandler = { session.service.close(session.token) }
        connection.resume()
        return true
    }
}

func runLidServiceIfRequested() -> Bool {
    let args = CommandLine.arguments
    guard args.count > 1 && args[1] == "--lid-service" else { return false }
    guard args.count == 3, geteuid() == 0, let user = uid_t(args[2]), user > 0 else { exit(64) }
    let service = LidPowerService()
    do { try service.recover() } catch { exit(1) }
    let delegate = LidPowerListener(user: user, service: service)
    let listener = NSXPCListener(machServiceName: LidHelperInstallation.label)
    listener.delegate = delegate
    var signals: [DispatchSourceSignal] = []
    for number in [SIGTERM, SIGINT, SIGHUP] {
        signal(number, SIG_IGN)
        let source = DispatchSource.makeSignalSource(signal: number, queue: .global())
        source.setEventHandler { service.shutdown(); exit(0) }
        source.resume()
        signals.append(source)
    }
    listener.resume()
    withExtendedLifetime((listener, delegate, signals)) { dispatchMain() }
}

func lidServiceSelfTest() {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent("DJOneHub-power-test-" + UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: root) }
    let journal = root.appendingPathComponent("active")
    var disabled = false
    let service = LidPowerService(journal: journal, read: { disabled }, write: { disabled = $0 })
    func set(_ enabled: Bool, token: UUID) -> (Bool, String) {
        let done = DispatchSemaphore(value: 0)
        var result = (false, "no reply")
        service.set(enabled, token: token) { value, error in result = (value, error); done.signal() }
        precondition(done.wait(timeout: .now() + 2) == .success)
        return result
    }
    let owner = UUID(), other = UUID()
    precondition(set(true, token: owner).0 && disabled)
    precondition(!set(false, token: other).0 && disabled)
    precondition(!set(true, token: other).1.isEmpty && disabled)
    precondition(!set(false, token: owner).0 && !disabled)
    precondition(!FileManager.default.fileExists(atPath: journal.path))
    precondition(set(true, token: owner).0)
    service.close(owner)
    service.shutdown() // waits until close has restored the setting
    precondition(!disabled)
    try! FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    try! Data().write(to: journal)
    disabled = true
    try! service.recover()
    precondition(!disabled && !FileManager.default.fileExists(atPath: journal.path))
    print("Lid service ownership, disconnect and restart recovery checks passed")
}
