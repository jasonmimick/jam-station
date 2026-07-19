import SwiftUI
import SessionCore

struct RootView: View {
    @EnvironmentObject var player: Player
    @Environment(\.colorScheme) var scheme
    @AppStorage("accent") var accentHex = "#FFD200"
    @AppStorage("theme") var themePref = "auto"
    @State private var showPlayer = false

    var t: IOSTheme { IOSTheme.current(scheme, accentHex: accentHex) }

    /// The mini pill lives INSIDE each tab, above the tab bar — inserting it at
    /// the screen edge covered the tab buttons and ate scroll gestures.
    @ViewBuilder func withMini<V: View>(_ v: V) -> some View {
        v.safeAreaInset(edge: .bottom) {
            if player.status != .idle {
                MiniPlayer(t: t) { showPlayer = true }
            }
        }
    }

    var body: some View {
        TabView {
            withMini(TunerTab(t: t, openPlayer: { showPlayer = true }))
                .tabItem { Label("Tuner", systemImage: "dial.medium") }
            withMini(ShelfTab(t: t, openPlayer: { showPlayer = true }))
                .tabItem { Label("Shelf", systemImage: "square.stack") }
            withMini(YouTab(t: t))
                .tabItem { Label("You", systemImage: "circle.circle") }
        }
        .tint(t.accent)
        .sheet(isPresented: $showPlayer) {
            PlayerSheet(t: t)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .preferredColorScheme(themePref == "dark" ? .dark : themePref == "light" ? .light : nil)
    }
}

// ── header used by tabs ──────────────────────────────────────────────────

struct SignageHeader: View {
    @EnvironmentObject var player: Player
    let t: IOSTheme

    var body: some View {
        HStack(spacing: 8) {
            ZStack {
                RoundedRectangle(cornerRadius: 2).fill(t.accent).frame(width: 24, height: 20)
                Text("J").font(.system(size: 11, weight: .heavy)).foregroundStyle(t.onAccent)
                Rectangle().fill(t.onAccent.opacity(0.3)).frame(width: 24, height: 1)
            }
            Text(stationName)
                .font(.system(size: 13, weight: .heavy)).tracking(1.5)
                .foregroundStyle(t.ink)
            Spacer()
            if player.member != nil {
                Circle().stroke(t.live, lineWidth: 1.5).frame(width: 10, height: 10)
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 10)
    }

    var stationName: String {
        (player.stationBase.host ?? "JAM-STATION")
            .replacingOccurrences(of: ".runslab.run", with: "").uppercased()
    }
}

// ── Tuner: the station wall ──────────────────────────────────────────────

struct TunerTab: View {
    @EnvironmentObject var player: Player
    let t: IOSTheme
    let openPlayer: () -> Void
    @State private var find = ""

    var channels: [Channel] {
        find.isEmpty ? player.channels
        : player.channels.filter { $0.name.localizedCaseInsensitiveContains(find) }
    }

    var body: some View {
        VStack(spacing: 0) {
            SignageHeader(t: t)
            FindField(text: $find, prompt: "find a channel", t: t)
            ScrollView {
                LazyVGrid(columns: [GridItem(.flexible(), spacing: 12),
                                    GridItem(.flexible(), spacing: 12)], spacing: 16) {
                    ForEach(channels) { ch in
                        ChannelCard(ch: ch, t: t, openPlayer: openPlayer)
                    }
                }
                .padding(.horizontal, 14).padding(.bottom, 20)
            }
        }
        .background(t.board)
        .task { await player.refreshChannels() }
    }
}

/// Image loader that goes through URLSession.shared — AsyncImage does not
/// reliably send the session cookie, and the members-only /music covers 403
/// without it.
struct NetImage: View {
    let url: URL?
    @State private var img: UIImage?

    var body: some View {
        Group {
            if let img {
                Image(uiImage: img).resizable().aspectRatio(contentMode: .fill)
            } else {
                Color.clear
            }
        }
        .task(id: url) {
            guard let url else { return }
            if let (d, r) = try? await URLSession.shared.data(from: url),
               (r as? HTTPURLResponse)?.statusCode == 200,
               let ui = UIImage(data: d) { img = ui }
        }
    }
}

struct FindField: View {
    @Binding var text: String
    let prompt: String
    let t: IOSTheme

    var body: some View {
        TextField(prompt, text: $text)
            .font(.system(size: 14))
            .padding(.horizontal, 13).padding(.vertical, 9)
            .background(t.panel)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(t.line, lineWidth: 1))
            .padding(.horizontal, 14).padding(.bottom, 10)
            .autocorrectionDisabled()
    }
}

struct ChannelCard: View {
    @EnvironmentObject var player: Player
    let ch: Channel
    let t: IOSTheme
    let openPlayer: () -> Void

    var tuned: Bool { player.current?.slug == ch.slug }

