import SwiftUI
import SessionCore

struct RootView: View {
    @EnvironmentObject var player: Player
    @Environment(\.colorScheme) var scheme
    @AppStorage("accent") var accentHex = "#FFD200"
    @AppStorage("theme") var themePref = "auto"
    @AppStorage("dance") var dance = false
    @State private var showPlayer = false

    var t: IOSTheme {
        IOSTheme.current(scheme, accentHex: accentHex,
                         dance: dance && player.status == .playing ? player.dancePhase : nil)
    }

    /// Pre-26 fallback: the pill lives INSIDE each tab, above the tab bar —
    /// a screen-level inset covers the tab buttons.
    @ViewBuilder func withMini<V: View>(_ v: V) -> some View {
        v.safeAreaInset(edge: .bottom) {
            if player.status != .idle {
                MiniPlayer(t: t) { showPlayer = true }
            }
        }
    }

    var body: some View {
        Group {
            if #available(iOS 26.0, *) {
                // the native mini-player slot above the tab bar (what Music uses)
                TabView {
                    TunerTab(t: t, openPlayer: { showPlayer = true })
                        .tabItem { Label("Tuner", systemImage: "dial.medium") }
                    ShelfTab(t: t, openPlayer: { showPlayer = true })
                        .tabItem { Label("Shelf", systemImage: "square.stack") }
                    YouTab(t: t)
                        .tabItem { Label("You", systemImage: "circle.circle") }
                }
                .tabViewBottomAccessory {
                    if player.status != .idle {
                        MiniPlayer(t: t, bare: true) { showPlayer = true }
                    }
                }
            } else {
                TabView {
                    withMini(TunerTab(t: t, openPlayer: { showPlayer = true }))
                        .tabItem { Label("Tuner", systemImage: "dial.medium") }
                    withMini(ShelfTab(t: t, openPlayer: { showPlayer = true }))
                        .tabItem { Label("Shelf", systemImage: "square.stack") }
                    withMini(YouTab(t: t))
                        .tabItem { Label("You", systemImage: "circle.circle") }
                }
            }
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
            DialMark(t: t)
            Text("SESSION")
                .font(.system(size: 13, weight: .heavy)).tracking(2)
                .foregroundStyle(t.ink)
            Text("· \(stationName)")
                .font(.system(size: 10, weight: .bold)).tracking(1)
                .foregroundStyle(t.faint)
            Spacer()
            if player.member != nil {
                Circle().stroke(t.live, lineWidth: 1.5).frame(width: 10, height: 10)
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 10)
    }

    var stationName: String {
        (player.stationBase.host ?? "jam-station")
            .replacingOccurrences(of: ".runslab.run", with: "").uppercased()
    }
}

/// The app's mark — the Dial, matching the home-screen icon.
struct DialMark: View {
    let t: IOSTheme

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 4).fill(Color(hexStr: "#1C1C20"))
            HStack(spacing: 3) {
                ForEach(0..<3, id: \.self) { _ in
                    Capsule().fill(Color(hexStr: "#5A5A62")).frame(width: 1.6, height: 5)
                }
            }
            .offset(x: -3, y: -4)
            Capsule().fill(t.accent).frame(width: 2.6, height: 16).offset(x: 6)
            Circle().fill(Color(hexStr: "#F0402F")).frame(width: 4.5, height: 4.5)
                .offset(x: 6, y: -8)
            Capsule().fill(t.accent.opacity(0.85)).frame(width: 14, height: 2)
                .offset(x: -2, y: 6)
        }
        .frame(width: 26, height: 22)
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
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 108), spacing: 11)], spacing: 14) {
                    ForEach(channels) { ch in
                        ChannelCard(ch: ch, t: t, openPlayer: openPlayer)
                    }
                }
                .padding(.horizontal, 14).padding(.bottom, 20)
            }
            .refreshable {
                await player.refreshChannels()
                await player.refreshMembership()
            }
        }
        .background(t.board)
        .task { await player.refreshChannels() }
    }
}

