import SwiftUI
import SessionCore

/// Tab routing + player-panel state. Lives in an observable so views in
/// separate hosting contexts (the tab-bar accessory) reliably drive it.
final class Nav: ObservableObject {
    @Published var tab = "home"
    @Published var playerOpen = false
    @Published var shelfSection: String?   // a genre handoff to the Shelf view
    @Published var shelfCrate: String?     // cds | vinyl handoff (iPad sidebar)
}

struct RootView: View {
    @EnvironmentObject var player: Player
    @StateObject private var nav = Nav()
    @Environment(\.colorScheme) var scheme
    @AppStorage("accent") var accentHex = "#FFD200"
    @AppStorage("theme") var themePref = "auto"
    @AppStorage("dance") var dance = false

    var t: IOSTheme {
        IOSTheme.current(scheme, accentHex: accentHex,
                         dance: dance && player.status == .playing ? player.dancePhase : nil)
    }

    /// The player is a plain SwiftUI overlay (state → transform), NOT a UIKit
    /// sheet. Presenting sheets from context menus / mid-dismissal is broken at
    /// the UIKit layer (Apple forums 709354, 692338); an overlay has no
    /// presentation machinery to desync — open/close is just state.
    func openPlayer() {
        withAnimation(.spring(response: 0.35, dampingFraction: 0.86)) { nav.playerOpen = true }
    }

    func closePlayer() {
        withAnimation(.spring(response: 0.35, dampingFraction: 0.86)) { nav.playerOpen = false }
    }

    /// Pre-26 fallback: the pill lives INSIDE each tab, above the tab bar —
    /// a screen-level inset covers the tab buttons.
    @ViewBuilder func withMini<V: View>(_ v: V) -> some View {
        v.safeAreaInset(edge: .bottom) {
            if player.status != .idle {
                MiniPlayer { openPlayer() }
            }
        }
    }

    var body: some View {
        Group {
            if UIDevice.current.userInterfaceIdiom == .pad {
                // iPad: the Mac shape — sidebar + content, no tab bar
                PadRoot(t: t, openPlayer: openPlayer)
            } else if #available(iOS 26.0, *) {
                // the native mini-player slot above the tab bar (what Music uses)
                TabView(selection: $nav.tab) {
                    HomeTab(t: t, openPlayer: openPlayer, goTuner: { nav.tab = "tuner" })
                        .tabItem { Label("Home", systemImage: "house") }.tag("home")
                    TunerTab(t: t, openPlayer: openPlayer)
                        .tabItem { Label("Tuner", systemImage: "dial.medium") }.tag("tuner")
                    ShelfTab(t: t, openPlayer: openPlayer)
                        .tabItem { Label("Shelf", systemImage: "square.stack") }.tag("shelf")
                    YouTab(t: t)
                        .tabItem { Label("You", systemImage: "circle.circle") }.tag("you")
                }
                .tabViewBottomAccessory {
                    if player.status != .idle {
                        MiniPlayer(bare: true) { openPlayer() }
                            // the accessory hosts its own environment — repeat the
                            // app's theme override so its chrome matches the UX
                            .preferredColorScheme(themePref == "dark" ? .dark
                                                  : themePref == "light" ? .light : nil)
                    }
                }
            } else {
                TabView(selection: $nav.tab) {
                    withMini(HomeTab(t: t, openPlayer: openPlayer, goTuner: { nav.tab = "tuner" }))
                        .tabItem { Label("Home", systemImage: "house") }.tag("home")
                    withMini(TunerTab(t: t, openPlayer: openPlayer))
                        .tabItem { Label("Tuner", systemImage: "dial.medium") }.tag("tuner")
                    withMini(ShelfTab(t: t, openPlayer: openPlayer))
                        .tabItem { Label("Shelf", systemImage: "square.stack") }.tag("shelf")
                    withMini(YouTab(t: t))
                        .tabItem { Label("You", systemImage: "circle.circle") }.tag("you")
                }
            }
        }
        .environmentObject(nav)
        .tint(t.accent)
        .overlay {
            if nav.playerOpen {
                PlayerSheet(t: t, close: closePlayer)
                    .transition(.move(edge: .bottom))
                    .zIndex(10)
            }
        }
        .preferredColorScheme(themePref == "dark" ? .dark : themePref == "light" ? .light : nil)
    }
}

// ── iPad: sidebar + content (the Mac shape) ──────────────────────────────

