import AppKit
import Foundation
import SwiftUI

struct PublishedDJOneHubRelease: Decodable {
    let tag_name: String
    let html_url: URL
    let draft: Bool
    let prerelease: Bool
}

enum DJOneHubUpdates {
    static let projectURL = URL(string: "https://github.com/aeromelo/DJOneHub-Mac")!
    static let releasesURL = projectURL.appendingPathComponent("releases/latest")
    static let apiURL = URL(string: "https://api.github.com/repos/aeromelo/DJOneHub-Mac/releases/latest")!

    static func compare(_ latest: String, with current: String) throws -> Int {
        func parts(_ value: String) throws -> [Int] {
            let value = value.hasPrefix("v") ? String(value.dropFirst()) : value
            let numbers = value.split(separator: ".", omittingEmptySubsequences: false).compactMap { Int($0) }
            guard numbers.count == 3,
                  value.range(of: "^[0-9]+\\.[0-9]+\\.[0-9]+$", options: .regularExpression) != nil else {
                throw NSError(domain: "DJOneHubUpdates", code: 1,
                              userInfo: [NSLocalizedDescriptionKey: "发布版本格式无法识别"])
            }
            return numbers
        }
        let newest = try parts(latest), installed = try parts(current)
        if newest == installed { return 0 }
        return installed.lexicographicallyPrecedes(newest) ? 1 : -1
    }

    static func fetch() async throws -> PublishedDJOneHubRelease {
        var request = URLRequest(url: apiURL, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 15)
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        request.setValue("DJOneHub-Mac", forHTTPHeaderField: "User-Agent")
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let response = response as? HTTPURLResponse, response.statusCode == 200 else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            let message = code == 403 || code == 429 ? "GitHub 暂时限制查询，请稍后重试" : "检查更新失败 · HTTP \(code)"
            throw NSError(domain: "DJOneHubUpdates", code: code, userInfo: [NSLocalizedDescriptionKey: message])
        }
        let release = try JSONDecoder().decode(PublishedDJOneHubRelease.self, from: data)
        guard !release.draft, !release.prerelease,
              release.html_url.scheme == "https", release.html_url.host == "github.com",
              release.html_url.path.hasPrefix("/aeromelo/DJOneHub-Mac/releases/tag/") else {
            throw NSError(domain: "DJOneHubUpdates", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "未取得有效的正式发布信息"])
        }
        return release
    }
}

struct AboutDJOneHubSection: View {
    @State private var checking = false
    @State private var resultText = ""
    @State private var failed = false
    @State private var availableRelease: PublishedDJOneHubRelease?
    private let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "未知"
    private let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "未知"

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            MoreSectionTitle("关于")
            VStack(alignment: .leading, spacing: 12) {
                Text("DJOneHub Mac").font(.headline)
                MoreInfoRow(label: "版本", value: "\(version)（构建 \(build)）")
                Button(checking ? "正在检查更新…" : "检查更新") {
                    Task { await checkForUpdates() }
                }
                .buttonStyle(SettingsActionButtonStyle(destructive: failed))
                .disabled(checking)
                if !resultText.isEmpty {
                    Text(resultText)
                        .font(.caption)
                        .foregroundStyle(failed ? Color.red : availableRelease == nil ? Color.secondary : Color.green)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let release = availableRelease {
                    Link("打开 \(release.tag_name) 下载页面", destination: release.html_url)
                        .buttonStyle(SettingsActionButtonStyle())
                }
                Link("github.com/aeromelo/DJOneHub-Mac", destination: DJOneHubUpdates.projectURL)
                    .font(.footnote)
                Text("PolyForm 非商业许可 · 原版与增强版引用见 GitHub 声明")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            .padding(12)
            .modifier(PhoneCard())
        }
    }

    @MainActor
    private func checkForUpdates() async {
        guard !checking else { return }
        checking = true
        failed = false
        availableRelease = nil
        resultText = ""
        defer { checking = false }
        do {
            let release = try await DJOneHubUpdates.fetch()
            switch try DJOneHubUpdates.compare(release.tag_name, with: version) {
            case 1:
                availableRelease = release
                resultText = "发现新版本 \(release.tag_name)；当前为 \(version)"
            case -1:
                resultText = "当前版本 \(version)；GitHub 最新正式版为 \(release.tag_name)"
            default:
                resultText = "已是最新版本（\(version)）"
            }
        } catch {
            failed = true
            resultText = "未能完成检查：\(error.localizedDescription)"
        }
    }
}

func updateCheckerSelfTest() {
    precondition(try! DJOneHubUpdates.compare("v1.0.10", with: "1.0.9") == 1)
    precondition(try! DJOneHubUpdates.compare("v1.0.3", with: "1.0.3") == 0)
    precondition(try! DJOneHubUpdates.compare("v1.0.2", with: "1.0.3") == -1)
    do {
        _ = try DJOneHubUpdates.compare("not-a-version", with: "1.0.3")
        preconditionFailure("Invalid version accepted")
    } catch {}
    print("Update version checks passed")
}
