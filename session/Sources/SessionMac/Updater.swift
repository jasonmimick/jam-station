import SwiftUI
import AppKit

/// Session has no App Store, so it doesn't get App Store updates. This checks
/// /session/version (stamped fresh on every `make mac-release`) against the
/// build baked into THIS running copy, and — with the user's one click —
/// downloads, verifies, and replaces itself in place, then relaunches.
/// No Sparkle/external dependency: the whole dance is stdlib Process + FileManager.
@MainActor
final class Updater: ObservableObject {
    enum State: Equatable {
        case idle
        case checking
        case available(build: String, downloadPath: String)
        case downloading
        case failed(String)
    }

    @Published var state: State = .idle

    private var myBuild: String {
        Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "0.1.0"
    }

    /// Fire-and-forget on launch. Silent on any failure — a version-check
    /// hiccup shouldn't nag the user; it'll just check again next launch.
    func checkForUpdate(stationBase: URL) {
        guard state == .idle else { return }
        state = .checking
        Task {
            guard let url = URL(string: "/session/version", relativeTo: stationBase) else {
                state = .idle; return
            }
            do {
                let (data, _) = try await URLSession.shared.data(from: url)
                let resp = try JSONDecoder().decode(VersionResponse.self, from: data)
                // Both sides are YYYYMMDDHHMMSS stamps (Makefile's `date +%Y%m%d%H%M%S`),
                // so a plain string comparison IS a correct newer-than check.
                if resp.build > myBuild {
                    state = .available(build: resp.build, downloadPath: resp.url)
                } else {
                    state = .idle
                }
            } catch {
                state = .idle
            }
        }
    }

    /// Download -> unzip -> sanity-check -> hand off to a tiny relaunch script
    /// (since a running process can't cleanly replace its own binary while
    /// executing) -> quit. The script waits, so THIS process is fully gone
    /// before anything touches its bundle on disk.
    func installUpdate(stationBase: URL, downloadPath: String) {
        state = .downloading
        Task {
            do {
                guard let url = URL(string: downloadPath, relativeTo: stationBase) else {
                    state = .failed("bad update URL"); return
                }
                let (tmpZip, _) = try await URLSession.shared.download(from: url)

                let workDir = FileManager.default.temporaryDirectory
                    .appendingPathComponent("session-update-\(UUID().uuidString)", isDirectory: true)
                try FileManager.default.createDirectory(at: workDir, withIntermediateDirectories: true)
                let zipDest = workDir.appendingPathComponent("Session-mac.zip")
                try FileManager.default.moveItem(at: tmpZip, to: zipDest)

                let unzip = Process()
                unzip.executableURL = URL(fileURLWithPath: "/usr/bin/unzip")
                unzip.arguments = ["-q", zipDest.path, "-d", workDir.path]
                try unzip.run()
                unzip.waitUntilExit()
                guard unzip.terminationStatus == 0 else {
                    state = .failed("couldn't unpack the update"); return
                }

                let newApp = workDir.appendingPathComponent("Session.app")
                let newBinary = newApp.appendingPathComponent("Contents/MacOS/Session")
                guard FileManager.default.isExecutableFile(atPath: newBinary.path) else {
                    state = .failed("the downloaded update looks broken — try again later"); return
                }

                // Never rm -rf anything that isn't unmistakably an app bundle.
                let currentAppPath = Bundle.main.bundlePath
                guard currentAppPath.hasSuffix(".app") else {
                    state = .failed("couldn't identify where I'm installed"); return
                }

                let script = """
                #!/bin/bash
                sleep 2
                rm -rf "\(currentAppPath)"
                mv "\(newApp.path)" "\(currentAppPath)"
                open "\(currentAppPath)"
                rm -rf "\(workDir.path)"
                """
                let scriptURL = workDir.appendingPathComponent("relaunch.sh")
                try script.write(to: scriptURL, atomically: true, encoding: .utf8)
                try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: scriptURL.path)

                let relaunch = Process()
                relaunch.executableURL = URL(fileURLWithPath: "/bin/bash")
                relaunch.arguments = [scriptURL.path]
                try relaunch.run()   // detached; outlives us

                try? await Task.sleep(for: .seconds(1))
                NSApp.terminate(nil)
            } catch {
                state = .failed(error.localizedDescription)
            }
        }
    }

    private struct VersionResponse: Decodable { let build: String; let url: String }
}

/// A thin banner above the masthead — only visible when there's actually
/// something to say. Never blocks the app; the user can keep listening while
/// an update sits there waiting for one click.
struct UpdateBanner: View {
    @ObservedObject var updater: Updater
    let stationBase: URL
    let t: Theme

    var body: some View {
        switch updater.state {
        case .available(let build, let path):
            bar {
                Text("An update is ready.").font(.system(size: 12, weight: .semibold))
                Button("Update & Relaunch") {
                    updater.installUpdate(stationBase: stationBase, downloadPath: path)
                }
                .buttonStyle(.plain)
                .font(.system(size: 11, weight: .heavy))
                .padding(.horizontal, 10).padding(.vertical, 5)
                .background(t.onAccent).foregroundStyle(t.accent)
                .clipShape(RoundedRectangle(cornerRadius: 5))
            }
            .accessibilityHint("build \(build)")
        case .downloading:
            bar {
                ProgressView().controlSize(.small).tint(t.onAccent)
                Text("Updating\u{2026} Session will relaunch itself in a moment.")
                    .font(.system(size: 12, weight: .semibold))
            }
        case .failed(let reason):
            bar {
                Text("Update didn't go through: \(reason)").font(.system(size: 12, weight: .semibold))
            }
        case .idle, .checking:
            EmptyView()
        }
    }

    @ViewBuilder func bar<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        HStack(spacing: 10) {
            content()
            Spacer()
        }
        .padding(.horizontal, 16).padding(.vertical, 8)
        .background(t.accent)
        .foregroundStyle(t.onAccent)
    }
}