struct PadRoot: View {
    @EnvironmentObject var player: Player
    @EnvironmentObject var nav: Nav
    let t: IOSTheme
    let openPlayer: () -> Void

    var body: some View {
        HStack(spacing: 0) {
            PadSidebar(t: t)
                .frame(width: 250)
                .background(t.panel)
            Rectangle().fill(t.line).frame(width: 1)
            Group {
                switch nav.tab {
                case "tuner": TunerTab(t: t, openPlayer: openPlayer)
                case "shelf": ShelfTab(t: t, openPlayer: openPlayer)
                case "you": YouTab(t: t)
                default: HomeTab(t: t, openPlayer: openPlayer, goTuner: { nav.tab = "tuner" })
                }
            }
            .frame(maxWidth: .infinity)
            .safeAreaInset(edge: .bottom) {
                if player.status != .idle {
                    MiniPlayer { openPlayer() }
                }
            }
        }
        .background(t.board)
    }
}

struct PadSidebar: View {
    @EnvironmentObject var player: Player
    @EnvironmentObject var nav: Nav
    let t: IOSTheme

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 8) {
                    DialMark(t: t)
                    Text("SESSION")
                        .font(.system(size: 13, weight: .heavy)).tracking(2)
                        .foregroundStyle(t.ink)
                }
                .padding(.horizontal, 16).padding(.top, 14).padding(.bottom, 12)
                PadSideItem(label: "Home", glyph: "house", sel: nav.tab == "home", t: t) {
                    nav.tab = "home"
                }
                PadSideItem(label: "The Dial", glyph: "dial.medium", sel: nav.tab == "tuner", t: t) {
                    nav.tab = "tuner"
                }
                PadSideItem(label: "The Shelf", glyph: "square.stack", sel: nav.tab == "shelf", t: t) {
                    nav.shelfSection = ""
                    nav.shelfCrate = "cds"
                    nav.tab = "shelf"
                }
                if !player.vinyl.isEmpty {
                    PadSideItem(label: "The Records", glyph: "opticaldisc", sel: false, t: t,
                                badge: "\(player.vinyl.count)") {
                        nav.shelfCrate = "vinyl"
                        nav.tab = "shelf"
                    }
                }
                if !player.attic.isEmpty {
                    PadSideItem(label: "The Attic", glyph: "house.lodge", sel: false, t: t,
                                badge: "\(player.attic.count)") {
                        nav.shelfCrate = "attic"
                        nav.tab = "shelf"
                    }
                }
                PadSideItem(label: "You", glyph: "circle.circle", sel: nav.tab == "you", t: t) {
                    nav.tab = "you"
                }
                if !player.genres.isEmpty {
                    Text("FROM THE SHELF")
                        .font(.system(size: 10, weight: .heavy)).tracking(1.8)
                        .foregroundStyle(t.accent)
                        .padding(.horizontal, 16).padding(.top, 18).padding(.bottom, 4)
                    ForEach(player.genres) { g in
                        PadSideItem(label: g.name, glyph: "music.note", sel: false, t: t,
                                    badge: "\(g.count)") {
                            nav.shelfSection = g.name
                            nav.tab = "shelf"
                        }
                    }
                }
            }
            .padding(.bottom, 20)
        }
    }
}

struct PadSideItem: View {
    let label: String
    let glyph: String
    let sel: Bool
    let t: IOSTheme
    var badge: String? = nil
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: glyph)
                    .font(.system(size: 14))
                    .foregroundStyle(sel ? t.accent : t.faint)
                    .frame(width: 22)
                Text(label)
                    .font(.system(size: 15, weight: sel ? .heavy : .semibold))
                    .foregroundStyle(t.ink)
                    .lineLimit(1)
                Spacer()
                if let badge {
                    Text(badge).font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(t.faint)
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 10)
            .background(sel ? t.sunk : .clear)
            .overlay(alignment: .leading) {
                if sel { Rectangle().fill(t.accent).frame(width: 3) }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 6)
    }
}

// ── header used by tabs ──────────────────────────────────────────────────

struct SignageHeader: View {
    @EnvironmentObject var player: Player
    @EnvironmentObject var nav: Nav
    let t: IOSTheme

