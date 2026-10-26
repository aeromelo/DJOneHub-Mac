import AppKit
import Foundation

func offerInstallation() -> Bool {
    guard Bundle.main.bundleURL.path.hasPrefix("/Volumes/") || CommandLine.arguments.contains("--install") else { return false }
    let app = NSApplication.shared
    app.setActivationPolicy(.regular)
    app.activate(ignoringOtherApps: true)
    let consent = NSAlert()
    consent.messageText = "安装 DJOneHub"
    consent.informativeText = "安装到当前用户的 Applications 文件夹，并设置登录启动。\n包含增强版 v1.2.9；原生管理界面与网络菜单已整合；已有模块配置和套餐统计将保留，更新成功后自动删除旧版 App。\n本项目及上游采用 PolyForm 非商业许可；继续表示接受随包 LICENSE 与第三方声明。\n安装本身不会切换 USB 模式、开启 ADB 或发送查询短信。"
    consent.addButton(withTitle: "同意并安装")
    consent.addButton(withTitle: "取消")
    guard consent.runModal() == .alertFirstButtonReturn else { return true }
    let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 430, height: 110), styleMask: [.titled], backing: .buffered, defer: false)
    window.title = "正在安装"
    let label = NSTextField(labelWithString: "正在复制程序并启动服务，请稍候…")
    label.frame = NSRect(x: 24, y: 57, width: 380, height: 24)
    let progress = NSProgressIndicator(frame: NSRect(x: 24, y: 25, width: 380, height: 16))
    progress.style = .bar
    progress.isIndeterminate = true
    progress.startAnimation(nil)
    window.contentView?.addSubview(label)
    window.contentView?.addSubview(progress)
    window.center()
    window.makeKeyAndOrderFront(nil)
    DispatchQueue.global().async {
        let process = Process()
        process.executableURL = Bundle.main.resourceURL!.appendingPathComponent("python/bin/python3")
        process.arguments = ["-I", "-B", Bundle.main.resourceURL!.appendingPathComponent("install_runtime.py").path]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        var detail = ""
        var succeeded = false
        do {
            try process.run()
            detail = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            process.waitUntilExit()
            succeeded = process.terminationStatus == 0
        } catch { detail = error.localizedDescription }
        let installed = succeeded
        let resultText = detail
        DispatchQueue.main.async {
            window.close()
            let alert = NSAlert()
            alert.messageText = installed ? "安装完成" : "安装未完成"
            alert.informativeText = installed ? "程序已设置登录启动。连接 4G 模块后，菜单栏入口会出现。\n可在菜单里点击“打开 DJOneHub”管理模块。" : String(resultText.suffix(1200))
            alert.runModal()
            app.terminate(nil)
        }
    }
    app.run()
    return true
}