    var body: some View {
        Button {
            guard ch.playable else { return }
            player.tune(ch)
            openPlayer()
        } label: {
            VStack(alignment: .leading, spacing: 0) {
                ZStack(alignment: .topTrailing) {
                    ZStack {
                        let hue = Double(abs(ch.name.hashValue % 360)) / 360.0
                        LinearGradient(
                            colors: [Color(hue: hue, saturation: 0.30, brightness: 0.36),
                                     Color(hue: hue, saturation: 0.40, brightness: 0.12)],
                            startPoint: .topLeading, endPoint: .bottomTrailing)
                        Text(String(ch.name.prefix(1)))
                            .font(.system(size: 38, weight: .ultraLight))
                            .foregroundStyle(.white.opacity(0.92))
                        if let url = ch.artURL(base: player.stationBase) {
                            NetImage(url: url)
                        }
                    }
                    .aspectRatio(1, contentMode: .fit)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                    .opacity(ch.playable ? 1 : 0.45)
                    if tuned && player.isPlaying && player.source == .radio {
                        Text("ON AIR")
                            .font(.system(size: 8, weight: .heavy)).tracking(1)
                            .padding(.horizontal, 6).padding(.vertical, 3)
                            .background(t.accent).foregroundStyle(t.onAccent)
                            .clipShape(RoundedRectangle(cornerRadius: 5))
                            .padding(7)
                    }
                }
                .overlay(RoundedRectangle(cornerRadius: 12)
                    .stroke(tuned ? t.accent : .clear, lineWidth: 3))
                Text(ch.name)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(t.ink).lineLimit(1)
                    .padding(.top, 7)
                Text(ch.playable ? (ch.isPrivate ? "PRIVATE" : " ") : "NO MUSIC")
                    .font(.system(size: 10, weight: .bold)).tracking(0.8)
                    .foregroundStyle(ch.playable ? t.accent : t.faint)
            }
        }
        .buttonStyle(.plain)
    }
}

// ── Shelf ────────────────────────────────────────────────────────────────

struct ShelfTab: View {
    @EnvironmentObject var player: Player
    let t: IOSTheme
    let openPlayer: () -> Void
    @State private var find = ""