    var body: some View {
        HStack(spacing: 8) {
            Button {
                nav.tab = "home"        // the mark is the way home
            } label: {
                HStack(spacing: 8) {
                    DialMark(t: t)
                    Text("SESSION")
                        .font(.system(size: 13, weight: .heavy)).tracking(2)
                        .foregroundStyle(t.ink)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
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
    @AppStorage("tunerView") var tunerView = "grid"

    var channels: [Channel] {
        find.isEmpty ? player.channels
        : player.channels.filter { $0.name.localizedCaseInsensitiveContains(find) }
    }

    var body: some View {
        VStack(spacing: 0) {
            SignageHeader(t: t)
            HStack(spacing: 8) {
                FindField(text: $find, prompt: "find a channel", t: t, inline: true)
                ViewToggle(selection: $tunerView, t: t)
            }
            .padding(.horizontal, 14).padding(.bottom, 10)
            ScrollView {
                if tunerView == "list" {
                    LazyVStack(spacing: 0) {
                        ForEach(channels) { ch in
                            ChannelRowIOS(ch: ch, t: t, openPlayer: openPlayer)
                        }
                    }
                    .padding(.bottom, 20)
                } else {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 108), spacing: 11)], spacing: 14) {
                        ForEach(channels) { ch in
                            ChannelCard(ch: ch, t: t, openPlayer: openPlayer)
                        }
                    }
                    .padding(.horizontal, 14).padding(.bottom, 20)
                }
            }
            .refreshable {
                await player.refreshChannels()
                await player.refreshMembership()
            }
        }
        .background(t.board)
        .task {
            await player.refreshChannels()
            while !Task.isCancelled {           // the dial stays current while you look at it
                await player.refreshDial()
                try? await Task.sleep(for: .seconds(20))
            }
        }
    }
}

