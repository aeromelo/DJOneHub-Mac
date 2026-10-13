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
    for name in ('NetworkMenu.swift', 'Installer.swift'):
        shutil.copy2(root / 'src' / name, sources / name)
    path = sources / 'AppMain.swift'
    text = path.read_text()
    text = replace_once(text, '            SelfTest.run()', '            SelfTest.run()\n            networkMenuSelfTest()')
    text = replace_once(text, '        let app = NSApplication.shared', '        if offerInstallation() { return }\n        let app = NSApplication.shared')
    text = replace_once(text, '    private let api: DJOneHubAPI', '    private let networkMenu = NetworkMenu()\n    private let api: DJOneHubAPI')
    text = replace_once(text, '        let demoCall = CommandLine.arguments.contains("--show-call")', '        networkMenu.openManagement = { [weak self] in self?.showMainWindow() }\n        networkMenu.applicationDidFinishLaunching(notification)\n        let demoCall = CommandLine.arguments.contains("--show-call")')
    text = replace_once(text, '        if CommandLine.arguments.contains("--show-window") {', '        if !CommandLine.arguments.contains("--background") || CommandLine.arguments.contains("--show-window") {')
    text = replace_once(text, '    func applicationWillTerminate(_ notification: Notification) {', '    func applicationWillTerminate(_ notification: Notification) {\n        if !healthCheck && previewMode == nil { networkMenu.applicationWillTerminate(notification) }')
    start = text.index('    private func pollCellularStatus() async {')
    end = text.index('    private func showCellularStatusItem', start)
    text = text[:start] + '    private func pollCellularStatus() async {\n        // Unified NetworkMenu owns the sole cellular signal indicator.\n        networkMenu.refresh()\n    }\n\n' + text[end:]
    # NetworkMenu owns wake routing; upstream keeps backend/USB recovery.
    path.write_text(text)
    phone = sources / 'PhoneAppView.swift'
    text = phone.read_text().replace('"com.jamie.djonehub-notifier",', '')
    phone.write_text(text)
