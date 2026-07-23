import SwiftUI
import AppKit
import UniformTypeIdentifiers

/// Send Music — the native sibling of tools/jam-outbox.command. Drop a folder,
/// it rsyncs into the family radio's contributor inbox over the SAME restricted
/// account (mark@jasons-mac-mini) and dedicated key as the standalone script;
/// jam-inbox.sh on the mini turns it into a station within ~20s, same as always.
/// Deliberately self-contained (no Player/SessionCore dependency) — this is a
/// one-way upload utility, not a playback surface.
struct ContributeView: View {
    let t: Theme
    @StateObject private var uploader = Uploader()
    @State private var isTargeted = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("SEND MUSIC").font(.system(size: 12, weight: .heavy)).tracking(2)
                    .foregroundStyle(t.ink)
                Spacer()
                Text("-> the family radio's inbox")
                    .font(.system(size: 9, weight: .heavy)).tracking(1)
                    .foregroundStyle(t.faint)
            }
            .padding(.horizontal, 18).padding(.vertical, 12)

            VStack(spacing: 14) {
                dropZone
                if !uploader.log.isEmpty {
                    logView
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        }
    }

    @ViewBuilder var dropZone: some View {
        RoundedRectangle(cornerRadius: 12)
            .strokeBorder(style: StrokeStyle(lineWidth: 2, dash: [7, 5]))
            .foregroundStyle(isTargeted ? t.accent : t.line)
            .background(RoundedRectangle(cornerRadius: 12).fill(isTargeted ? t.accent.opacity(0.08) : t.panel))
            .frame(height: 180)
            .overlay {
                switch uploader.status {
                case .idle:
                    VStack(spacing: 8) {
                        Text("⇪").font(.system(size: 30, weight: .thin)).foregroundStyle(t.faint)
                        Text("Drag a music folder here")
                            .font(.system(size: 13, weight: .semibold)).foregroundStyle(t.ink)
                        Text("the folder's name becomes the station's name")
                            .font(.system(size: 11)).foregroundStyle(t.muted)
                    }
                case .sending(let name):
                    VStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text("Sending \u{201c}\(name)\u{201d}\u{2026}")
                            .font(.system(size: 13, weight: .semibold)).foregroundStyle(t.ink)
                    }
                case .done(let name):
                    VStack(spacing: 8) {
                        Text("\u{2713}").font(.system(size: 26, weight: .bold)).foregroundStyle(t.live)
                        Text("\u{201c}\(name)\u{201d} sent")
                            .font(.system(size: 13, weight: .semibold)).foregroundStyle(t.ink)
                        Text("it'll show up as its own station within a minute")
                            .font(.system(size: 11)).foregroundStyle(t.muted)
                        sendAnotherButton
                    }
                case .failed(let name, let reason):
                    VStack(spacing: 8) {
                        Text("!").font(.system(size: 24, weight: .heavy)).foregroundStyle(t.red)
                        Text("\u{201c}\(name)\u{201d} didn't make it")
                            .font(.system(size: 13, weight: .semibold)).foregroundStyle(t.ink)
                        Text(reason).font(.system(size: 10.5)).foregroundStyle(t.muted)
                            .multilineTextAlignment(.center).lineLimit(3)
                            .padding(.horizontal, 20)
                        sendAnotherButton
                    }
                }
            }
            .onDrop(of: [.fileURL], isTargeted: $isTargeted) { providers in
                guard case .idle = uploader.status, let provider = providers.first else { return false }
                _ = provider.loadObject(ofClass: URL.self) { url, _ in
                    guard let url, url.hasDirectoryPath else { return }
                    DispatchQueue.main.async { uploader.send(folder: url) }
                }
                return true
            }
    }

    var sendAnotherButton: some View {
        Button("Send another folder") { uploader.reset() }
            .buttonStyle(.plain)
            .font(.system(size: 11, weight: .semibold))
            .padding(.horizontal, 10).padding(.vertical, 5)
            .background(t.sunk)
            .foregroundStyle(t.ink)
            .clipShape(RoundedRectangle(cornerRadius: 5))
            .padding(.top, 4)
    }

    var logView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 2) {
                ForEach(Array(uploader.log.enumerated()), id: \.offset) { _, line in
                    Text(line).font(.system(size: 10.5, design: .monospaced))
                        .foregroundStyle(t.muted)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(10)
        }
        .frame(maxHeight: 200)
        .background(t.sunk)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

/// Owns the rsync subprocess. The key ships INSIDE the app bundle
/// (Resources/dad_key, copied in by the Makefile like Session.icns) and gets
/// staged out to a private, correctly-permissioned location on first use —
/// ssh refuses a key file the group/world can read.
@MainActor
final class Uploader: ObservableObject {
    enum Status: Equatable {
        case idle
        case sending(String)
        case done(String)
        case failed(String, String)
    }

    @Published var status: Status = .idle
    @Published var log: [String] = []

    private static let destination = "mark@jasons-mac-mini:jam-inbox/"

    func reset() {
        status = .idle
        log = []
    }

    func send(folder: URL) {
        let name = folder.lastPathComponent
        status = .sending(name)
        log = []

        guard let keyPath = Self.stagedKeyPath() else {
            status = .failed(name, "couldn't prepare the upload key — try relaunching Session")
            return
        }

        // Make sure the files are actually readable by whoever picks them up on
        // the mini — a real contributor's files showed up owner-only-readable
        // (wherever he originally got them), which jam-inbox.sh (a DIFFERENT
        // account) couldn't read at all. openrsync's --chmod/--no-perms don't
        // reliably override this (tested live), so fix it at the source: the
        // contributor always owns their own files, so relaxing permissions
        // here always succeeds regardless of how restrictive they started.
        let fixPerms = Process()
        fixPerms.executableURL = URL(fileURLWithPath: "/bin/chmod")
        fixPerms.arguments = ["-R", "go+rX", folder.path]
        try? fixPerms.run()
        fixPerms.waitUntilExit()

        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/rsync")
        task.arguments = [
            "-av", "-e", "ssh -i \(keyPath) -o StrictHostKeyChecking=accept-new",
            folder.path, Self.destination,
        ]
        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = pipe

        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            let lines = text.split(separator: "\n").map(String.init)
            DispatchQueue.main.async { self?.log.append(contentsOf: lines) }
        }

        task.terminationHandler = { [weak self] proc in
            pipe.fileHandleForReading.readabilityHandler = nil
            DispatchQueue.main.async {
                guard let self else { return }
                if proc.terminationStatus == 0 {
                    self.status = .done(name)
                } else {
                    self.status = .failed(name, "rsync exited with status \(proc.terminationStatus) — check the log above")
                }
            }
        }

        do {
            try task.run()
        } catch {
            status = .failed(name, error.localizedDescription)
        }
    }

    /// Copies the bundled key to a private, SPACE-FREE path once (or refreshes it
    /// if the bundled copy ever changes) and locks it down to 600 — SSH silently
    /// refuses a key with group/world read permission. Deliberately NOT under
    /// ~/Library/Application Support: rsync's -e option does its own naive
    /// whitespace splitting (no shell-style quoting), so a path containing
    /// "Application Support" gets chopped at the space and the second half
    /// gets fed to ssh as a bogus hostname (hit this live — "Could not resolve
    /// hostname support/session/dad_key").
    private static func stagedKeyPath() -> String? {
        guard let bundled = Bundle.main.url(forResource: "dad_key", withExtension: nil) else { return nil }
        let dir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".session-outbox", isDirectory: true)
        let staged = dir.appendingPathComponent("dad_key")
        do {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            if !FileManager.default.fileExists(atPath: staged.path) {
                try FileManager.default.copyItem(at: bundled, to: staged)
            }
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: staged.path)
            return staged.path
        } catch {
            return nil
        }
    }
}