struct SectionChip: View {
    let label: String
    let on: Bool
    let t: IOSTheme
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(label)
                .font(.system(size: 11, weight: .heavy)).tracking(0.5)
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(on ? t.accent : t.panel)
                .foregroundStyle(on ? t.onAccent : t.muted)
                .clipShape(Capsule())
                .overlay(Capsule().stroke(on ? t.accent : t.line, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

/// The record-store sections the owner can pin an album into (long-press a
/// record). Any custom label works via the API; these are the house buckets.
let SHELF_SECTIONS = ["Jazz", "Blues", "Classical", "Rock", "Folk", "Country",
                      "Soul/Funk", "Hip-Hop", "Electronic", "Reggae", "World", "Pop"]

struct AlbumSectionsModifier: ViewModifier {
    @EnvironmentObject var player: Player
    @Environment(\.colorScheme) var scheme
    @AppStorage("accent") var accentHex = "#FFD200"
    let al: Album
    @State private var showPhotos = false

    func body(content: Content) -> some View {
        content.contextMenu {
            Button {
                player.toggleAlbumLike(al.dir)
            } label: {
                Label(player.isAlbumLiked(al.dir) ? "Unlike record" : "Like record",
                      systemImage: player.isAlbumLiked(al.dir) ? "heart.fill" : "heart")
            }
            Button {
                showPhotos = true
            } label: { Label("Photos…", systemImage: "photo.on.rectangle") }
            Menu("Set section" + (al.genres.isEmpty ? "" : " (\(al.genres.joined(separator: ", ")))")) {
                ForEach(SHELF_SECTIONS, id: \.self) { s in
                    Button {
                        player.setAlbumGenres(al, genres: [s])
                    } label: {
                        if al.genres.contains(s) {
                            Label(s, systemImage: "checkmark")
                        } else {
                            Text(s)
                        }
                    }
                }
                Button("No section", role: .destructive) {
                    player.setAlbumGenres(al, genres: [])
                }
            }
        }
        .sheet(isPresented: $showPhotos) {
            AlbumPhotosView(album: al, t: IOSTheme.current(scheme, accentHex: accentHex))
        }
    }
}

/// The shared ▦/☰ pair, styled like the web's vtog.
struct ViewToggle: View {
    @Binding var selection: String
    let t: IOSTheme

    var body: some View {
        HStack(spacing: 0) {
            ForEach([("grid", "square.grid.2x2"), ("list", "list.bullet")], id: \.0) { mode, icon in
                Button {
                    selection = mode
                } label: {
                    Image(systemName: icon)
                        .font(.system(size: 13))
                        .frame(width: 38, height: 36)
                        .background(selection == mode ? t.accent : t.panel)
                        .foregroundStyle(selection == mode ? t.onAccent : t.muted)
                }
                .buttonStyle(.plain)
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(t.line, lineWidth: 1))
    }
}

/// A station as a departure row — thumb, name, state; ▸ marks the tuned one.
struct ChannelRowIOS: View {
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
            HStack(spacing: 12) {
                ZStack {
                    let hue = Double(abs(ch.name.hashValue % 360)) / 360.0
                    LinearGradient(
                        colors: [Color(hue: hue, saturation: 0.30, brightness: 0.36),
                                 Color(hue: hue, saturation: 0.40, brightness: 0.12)],
                        startPoint: .topLeading, endPoint: .bottomTrailing)
                    Text(String(ch.name.prefix(1)))
                        .font(.system(size: 17, weight: .light))
                        .foregroundStyle(.white.opacity(0.9))
                    if let url = ch.artURL(base: player.stationBase) {
                        NetImage(url: url)
                    }
                }
                .frame(width: 44, height: 44)
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .opacity(ch.playable ? 1 : 0.45)
                VStack(alignment: .leading, spacing: 1) {
                    Text(ch.name)
                        .font(.system(size: 14, weight: tuned ? .heavy : .semibold))
                        .foregroundStyle(ch.playable ? t.ink : t.faint).lineLimit(1)
                    if let np = player.dialNow[ch.slug], !np.isEmpty {
                        Text(np.title + (np.artist.isEmpty ? "" : " — \(np.artist)"))
                            .font(.system(size: 10.5)).foregroundStyle(t.muted).lineLimit(1)
                    } else if !ch.playable {
                        Text("NO MUSIC").font(.system(size: 9, weight: .heavy)).tracking(1)
                            .foregroundStyle(t.faint)
                    } else if ch.isPrivate {
                        Text("PRIVATE").font(.system(size: 9, weight: .heavy)).tracking(1)
                            .foregroundStyle(t.accent)
                    }
                }
                Spacer()
                if tuned && player.isPlaying && player.source == .radio {
                    Text("ON AIR").font(.system(size: 8, weight: .heavy)).tracking(1)
                        .padding(.horizontal, 6).padding(.vertical, 3)
                        .background(t.accent).foregroundStyle(t.onAccent)
                        .clipShape(RoundedRectangle(cornerRadius: 5))
                } else if tuned {
                    Text("▸").font(.system(size: 13, weight: .bold)).foregroundStyle(t.accent)
                }
            }
            .padding(.horizontal, 14).padding(.vertical, 7)
            .background(tuned ? t.sunk : .clear)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!ch.playable)
        .channelPeek(ch: ch, t: t, openPlayer: openPlayer)
        .overlay(alignment: .bottom) {
            Rectangle().fill(t.line).frame(height: 1).padding(.leading, 70)
        }
        .overlay(alignment: .leading) {
            if tuned { Rectangle().fill(t.accent).frame(width: 3) }
        }
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

    var onNow: Bool { !(player.dialNow[ch.slug]?.isEmpty ?? true) }

    /// The card's one line: what's PLAYING on the channel beats a status word.
    var cardSub: String {
        if let np = player.dialNow[ch.slug], !np.isEmpty { return np.title }
        if !ch.playable { return "NO MUSIC" }
        if ch.isPrivate { return "PRIVATE" }
        return " "
    }

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
                Text(cardSub)
                    .font(.system(size: 10, weight: onNow ? .medium : .bold))
                    .tracking(onNow ? 0 : 0.8)
                    .foregroundStyle(onNow ? t.muted : (ch.playable ? t.accent : t.faint))
                    .lineLimit(1)
            }
        }
        .buttonStyle(.plain)
        .channelPeek(ch: ch, t: t, openPlayer: openPlayer)
    }
}

/// Long-press a channel: peek what's on without tuning, then choose your door.
extension View {
    func channelPeek(ch: Channel, t: IOSTheme, openPlayer: @escaping () -> Void) -> some View {
        modifier(ChannelPeekModifier(ch: ch, t: t, openPlayer: openPlayer))
    }
}

struct ChannelPeekModifier: ViewModifier {
    @EnvironmentObject var player: Player
    let ch: Channel
    let t: IOSTheme
    let openPlayer: () -> Void

