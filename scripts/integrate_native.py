"""Apply reviewed integration to pristine, licensed v1.2.9 native sources."""
from pathlib import Path
import shutil


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Pinned upstream integration anchor changed: ' + old[:70])
    return text.replace(old, new, 1)


def prepare(root, destination):
    shutil.copytree(root / 'vendor/djonehub-enhanced', destination)
    sources = destination / 'Sources/DJOneHubNotifier'
    for name in ('NetworkMenu.swift', 'Installer.swift', 'SettingsButtons.swift', 'About.swift', 'KeepAwake.swift', 'LidService.swift'):
        shutil.copy2(root / 'src' / name, sources / name)
    path = sources / 'AppMain.swift'
    text = path.read_text()
    text = replace_once(text, '            SelfTest.run()', '            SelfTest.run()\n            networkMenuSelfTest()\n            updateCheckerSelfTest()\n            closedLidSelfTest()\n            lidServiceSelfTest()')
    text = replace_once(text, '    static func main() {', '    static func main() {\n        if runLidServiceIfRequested() { return }')
    text = replace_once(text, '        let app = NSApplication.shared', '        if offerInstallation() { return }\n        let app = NSApplication.shared')
    text = replace_once(text, '    private let api: DJOneHubAPI', '    private let networkMenu = NetworkMenu()\n    private let api: DJOneHubAPI')
    text = replace_once(text, '    private var mainWindow: NSWindow?', '    private var mainWindow: NSWindow?\n    private var aboutWindow: NSWindow?')
    text = replace_once(text, '        let demoCall = CommandLine.arguments.contains("--show-call")', '        networkMenu.openManagement = { [weak self] in self?.showMainWindow() }\n        networkMenu.applicationDidFinishLaunching(notification)\n        let demoCall = CommandLine.arguments.contains("--show-call")')
    text = replace_once(text, '        if CommandLine.arguments.contains("--show-window") {', '        if !CommandLine.arguments.contains("--background") || CommandLine.arguments.contains("--show-window") {')
    text = replace_once(text, '    func applicationWillTerminate(_ notification: Notification) {', '    func applicationWillTerminate(_ notification: Notification) {\n        if !healthCheck && previewMode == nil { networkMenu.applicationWillTerminate(notification) }')
    start = text.index('    private func pollCellularStatus() async {')
    end = text.index('    private func showCellularStatusItem', start)
    text = text[:start] + '    private func pollCellularStatus() async {\n        // Unified NetworkMenu owns the sole cellular signal indicator.\n        networkMenu.refresh()\n    }\n\n' + text[end:]
    # NetworkMenu owns wake routing; upstream keeps backend/USB recovery.
    text = replace_once(text, 'action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)),',
                        'action: #selector(showAboutWindow(_:)),')
    text = replace_once(text, '        appMenu.addItem(.separator())\n        appMenu.addItem(\n            withTitle: "隐藏 DJOneHub",',
                        '        appMenu.items.first?.target = self\n        appMenu.addItem(.separator())\n        appMenu.addItem(\n            withTitle: "隐藏 DJOneHub",')
    text = replace_once(text, '    private func installMainMenu() {', '''    @objc private func showAboutWindow(_ sender: Any?) {
        if aboutWindow == nil {
            let root = ScrollView { AboutDJOneHubSection().padding(16) }
                .preferredColorScheme(appSettings.appearance.colorScheme)
            let window = NSWindow(contentViewController: NSHostingController(rootView: root))
            window.title = "关于 DJOneHub"
            window.styleMask = [.titled, .closable, .resizable]
            window.setContentSize(NSSize(width: 420, height: 360))
            window.center()
            window.isReleasedWhenClosed = false
            aboutWindow = window
        }
        aboutWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func installMainMenu() {''')
    path.write_text(text)
    phone = sources / 'PhoneAppView.swift'
    text = phone.read_text().replace('"com.jamie.djonehub-notifier",', '')
    text = replace_once(text, '.buttonStyle(.bordered)\n                            .tint(.red)\n                            .controlSize(.regular)',
                        '.buttonStyle(SettingsActionButtonStyle(destructive: true))\n                            .controlSize(.regular)')
    text = replace_once(text, '                    MoreView()\n\n                    MoreSectionTitle(L10n.t("服务控制"))',
                        '                    MoreView()\n\n                    ClosedLidSection()\n\n                    AboutDJOneHubSection()\n\n                    MoreSectionTitle(L10n.t("服务控制"))')
    phone.write_text(text)
    apply_settings_button_colors(sources / 'MoreView.swift')


def apply_settings_button_colors(path):
    text = path.read_text()
    text = replace_once(text, '    @State private var networkDiag: NetworkDiagnostic?',
                        '    @State private var cellularCheckPassed: Bool?\n    @State private var proxyCheckPassed: Bool?\n    @State private var networkDiag: NetworkDiagnostic?')
    for name, method, state in (('检查 4G 出口', 'check4GRoute', 'cellularCheckPassed'),
                                ('检查代理出口', 'checkProxyRoute', 'proxyCheckPassed')):
        text = replace_once(text, 'MoreActionButton(title: L10n.t("%s"))' % name,
                            'MoreActionButton(title: L10n.t("%s"), passed: %s)' % (name, state))
        old = ('                            runCheck(try await calls.apiClient.%s())\n'
               '                        } catch {\n                            message = error.localizedDescription') % method
        new = ('                            let result = try await calls.apiClient.%s()\n'
               '                            %s = result.ok\n                            runCheck(result)\n'
               '                        } catch {\n                            %s = false\n                            message = error.localizedDescription') % (method, state, state)
        text = replace_once(text, old, new)
    text = replace_once(text, '    var destructive = false\n    let action:',
                        '    var destructive = false\n    var passed: Bool? = nil\n    let action:')
    text = replace_once(text, 'Text(running ? L10n.t("处理中…") : title)',
                        'Text(running ? L10n.t("处理中…") : title + (passed.map { $0 ? " ✓" : " !" } ?? ""))')
    text = replace_once(text, '.buttonStyle(.bordered)\n        .controlSize(.regular)\n        .tint(destructive ? .red : nil)',
                        '.buttonStyle(SettingsActionButtonStyle(destructive: destructive || passed == false))\n        .controlSize(.regular)')
    text = replace_once(text, '.buttonStyle(.bordered)\n                    .controlSize(.small)\n                    .disabled(busy || usbProfile == nil)',
                        '.buttonStyle(SettingsActionButtonStyle())\n                    .controlSize(.small)\n                    .disabled(busy || usbProfile == nil)')
    text = replace_once(text, '                        .frame(maxWidth: 150)\n                        Spacer()',
                        '                        .frame(maxWidth: 150)\n                        .disabled(esim == nil || esim?.cardType == "physical_sim")\n                        Spacer()')
    text = replace_once(text, '            set: { allow in\n                busy = true',
                        '            set: { allow in\n                cellularCheckPassed = nil\n                proxyCheckPassed = nil\n                busy = true')
    text = replace_once(text, '    private func applyUSBProfile(_ mode: String) async {\n        busy = true',
                        '    private func applyUSBProfile(_ mode: String) async {\n        cellularCheckPassed = nil\n        proxyCheckPassed = nil\n        busy = true')
    path.write_text(text)
