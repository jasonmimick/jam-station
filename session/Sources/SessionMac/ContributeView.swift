import SwiftUI
import AppKit
import SessionCore
import UniformTypeIdentifiers

/// Send Music — the native sibling of tools/jam-outbox.command. Drop a folder,
/// it becomes a station. Generation 2 (2026-07-22): a personal API key minted
/// from the member's own signed-in session, NOT a shared secret baked into the
/// app — see AGENTS.md's contributor-path section and
/// docs/DESIGN-contributor-identity.md for the road that got here (an
/// embedded SSH key anyone who downloaded Session could use, then an
/// abandoned Tailscale-daemon idea, then this). POST straight to
/// /api/contribute; jam-inbox.sh isn't involved for this path at all.
struct ContributeView: View {
    @EnvironmentObject var player: Player
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

            if player.memberEmail == nil {
                EmptyNote(t: t, title: "Sign in to send music",
                          sub: "Your upload is tied to your own account — sign in (You, in the sidebar) first.")
            } else {
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
        .onAppear { uploader.stationBase = player.stationBase }
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

/// Zips the dropped folder and POSTs it to /api/contribute with a personal
/// upload token — minted lazily from the member's own signed-in session
/// (the cookie already lives in HTTPCookieStorage; no separate login here)
/// and cached in UserDefaults so it's only minted once. A 403 means the
/// stored token got revoked (e.g. a fresh one was minted elsewhere) — mint
/// a new one and retry exactly once rather than fail confusingly.
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
    var stationBase = StationAPI.defaultBase

    private static let tokenDefaultsKey = "contributionToken"

    func reset() {
        status = .idle
        log = []
    }

    func send(folder: URL) {
        let name = folder.lastPathComponent
        status = .sending(name)
        log = ["zipping \"\(name)\"\u{2026}"]

        Task {
            do {
                let zipData = try zip(folder: folder)
                try await upload(name: name, zipData: zipData, retrying: false)
            } catch {
                status = .failed(name, error.localizedDescription)
            }
        }
    }

    private func zip(folder: URL) throws -> Data {
        let out = FileManager.default.temporaryDirectory
            .appendingPathComponent("contribute-\(UUID().uuidString).zip")
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/zip")
        task.currentDirectoryURL = folder      // zip the CONTENTS, not the folder itself —
        task.arguments = ["-r", "-q", out.path, "."]   // the server extracts straight into
        try task.run()                                 // /music/inbox/<folder-name>/
        task.waitUntilExit()
        guard task.terminationStatus == 0 else {
            throw NSError(domain: "Uploader", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "couldn't zip the folder"])
        }
        defer { try? FileManager.default.removeItem(at: out) }
        return try Data(contentsOf: out)
    }

    private func tokenFromDefaults() -> String? {
        UserDefaults.standard.string(forKey: Self.tokenDefaultsKey)
    }

    /// Mints a fresh token from the member's OWN signed-in session (the cookie
    /// is already in HTTPCookieStorage — Session's existing sign-in, nothing
    /// new). A 403 here means genuinely not signed in.
    private func mintToken() async throws -> String {
        var req = URLRequest(url: stationBase.appendingPathComponent("api/contribute/token"))
        req.httpMethod = "POST"
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard (resp as? HTTPURLResponse)?.statusCode == 200 else {
            throw NSError(domain: "Uploader", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "sign in first"])
        }
        struct TokenResp: Decodable { let token: String }
        let token = try JSONDecoder().decode(TokenResp.self, from: data).token
        UserDefaults.standard.set(token, forKey: Self.tokenDefaultsKey)
        return token
    }

    private func upload(name: String, zipData: Data, retrying: Bool) async throws {
        log.append("sending\u{2026}")
        let token: String
        if let stored = tokenFromDefaults() {
            token = stored
        } else {
            token = try await mintToken()
        }

        let boundary = "session-contribute-\(UUID().uuidString)"
        var req = URLRequest(url: stationBase.appendingPathComponent("api/contribute"))
        req.httpMethod = "POST"
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data()
        func field(_ fieldName: String, _ value: String) {
            body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(fieldName)\"\r\n\r\n\(value)\r\n".utf8))
        }
        field("folder", name)
        body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"upload.zip\"\r\nContent-Type: application/zip\r\n\r\n".utf8))
        body.append(zipData)
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        req.httpBody = body
        req.timeoutInterval = 300   // a big folder over a slow connection is fine, just not infinite

        let (data, resp) = try await URLSession.shared.data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if code == 403 && !retrying {
            // stored token got revoked (a fresh one minted elsewhere) — mint once
            // more and retry, rather than fail with a confusing "invalid key."
            UserDefaults.standard.removeObject(forKey: Self.tokenDefaultsKey)
            log.append("upload key needed refreshing, retrying\u{2026}")
            try await upload(name: name, zipData: zipData, retrying: true)
            return
        }
        guard code == 200 else {
            let text = String(data: data, encoding: .utf8) ?? "server said \(code)"
            throw NSError(domain: "Uploader", code: 3, userInfo: [NSLocalizedDescriptionKey: text])
        }
        log.append("done.")
        status = .done(name)
    }
}