    func body(content: Content) -> some View {
        content.contextMenu {
            Button {
                tapHaptic()
                player.tune(ch)
                openPlayer()
            } label: { Label("Tune in — Radio", systemImage: "dot.radiowaves.left.and.right") }
            Button {
                tapHaptic()
                player.playTape(ch)
                openPlayer()
            } label: { Label("Play this tape", systemImage: "recordingtape") }
        } preview: {
            ChannelPeek(ch: ch, t: t)
        }
    }
}

struct ChannelPeek: View {
    @EnvironmentObject var player: Player
    let ch: Channel
    let t: IOSTheme
    @State private var np = NowPlaying.empty

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                ZStack {
                    let hue = Double(abs(ch.name.hashValue % 360)) / 360.0
                    LinearGradient(
                        colors: [Color(hue: hue, saturation: 0.30, brightness: 0.36),
                                 Color(hue: hue, saturation: 0.40, brightness: 0.12)],
                        startPoint: .topLeading, endPoint: .bottomTrailing)
                    if let url = ch.artURL(base: player.stationBase) {
                        NetImage(url: url)
                    }
                }
                .frame(width: 52, height: 52)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                VStack(alignment: .leading, spacing: 2) {
                    Text(ch.name).font(.system(size: 15, weight: .bold)).foregroundStyle(t.ink)
                    Text("NOW PLAYING").font(.system(size: 8, weight: .heavy)).tracking(1.6)
                        .foregroundStyle(t.faint)
                }
            }
            if np.isEmpty {
                Text("…").font(.system(size: 13)).foregroundStyle(t.muted)
            } else {
                Text(np.title).font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(t.ink).lineLimit(2)
                Text(np.artist + (np.album.isEmpty ? "" : " · \(np.album)"))
                    .font(.system(size: 11.5)).foregroundStyle(t.muted).lineLimit(2)
            }
        }
        .padding(16)
        .frame(width: 280, alignment: .leading)
        .background(t.board)
        .task {
            np = (try? await player.api.nowPlaying(channel: ch.slug)) ?? .empty
        }
    }
}

// ── Shelf ────────────────────────────────────────────────────────────────

struct ShelfTab: View {
    @EnvironmentObject var player: Player
    let t: IOSTheme
    @EnvironmentObject var nav: Nav
    let openPlayer: () -> Void
    @State private var find = ""
    @State private var section = ""          // "" = the whole shelf
    @State private var crate = "cds"         // cds | vinyl — which wall you're facing
    @AppStorage("shelfView") var shelfView = "grid"

    @State private var likedOnly = false

    var albums: [Album] {
        player.albums.filter { al in
            (!likedOnly || player.isAlbumLiked(al.dir))
            && (section.isEmpty || al.genres.contains(section))
            && (find.isEmpty
                || al.album.localizedCaseInsensitiveContains(find)
                || al.artist.localizedCaseInsensitiveContains(find))
        }
    }