    var albums: [Album] {
        find.isEmpty ? player.albums
        : player.albums.filter {
            $0.album.localizedCaseInsensitiveContains(find)
            || $0.artist.localizedCaseInsensitiveContains(find)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            SignageHeader(t: t)
            if let rip = player.rip, rip.ripping {
                HStack(spacing: 8) {
                    Circle().fill(t.red).frame(width: 7, height: 7)
                    Text("NOW RIPPING · \(rip.album) · \(rip.track)/\(rip.total)")
                        .font(.system(size: 11, weight: .bold)).lineLimit(1)
                    Spacer()
                }
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(
                    GeometryReader { g in
                        ZStack(alignment: .leading) {
                            t.accent
                            t.onAccent.opacity(0.14)
                                .frame(width: g.size.width *
                                       CGFloat(rip.total > 0 ? Double(rip.track) / Double(rip.total) : 0))
                        }
                    }
                )
                .foregroundStyle(t.onAccent)
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .padding(.horizontal, 14).padding(.bottom, 10)
            }
            if player.member != nil {
                SpotButton(t: t)
                FindField(text: $find, prompt: "search the shelf", t: t)
            }
            if player.member == nil {
                Spacer()
                Text("Your records").font(.system(size: 16, weight: .bold)).foregroundStyle(t.ink)
                Text("Your ripped CDs live here once you sign in — the You tab has the door.")
                    .font(.system(size: 13)).foregroundStyle(t.muted)
                    .multilineTextAlignment(.center).padding(.horizontal, 40).padding(.top, 4)
                Spacer()
            } else {
                ScrollView {
                    LazyVGrid(columns: [GridItem(.flexible(), spacing: 12),
                                        GridItem(.flexible(), spacing: 12)], spacing: 16) {
                        ForEach(albums) { al in
                            Button {
                                player.playAlbum(al)
                                openPlayer()
                            } label: {
                                VStack(alignment: .leading, spacing: 0) {
                                    ZStack {
                                        let hue = Double(abs(al.album.hashValue % 360)) / 360.0
                                        LinearGradient(
                                            colors: [Color(hue: hue, saturation: 0.30, brightness: 0.34),
                                                     Color(hue: hue, saturation: 0.38, brightness: 0.12)],
                                            startPoint: .topLeading, endPoint: .bottomTrailing)
                                        Text(String(al.album.prefix(1)))
                                            .font(.system(size: 36, weight: .ultraLight))
                                            .foregroundStyle(.white.opacity(0.92))
                                        if let url = al.coverURL(base: player.stationBase) {
                                            NetImage(url: url)
                                        }
                                    }
                                    .aspectRatio(1, contentMode: .fit)
                                    .clipShape(RoundedRectangle(cornerRadius: 12))
                                    Text(al.album)
                                        .font(.system(size: 13.5, weight: .semibold))
                                        .foregroundStyle(t.ink).lineLimit(1).padding(.top, 7)
                                    Text(al.artist)
                                        .font(.system(size: 11)).foregroundStyle(t.muted).lineLimit(1)
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.horizontal, 14).padding(.bottom, 20)
                }
            }
        }
        .background(t.board)
    }
}

// ── You ──────────────────────────────────────────────────────────────────

struct YouTab: View {
    @EnvironmentObject var player: Player
    let t: IOSTheme
    @AppStorage("accent") var accentHex = "#FFD200"
    @AppStorage("theme") var themePref = "auto"
    @State private var code = ""
    @State private var authError = false
    @State private var stationText = ""
    @State private var sleepPick = 0

    func isSleep(_ m: Int) -> Bool {
        player.sleepAt == nil ? m == 0 : m == sleepPick
    }

    var body: some View {
        VStack(spacing: 0) {
            SignageHeader(t: t)
            List {
                Section("Member") {
                    if let name = player.member {
                        HStack {
                            Text(name).font(.system(size: 15, weight: .semibold))
                            Spacer()
                            Button("Sign out") { Task { await player.signOut() } }
                                .font(.system(size: 13)).foregroundStyle(t.muted)
                        }
                    } else {
                        SecureField("passcode or passphrase", text: $code)
                            .font(.system(size: 15, design: .monospaced))
                            .onSubmit { submit() }
                        if authError {
                            Text("that code or passphrase isn't valid")
                                .font(.system(size: 12)).foregroundStyle(t.red)
                        }
                        Button("Enter") { submit() }
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(t.accent)
                    }
                }
                if player.member != nil, !player.favs.isEmpty {
                    Section("Favourites") {
                        ForEach(Array(player.favs.enumerated()), id: \.element.url) { i, f in
                            Button {
                                player.playFavourites(at: i)
                            } label: {
                                HStack {
                                    Text("♥").foregroundStyle(t.red)
                                    VStack(alignment: .leading) {
                                        Text(f.title.isEmpty ? f.album : f.title)
                                            .font(.system(size: 14, weight: .medium))
                                            .foregroundStyle(t.ink).lineLimit(1)
                                        Text(f.artist).font(.system(size: 11))
                                            .foregroundStyle(t.muted).lineLimit(1)
                                    }
                                }
                            }
                        }
                    }
                }
                Section("Sleep timer") {
                    HStack(spacing: 8) {
                        ForEach([0, 15, 30, 60], id: \.self) { m in
                            Button {
                                sleepPick = m
                                player.setSleepTimer(minutes: m == 0 ? nil : m)
                            } label: {
                                Text(m == 0 ? "OFF" : "\(m)M")
                                    .font(.system(size: 11, weight: .heavy))
                                    .padding(.horizontal, 12).padding(.vertical, 7)
                                    .background(isSleep(m) ? t.accent : t.sunk)
                                    .foregroundStyle(isSleep(m) ? t.onAccent : t.muted)
                                    .clipShape(Capsule())
                            }
                            .buttonStyle(.plain)
                        }
                        if let at = player.sleepAt {
                            Spacer()
                            Text(at, style: .timer)
                                .font(.system(size: 12, design: .monospaced))
                                .foregroundStyle(t.muted)
                        }
                    }
                }
                Section("Station") {
                    TextField("https://…", text: $stationText)
                        .font(.system(size: 13, design: .monospaced))
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                        .onSubmit {
                            if let url = URL(string: stationText), url.scheme != nil {
                                player.stationBase = url
                            }
                        }
                    Text("the station Session is tuned to — presets come later")
                        .font(.system(size: 11)).foregroundStyle(t.faint)
                }
                Section("Appearance") {
                    Picker("Theme", selection: $themePref) {
                        Text("Auto").tag("auto"); Text("Dark").tag("dark"); Text("Light").tag("light")
                    }
                    HStack(spacing: 10) {
                        ForEach(IOS_ACCENTS, id: \.hex) { a in
                            Button {
                                accentHex = a.hex
                            } label: {
                                ZStack {
                                    Circle().fill(Color(hexStr: a.hex)).frame(width: 26, height: 26)
                                    if accentHex.uppercased() == a.hex.uppercased() {
                                        Text("✓").font(.system(size: 12, weight: .heavy))
                                            .foregroundStyle(IOSTheme.luminance(a.hex) > 0.45
                                                             ? Color(hexStr: "#12120C") : .white)
                                    }
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            .scrollContentBackground(.hidden)
        }
        .background(t.board)
        .onAppear { stationText = player.stationBase.absoluteString }
    }

    func submit() {
        let c = code.trimmingCharacters(in: .whitespaces)
        guard !c.isEmpty else { return }
        Task {
            do { try await player.signIn(code: c); authError = false; code = "" }
            catch { authError = true }
        }
    }
}