/// A slider whose track IS the choice — the colour spectrum under your finger.
struct GradientSlider: View {
    @Binding var value: Double     // 0...1
    let gradient: [Color]

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule()
                    .fill(LinearGradient(colors: gradient, startPoint: .leading, endPoint: .trailing))
                    .frame(height: 22)
                Circle()
                    .fill(.white)
                    .frame(width: 24, height: 24)
                    .shadow(color: .black.opacity(0.35), radius: 3, y: 1)
                    .overlay(Circle().stroke(.black.opacity(0.15), lineWidth: 1))
                    .offset(x: CGFloat(value) * (geo.size.width - 24))
            }
            .frame(maxHeight: .infinity)
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0).onChanged { g in
                value = min(1, max(0, Double((g.location.x - 12) / (geo.size.width - 24))))
            })
        }
        .frame(height: 26)
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
    var inline = false      // true: no outer padding (caller composes a row)

    var body: some View {
        TextField(prompt, text: $text)
            .font(.system(size: 14))
            .padding(.horizontal, 13).padding(.vertical, 9)
            .background(t.panel)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(t.line, lineWidth: 1))
            .padding(.horizontal, inline ? 0 : 14)
            .padding(.bottom, inline ? 0 : 10)
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
            tapHaptic()
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
                            .font(.system(size: 28, weight: .ultraLight))
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
                    .font(.system(size: 12.5, weight: .semibold))
                    .foregroundStyle(t.ink).lineLimit(1)
                    .padding(.top, 6)
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
    @AppStorage("shelfView") var shelfView = "grid"

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
                HStack(spacing: 8) {
                    FindField(text: $find, prompt: "search the shelf", t: t, inline: true)
                    HStack(spacing: 0) {
                        ForEach([("grid", "square.grid.2x2"), ("list", "list.bullet")], id: \.0) { mode, icon in
                            Button {
                                shelfView = mode
                            } label: {
                                Image(systemName: icon)
                                    .font(.system(size: 13))
                                    .frame(width: 38, height: 36)
                                    .background(shelfView == mode ? t.accent : t.panel)
                                    .foregroundStyle(shelfView == mode ? t.onAccent : t.muted)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                    .overlay(RoundedRectangle(cornerRadius: 10).stroke(t.line, lineWidth: 1))
                }
                .padding(.horizontal, 14).padding(.bottom, 10)
            }
            if player.member == nil {
                Spacer()
                Text("Your records").font(.system(size: 16, weight: .bold)).foregroundStyle(t.ink)
                Text("Your ripped CDs live here once you sign in — the You tab has the door.")
                    .font(.system(size: 13)).foregroundStyle(t.muted)
                    .multilineTextAlignment(.center).padding(.horizontal, 40).padding(.top, 4)
                Spacer()
            } else {
                if shelfView == "list" {
                    ScrollView {
                        LazyVStack(spacing: 0) {
                            ForEach(albums) { al in
                                Button {
                                    player.playAlbum(al)
                                    openPlayer()
                                } label: {
                                    HStack(spacing: 12) {
                                        ZStack {
                                            let hue = Double(abs(al.album.hashValue % 360)) / 360.0
                                            LinearGradient(
                                                colors: [Color(hue: hue, saturation: 0.30, brightness: 0.34),
                                                         Color(hue: hue, saturation: 0.38, brightness: 0.12)],
                                                startPoint: .topLeading, endPoint: .bottomTrailing)
                                            Text(String(al.album.prefix(1)))
                                                .font(.system(size: 17, weight: .light))
                                                .foregroundStyle(.white.opacity(0.9))
                                            if let url = al.coverURL(base: player.stationBase) {
                                                NetImage(url: url)
                                            }
                                        }
                                        .frame(width: 44, height: 44)
                                        .clipShape(RoundedRectangle(cornerRadius: 6))
                                        VStack(alignment: .leading, spacing: 1) {
                                            Text(al.album)
                                                .font(.system(size: 14, weight: .semibold))
                                                .foregroundStyle(t.ink).lineLimit(1)
                                            Text(al.artist + (al.year.map { " · \($0)" } ?? ""))
                                                .font(.system(size: 11.5))
                                                .foregroundStyle(t.muted).lineLimit(1)
                                        }
                                        Spacer()
                                        Text("\(al.trackCount)")
                                            .font(.system(size: 11, design: .monospaced))
                                            .foregroundStyle(t.faint)
                                    }
                                    .padding(.horizontal, 14).padding(.vertical, 8)
                                    .contentShape(Rectangle())
                                }
                                .buttonStyle(.plain)
                                .overlay(alignment: .bottom) {
                                    Rectangle().fill(t.line).frame(height: 1).padding(.leading, 70)
                                }
                            }
                        }
                        .padding(.bottom, 20)
                    }
                } else {
                ScrollView {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 108), spacing: 11)], spacing: 14) {
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
                                            .font(.system(size: 26, weight: .ultraLight))
                                            .foregroundStyle(.white.opacity(0.92))
                                        if let url = al.coverURL(base: player.stationBase) {
                                            NetImage(url: url)
                                        }
                                    }
                                    .aspectRatio(1, contentMode: .fit)
                                    .clipShape(RoundedRectangle(cornerRadius: 12))
                                    Text(al.album)
                                        .font(.system(size: 12, weight: .semibold))
                                        .foregroundStyle(t.ink).lineLimit(1).padding(.top, 6)
                                    Text(al.artist)
                                        .font(.system(size: 10.5)).foregroundStyle(t.muted).lineLimit(1)
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.horizontal, 14).padding(.bottom, 20)
                }
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
    @AppStorage("dance") var dance = false
    @AppStorage("saver") var saverMode = "rotate"
    @State private var code = ""
    @State private var authError = false
    @State private var stationText = ""
    @State private var sleepPick = 0

    func isSleep(_ m: Int) -> Bool {
        player.sleepAt == nil ? m == 0 : m == sleepPick
    }

    // ── accent spectrum: hue + tint (white → vivid) over the stored hex ──

    var currentHSB: (h: Double, s: Double, b: Double) {
        var h: CGFloat = 0, s: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        let c = IOSTheme.rgb(accentHex)
        UIColor(red: c[0], green: c[1], blue: c[2], alpha: 1)
            .getHue(&h, saturation: &s, brightness: &b, alpha: &a)
        return (Double(h), Double(s), Double(b))
    }

    func setHSB(h: Double, s: Double, b: Double) {
        let out = UIColor(hue: CGFloat(h), saturation: CGFloat(s), brightness: CGFloat(b), alpha: 1)
        var r: CGFloat = 0, g: CGFloat = 0, bl: CGFloat = 0, a: CGFloat = 0
        out.getRed(&r, green: &g, blue: &bl, alpha: &a)
        accentHex = String(format: "#%02X%02X%02X", Int(r * 255), Int(g * 255), Int(bl * 255))
    }

    var hueBinding: Binding<Double> {
        Binding(
            get: { currentHSB.h },
            set: { nh in
                let c = currentHSB
                setHSB(h: nh, s: max(c.s, 0.35), b: max(c.b, 0.7))
            })
    }

    var tintBinding: Binding<Double> {
        Binding(
            get: { currentHSB.s },
            set: { ns in
                let c = currentHSB
                setHSB(h: c.h, s: ns, b: max(c.b, 0.9))
            })
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
                if !player.history.isEmpty {
                    Section("On the station lately") {
                        ForEach(player.history.prefix(15)) { h in
                            HStack(spacing: 9) {
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(h.title.isEmpty ? h.album : h.title)
                                        .font(.system(size: 13, weight: .medium))
                                        .foregroundStyle(t.ink).lineLimit(1)
                                    Text("\(h.channel) · \(h.artist)")
                                        .font(.system(size: 10.5))
                                        .foregroundStyle(t.muted).lineLimit(1)
                                }
                                Spacer()
                                Text(h.when)
                                    .font(.system(size: 10, design: .monospaced))
                                    .foregroundStyle(t.faint)
                            }
                        }
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
                        ColorPicker("", selection: Binding(
                            get: { Color(hexStr: accentHex) },
                            set: { c in
                                let ui = UIColor(c)
                                var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
                                ui.getRed(&r, green: &g, blue: &b, alpha: &a)
                                accentHex = String(format: "#%02X%02X%02X",
                                                   Int(r * 255), Int(g * 255), Int(b * 255))
                            }
                        ), supportsOpacity: false)
                        .labelsHidden()
                        .frame(width: 30)
                    }
                    VStack(spacing: 10) {
                        HStack(spacing: 10) {
                            Text("Hue").font(.system(size: 12)).foregroundStyle(t.muted)
                                .frame(width: 32, alignment: .leading)
                            GradientSlider(value: hueBinding, gradient:
                                (0...12).map { Color(hue: Double($0) / 12, saturation: 0.9, brightness: 1) })
                        }
                        HStack(spacing: 10) {
                            Text("Tint").font(.system(size: 12)).foregroundStyle(t.muted)
                                .frame(width: 32, alignment: .leading)
                            GradientSlider(value: tintBinding, gradient:
                                [.white, Color(hue: currentHSB.h, saturation: 1, brightness: 1)])
                        }
                    }
                    .padding(.vertical, 2)
                    Toggle(isOn: $dance) {
                        Text(dance ? "♪ Dancing — the colour sways with the music"
                                   : "Let it dance")
                            .font(.system(size: 13))
                    }
                    .tint(t.accent)
                    HStack(spacing: 8) {
                        Text("Saver").font(.system(size: 13)).foregroundStyle(t.muted)
                        ForEach(["bars", "ring", "scope", "rotate"], id: \.self) { m in
                            Button {
                                saverMode = m
                            } label: {
                                Text(m.uppercased())
                                    .font(.system(size: 10, weight: .heavy))
                                    .padding(.horizontal, 9).padding(.vertical, 6)
                                    .background(saverMode == m ? t.accent : t.sunk)
                                    .foregroundStyle(saverMode == m ? t.onAccent : t.muted)
                                    .clipShape(Capsule())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .safeAreaInset(edge: .bottom) {
                Text("Session \(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?") · build \(Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "?")")
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(t.faint)
                    .padding(.bottom, 4)
            }
        }
        .background(t.board)
        .onAppear { stationText = player.stationBase.absoluteString }
        .task { await player.refreshHistory() }
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