    /// The broadcast twin of a section — 'From the Shelf — Jazz' on the dial.
    func shelfChannel(for s: String) -> Channel? {
        let slug = "shelf-" + s.lowercased()
            .replacingOccurrences(of: "[^a-z0-9]+", with: "-", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        return player.channels.first { $0.slug == slug && $0.playable }
    }

    var body: some View {
        VStack(spacing: 0) {
            SignageHeader(t: t)
            if !player.vinyl.isEmpty || !player.attic.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 7) {
                        SectionChip(label: "SHELF · \(player.albums.count)",
                                    on: crate == "cds", t: t) { crate = "cds" }
                        if !player.vinyl.isEmpty {
                            SectionChip(label: "RECORDS · \(player.vinyl.count)",
                                        on: crate == "vinyl", t: t) { crate = "vinyl" }
                        }
                        if !player.attic.isEmpty {
                            SectionChip(label: "ATTIC · \(player.attic.count)",
                                        on: crate == "attic", t: t) { crate = "attic" }
                        }
                    }
                    .padding(.horizontal, 14)
                }
                .padding(.bottom, 8)
            }
            if crate == "vinyl" {
                VinylWalliOS(t: t)
            } else if crate == "attic" {
                AtticWalliOS(t: t, openPlayer: openPlayer)
            } else {
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
                    ViewToggle(selection: $shelfView, t: t)
                }
                .padding(.horizontal, 14).padding(.bottom, 8)
                if !player.genres.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 7) {
                            SectionChip(label: "ALL", on: section.isEmpty, t: t) { section = "" }
                            SectionChip(label: "♥", on: likedOnly, t: t) { likedOnly.toggle() }
                            ForEach(player.genres) { g in
                                SectionChip(label: "\(g.name.uppercased()) · \(g.count)",
                                            on: section == g.name, t: t) {
                                    section = section == g.name ? "" : g.name
                                }
                            }
                            if !section.isEmpty {
                                Button {
                                    tapHaptic()
                                    player.playMix(section)
                                    openPlayer()
                                } label: {
                                    Text("▶ \(section.uppercased()) MIX")
                                        .font(.system(size: 11, weight: .heavy)).tracking(0.8)
                                        .padding(.horizontal, 12).padding(.vertical, 8)
                                        .background(t.accent).foregroundStyle(t.onAccent)
                                        .clipShape(Capsule())
                                }
                                .buttonStyle(.plain)
                                if let ch = shelfChannel(for: section) {
                                    Button {
                                        tapHaptic()
                                        player.tune(ch)
                                        openPlayer()
                                    } label: {
                                        HStack(spacing: 5) {
                                            Image(systemName: "dot.radiowaves.left.and.right")
                                                .font(.system(size: 10, weight: .bold))
                                            Text("TUNE IN")
                                                .font(.system(size: 11, weight: .heavy)).tracking(0.8)
                                        }
                                        .padding(.horizontal, 12).padding(.vertical, 8)
                                        .foregroundStyle(t.red)
                                        .overlay(Capsule().stroke(t.red, lineWidth: 1.5))
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                        }
                        .padding(.horizontal, 14)
                    }
                    .padding(.bottom, 10)
                }
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
                                .modifier(AlbumSectionsModifier(al: al))
                                .overlay(alignment: .bottom) {
                                    Rectangle().fill(t.line).frame(height: 1).padding(.leading, 70)
                                }
                            }
                        }
                        if section.isEmpty && find.isEmpty {   // Spotted belongs to the whole shelf,
                            SpottedSection(t: t)               // not to every section view
                        }
                        Color.clear.frame(height: 20)
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
                                    .overlay(alignment: .topLeading) {
                                        if player.isAlbumLiked(al.dir) {
                                            Image(systemName: "heart.fill")
                                                .font(.system(size: 11))
                                                .foregroundStyle(t.accent)
                                                .padding(5)
                                                .background(Circle().fill(.black.opacity(0.5)))
                                                .padding(6)
                                        }
                                    }
                                    Text(al.album)
                                        .font(.system(size: 12, weight: .semibold))
                                        .foregroundStyle(t.ink).lineLimit(1).padding(.top, 6)
                                    Text(al.artist)
                                        .font(.system(size: 10.5)).foregroundStyle(t.muted).lineLimit(1)
                                }
                            }
                            .buttonStyle(.plain)
                            .modifier(AlbumSectionsModifier(al: al))
                        }
                    }
                    .padding(.horizontal, 14)
                    if section.isEmpty && find.isEmpty {
                        SpottedSection(t: t)
                    }
                    Color.clear.frame(height: 20)
                }
                }
            }
            }
        }
        .background(t.board)
        .onChange(of: nav.shelfSection) { _, s in
            if let s { section = s; crate = "cds"; nav.shelfSection = nil }
        }
        .onChange(of: nav.shelfCrate) { _, c in
            if let c { crate = c; nav.shelfCrate = nil }
        }
        .onAppear {
            if let s = nav.shelfSection { section = s; nav.shelfSection = nil }
            if let c = nav.shelfCrate { crate = c; nav.shelfCrate = nil }
        }
    }
}

/// The attic on iOS — the rescued crate off the vault. Placard tiles only
/// (art loads lazily when a record plays; no bulk prefetch). Tap = play.
struct AtticWalliOS: View {
    @EnvironmentObject var player: Player
    let t: IOSTheme
    let openPlayer: () -> Void
    @State private var find = ""

    var albums: [Album] {
        find.isEmpty ? player.attic
        : player.attic.filter {
            $0.album.localizedCaseInsensitiveContains(find)
            || $0.artist.localizedCaseInsensitiveContains(find)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            FindField(text: $find, prompt: "search the attic", t: t)
            ScrollView {
                LazyVStack(spacing: 0) {
                    ForEach(albums) { al in
                        Button {
                            tapHaptic()
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
                                        .font(.system(size: 16, weight: .light))
                                        .foregroundStyle(.white.opacity(0.9))
                                    if al.coverPath != nil {       // cached sleeves only — the
                                        NetImage(url: al.coverURL(base: player.stationBase))
                                    }                              // warmer fills the rest
                                }
                                .frame(width: 40, height: 40)
                                .clipShape(RoundedRectangle(cornerRadius: 6))
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(al.album)
                                        .font(.system(size: 14, weight: .semibold))
                                        .foregroundStyle(t.ink).lineLimit(1)
                                    Text(al.artist)
                                        .font(.system(size: 11.5))
                                        .foregroundStyle(t.muted).lineLimit(1)
                                }
                                Spacer()
                                Text("\(al.trackCount)")
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundStyle(t.faint)
                            }
                            .padding(.horizontal, 14).padding(.vertical, 7)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .overlay(alignment: .bottom) {
                            Rectangle().fill(t.line).frame(height: 1).padding(.leading, 66)
                        }
                    }
                }
                .padding(.bottom, 20)
            }
        }
    }
}

/// The vinyl wall on iOS — browse the LP collection; a tap opens the Discogs
/// release. Catalog, not playback (playable twins are phase 2).
struct VinylWalliOS: View {
    @EnvironmentObject var player: Player
    let t: IOSTheme
    @State private var find = ""
    @State private var section = ""

    var records: [VinylRecord] {
        player.vinyl.filter { r in
            (section.isEmpty || r.sections.contains(section))
            && (find.isEmpty
                || r.title.localizedCaseInsensitiveContains(find)
                || r.artist.localizedCaseInsensitiveContains(find))
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            FindField(text: $find, prompt: "search the records", t: t)
            if !player.vinylSections.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 7) {
                        SectionChip(label: "ALL", on: section.isEmpty, t: t) { section = "" }
                        ForEach(player.vinylSections) { s in
                            SectionChip(label: "\(s.name.uppercased()) · \(s.count)",
                                        on: section == s.name, t: t) {
                                section = section == s.name ? "" : s.name
                            }
                        }
                    }
                    .padding(.horizontal, 14)
                }
                .padding(.bottom, 10)
            }
            ScrollView {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 108), spacing: 11)], spacing: 14) {
                    ForEach(records) { r in
                        Link(destination: r.discogsURL ?? player.stationBase) {
                            VStack(alignment: .leading, spacing: 0) {
                                ZStack {
                                    let hue = Double(abs(r.title.hashValue % 360)) / 360.0
                                    LinearGradient(
                                        colors: [Color(hue: hue, saturation: 0.28, brightness: 0.32),
                                                 Color(hue: hue, saturation: 0.36, brightness: 0.11)],
                                        startPoint: .topLeading, endPoint: .bottomTrailing)
                                    Circle().stroke(.white.opacity(0.25), lineWidth: 2).padding(10)
                                    Circle().fill(.white.opacity(0.25)).frame(width: 7, height: 7)
                                    NetImage(url: r.coverURL(base: player.stationBase))
                                }
                                .aspectRatio(1, contentMode: .fit)
                                .clipShape(RoundedRectangle(cornerRadius: 12))
                                Text(r.title)
                                    .font(.system(size: 12, weight: .semibold))
                                    .foregroundStyle(t.ink).lineLimit(1).padding(.top, 6)
                                Text(r.artist + (r.year.map { " · \($0)" } ?? ""))
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
                if player.member != nil, let handle = player.memberHandle {
                    Section("Your radio") {
                        let url = player.stationBase.appendingPathComponent(handle)
                        HStack {
                            VStack(alignment: .leading, spacing: 1) {
                                Text("Your personal dial")
                                    .font(.system(size: 13, weight: .semibold))
                                    .foregroundStyle(t.ink)
                                Text(url.absoluteString.replacingOccurrences(of: "https://", with: ""))
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundStyle(t.muted)
                            }
                            Spacer()
                            ShareLink(item: url) {
                                Image(systemName: "square.and.arrow.up")
                                    .font(.system(size: 14))
                                    .foregroundStyle(t.accent)
                            }
                        }
                        Link(destination: player.stationBase.appendingPathComponent("guide")) {
                            HStack {
                                Text("Contributor guide")
                                    .font(.system(size: 13)).foregroundStyle(t.ink)
                                Spacer()
                                Image(systemName: "arrow.up.right")
                                    .font(.system(size: 11)).foregroundStyle(t.faint)
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
