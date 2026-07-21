import SwiftUI
import AppKit
import SessionCore

/// The desktop Session, Option A: sidebar + content + a persistent transport
/// bar (the Music-app shape). Favourites and History are destinations you
/// visit, not permanent rails; the genre sections sit in the sidebar with
/// MIX / TUNE IN one click away; the transport never leaves the bottom edge.
enum MacDest: Hashable {
    case stage, dial, shelf, favs, history, you
    case genre(String)
}

struct MainWindowView: View {
    @EnvironmentObject var player: Player
    @Environment(\.colorScheme) var scheme
    @AppStorage("accent") var accentHex = "#FFD200"
    @AppStorage("theme") var themePref = "auto"
    @AppStorage("dance") var dance = false
    @AppStorage("saver") var saverMode = "rotate"
    @AppStorage("zoom") var zoom = 1.0
    @State var dest: MacDest = .stage
    @State var confirmSkip = false
    @State var showSettings = false
    @State var saverOn = false
    @State var lastActive = Date()

    var t: Theme {
        Theme.current(scheme, accentHex: accentHex,
                      dance: dance && player.status == .playing ? player.dancePhase : nil)
    }

    var body: some View {
        GeometryReader { geo in
            ZStack {
                VStack(spacing: 0) {
                    Masthead(t: t, confirmSkip: $confirmSkip,
                             onGear: { showSettings = true },
                             onSaver: { saverOn = true })
                    if let rip = player.rip, rip.ripping {
                        RipBar(rip: rip, t: t)
                    }
                    HStack(spacing: 0) {
                        Sidebar(dest: $dest, t: t)
                            .frame(width: 214)
                            .background(t.panel)
                        Rectangle().fill(t.line).frame(width: 1)
                        content
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                            .background(t.board)
                    }
                    TransportBar(t: t, confirmSkip: $confirmSkip) { dest = .stage }
                }
                if saverOn {
                    SaverOverlay(t: t, mode: saverMode) {
                        saverOn = false
                        lastActive = Date()
                    }
                    .transition(.opacity)
                }
            }
            .frame(width: max(geo.size.width, 1) / zoom, height: max(geo.size.height, 1) / zoom)
            .scaleEffect(zoom, anchor: .topLeading)
        }
        .background(t.board)
        .frame(minWidth: 860 * max(1, zoom), minHeight: 560 * max(1, zoom))
        .preferredColorScheme(themePref == "dark" ? .dark : themePref == "light" ? .light : nil)
        .onContinuousHover { _ in
            lastActive = Date()
            if saverOn { saverOn = false }
        }
        .sheet(isPresented: $showSettings) {
            SettingsSheet().environmentObject(player)
        }
        .task {   // idle → the saver
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(10))
                if !saverOn, Date().timeIntervalSince(lastActive) > 180 {
                    saverOn = true
                }
            }
        }
        .onAppear {
            NSApp.setActivationPolicy(.regular)
            NSApp.activate(ignoringOtherApps: true)
        }
        .onDisappear {
            NSApp.setActivationPolicy(.accessory)
        }
    }

    @ViewBuilder var content: some View {
        switch dest {
        case .stage:
            VStack(alignment: .leading, spacing: 0) {
                NowPlayingPane(t: t, confirmSkip: $confirmSkip)
                Divider().overlay(t.line)
                Tracklist(t: t)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        case .dial:
            TunerList(t: t, fixedHeight: nil, browseAlbums: true,
                      onAction: { dest = .stage })
        case .shelf:
            ShelfGallery(t: t, initialSection: "") { al in
                player.browseAlbum(al)
                dest = .stage
            }
        case .genre(let g):
            ShelfGallery(t: t, initialSection: g) { al in
                player.browseAlbum(al)
                dest = .stage
            }
            .id(g)      // fresh state per section
        case .favs:
            FavList(t: t)
        case .history:
            HistoryList(t: t)
                .task { await player.refreshHistory() }
        case .you:
            ScrollView { SettingsPane(t: t) }
        }
    }
}

// ── the sidebar ──────────────────────────────────────────────────────────

struct Sidebar: View {
    @EnvironmentObject var player: Player
    @Binding var dest: MacDest
    let t: Theme

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 2) {
                SideItem(label: "Now Playing", glyph: "▶", sel: dest == .stage, t: t) { dest = .stage }
                SideItem(label: "The Dial", glyph: "◉", sel: dest == .dial, t: t) { dest = .dial }
                SideItem(label: "The Shelf", glyph: "▤", sel: dest == .shelf, t: t) { dest = .shelf }
                if player.member != nil {
                    SideItem(label: "Favourites", glyph: "♥", sel: dest == .favs, t: t,
                             glyphColor: t.red) { dest = .favs }
                }
                SideItem(label: "History", glyph: "⏱", sel: dest == .history, t: t) { dest = .history }
                SideItem(label: "You", glyph: "◎", sel: dest == .you, t: t) { dest = .you }

                if !player.genres.isEmpty {
                    Text("FROM THE SHELF")
                        .font(.system(size: 9, weight: .heavy)).tracking(1.8)
                        .foregroundStyle(t.accent)
                        .padding(.horizontal, 14).padding(.top, 16).padding(.bottom, 4)
                    ForEach(player.genres) { g in
                        SideItem(label: g.name, glyph: "♫", sel: dest == .genre(g.name), t: t,
                                 badge: "\(g.count)") { dest = .genre(g.name) }
                    }
                }
            }
            .padding(.vertical, 10)
        }
    }
}

struct SideItem: View {
    let label: String
    let glyph: String
    let sel: Bool
    let t: Theme
    var glyphColor: Color? = nil
    var badge: String? = nil
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 9) {
                Text(glyph).font(.system(size: 12))
                    .foregroundStyle(glyphColor ?? (sel ? t.accent : t.faint))
                    .frame(width: 16)
                Text(label)
                    .font(.system(size: 13, weight: sel ? .heavy : .semibold))
                    .foregroundStyle(t.ink)
                    .lineLimit(1)
                Spacer()
                if let badge {
                    Text(badge).font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(t.faint)
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 7)
            .background(sel ? t.sunk : (hover ? t.sunk.opacity(0.6) : .clear))
            .overlay(alignment: .leading) {
                if sel { Rectangle().fill(t.accent).frame(width: 3) }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .padding(.horizontal, 6)
    }
}

// ── the transport bar: the music never leaves the bottom edge ────────────

struct TransportBar: View {
    @EnvironmentObject var player: Player
    let t: Theme
    @Binding var confirmSkip: Bool
    let goStage: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Button(action: goStage) {
                HStack(spacing: 10) {
                    ArtTile(t: t, size: 40)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(player.now.title.isEmpty ? (player.current?.name ?? "Tune in")
                                                      : player.now.title)
                            .font(.system(size: 12.5, weight: .semibold))
                            .foregroundStyle(t.ink).lineLimit(1)
                        Text(player.now.artist)
                            .font(.system(size: 10.5)).foregroundStyle(t.muted).lineLimit(1)
                    }
                    .frame(width: 170, alignment: .leading)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            SquareButton(label: "◂◂", t: t, small: true) { player.stepBack() }
            Button {
                player.toggle()
            } label: {
                Text(player.isPlaying ? "❚❚" : "▶")
                    .font(.system(size: 13, weight: .bold))
                    .frame(width: 36, height: 36)
                    .background(t.accent).foregroundStyle(t.onAccent)
                    .clipShape(RoundedRectangle(cornerRadius: 2))
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            SquareButton(label: "▸▸", t: t, small: true) {
                if player.source == .radio { confirmSkip = true } else { player.stepForward() }
            }
            .confirmationDialog("Skip moves the station for everyone listening.",
                                isPresented: $confirmSkip, titleVisibility: .visible) {
                Button("Skip the show") { player.skipRadio() }
                Button("Stay with it", role: .cancel) {}
            }
            Button {
                player.toggleFavourite()
            } label: {
                Text("♥").font(.system(size: 13))
                    .frame(width: 30, height: 30)
                    .foregroundStyle(player.nowIsFavourite ? t.red : t.faint)
                    .overlay(RoundedRectangle(cornerRadius: 2)
                        .stroke(player.nowIsFavourite ? t.red : t.line, lineWidth: 2))
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(player.member == nil || player.now.url.isEmpty)
            .opacity(player.member == nil ? 0.3 : 1)

            if player.source == .radio {
                if player.status == .playing {
                    HStack(spacing: 6) {
                        Circle().fill(t.red).frame(width: 7, height: 7)
                        Text("ON AIR · \((player.current?.name ?? "").uppercased())")
                            .font(.system(size: 9, weight: .heavy)).tracking(1.4)
                    }
                    .foregroundStyle(t.red)
                    .frame(maxWidth: .infinity)
                } else {
                    Text(player.status == .tuning ? "TUNING IN…" : " ")
                        .font(.system(size: 9, weight: .heavy)).tracking(1.4)
                        .foregroundStyle(t.muted)
                        .frame(maxWidth: .infinity)
                }
            } else {
                HStack(spacing: 8) {
                    Text(mmss(player.position)).font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(t.muted)
                    Slider(value: Binding(
                        get: { player.position },
                        set: { player.position = $0 }
                    ), in: 0...max(player.duration, 1)) { editing in
                        player.isScrubbing = editing
                        if !editing { player.seek(to: player.position) }
                    }
                    .controlSize(.mini)
                    .tint(t.blue)
                    Text(mmss(player.duration)).font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(t.muted)
                }
                .frame(maxWidth: .infinity)
            }

            SourceSwitch(t: t)
            Image(systemName: "speaker.wave.2").font(.system(size: 10)).foregroundStyle(t.muted)
            VolumeSlider(t: t).frame(width: 70)
        }
        .padding(.horizontal, 14).padding(.vertical, 9)
        .background(t.panel)
        .overlay(alignment: .top) { Rectangle().fill(t.line).frame(height: 1) }
    }

    func mmss(_ s: Double) -> String {
        let n = Int(s.isFinite ? max(s, 0) : 0)
        return String(format: "%d:%02d", n / 60, n % 60)
    }
}

// ── LISTEN AND RIP, first-class ──────────────────────────────────────────

struct RipBar: View {
    let rip: RipStatus
    let t: Theme
    @State private var lampOn = true

    var body: some View {
        HStack(spacing: 10) {
            Circle().fill(t.red).frame(width: 8, height: 8).opacity(lampOn ? 1 : 0.25)
                .onAppear {
                    withAnimation(.easeInOut(duration: 0.6).repeatForever()) { lampOn.toggle() }
                }
            Text("NOW RIPPING").font(.system(size: 10, weight: .heavy)).tracking(1.8)
            Text("\(rip.album) · track \(rip.track)/\(rip.total)")
                .font(.system(size: 12, weight: .medium, design: .monospaced))
                .opacity(0.85)
            Spacer()
        }
        .padding(.horizontal, 16).padding(.vertical, 8)
        .foregroundStyle(t.onAccent)
        .background(
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    t.accent
                    t.onAccent.opacity(0.12)
                        .frame(width: geo.size.width
                               * CGFloat(rip.total > 0 ? Double(rip.track) / Double(rip.total) : 0))
                }
            }
        )
        .overlay(alignment: .leading) { Rectangle().fill(t.red).frame(width: 4) }
    }
}

// ── the shelf gallery (content view; section preselectable) ──────────────

struct ShelfGallery: View {
    @EnvironmentObject var player: Player
    let t: Theme
    let onPick: (Album) -> Void
    @State var section: String
    @State private var find = ""
    @AppStorage("shelfView") var shelfView = "grid"

    init(t: Theme, initialSection: String, onPick: @escaping (Album) -> Void) {
        self.t = t
        self.onPick = onPick
        _section = State(initialValue: initialSection)
    }

    var albums: [Album] {
        player.albums.filter { al in
            (section.isEmpty || al.genres.contains(section))
            && (find.isEmpty
                || al.album.localizedCaseInsensitiveContains(find)
                || al.artist.localizedCaseInsensitiveContains(find))
        }
    }

    func shelfChannel(for s: String) -> Channel? {
        let slug = "shelf-" + s.lowercased()
            .replacingOccurrences(of: "[^a-z0-9]+", with: "-", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        return player.channels.first { $0.slug == slug && $0.playable }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(section.isEmpty ? "THE SHELF" : section.uppercased())
                    .font(.system(size: 12, weight: .heavy)).tracking(2)
                    .foregroundStyle(t.ink)
                if !section.isEmpty {
                    Button {
                        player.playMix(section)
                    } label: {
                        Text("▶ \(section.uppercased()) MIX")
                            .font(.system(size: 10, weight: .heavy)).tracking(0.8)
                            .padding(.horizontal, 11).padding(.vertical, 6)
                            .background(t.accent).foregroundStyle(t.onAccent)
                            .clipShape(Capsule())
                            .contentShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    if let ch = shelfChannel(for: section) {
                        Button {
                            player.tune(ch)
                        } label: {
                            Text("((( TUNE IN")
                                .font(.system(size: 10, weight: .heavy)).tracking(0.8)
                                .padding(.horizontal, 11).padding(.vertical, 6)
                                .foregroundStyle(t.red)
                                .overlay(Capsule().stroke(t.red, lineWidth: 1.5))
                                .contentShape(Capsule())
                        }
                        .buttonStyle(.plain)
                    }
                }
                TextField("search", text: $find)
                    .textFieldStyle(.plain)
                    .font(.system(size: 12))
                    .padding(.horizontal, 10).padding(.vertical, 6)
                    .frame(maxWidth: 200)
                    .background(t.board)
                    .overlay(RoundedRectangle(cornerRadius: 2).stroke(t.line, lineWidth: 1))
                HStack(spacing: 0) {
                    ForEach([("grid", "▦"), ("list", "☰")], id: \.0) { mode, glyph in
                        Button {
                            shelfView = mode
                        } label: {
                            Text(glyph).font(.system(size: 12))
                                .frame(width: 30, height: 26)
                                .background(shelfView == mode ? t.accent : t.panel)
                                .foregroundStyle(shelfView == mode ? t.onAccent : t.muted)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(t.line, lineWidth: 1))
                .clipShape(RoundedRectangle(cornerRadius: 6))
                Spacer()
                Text("\(albums.count) RECORDS")
                    .font(.system(size: 9, weight: .heavy)).tracking(1)
                    .foregroundStyle(t.faint)
            }
            .padding(.horizontal, 18).padding(.vertical, 12)
            if shelfView == "list" {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(albums) { al in
                            Button {
                                onPick(al)
                            } label: {
                                HStack(spacing: 12) {
                                    CoverTile(al: al, t: t, corner: 5)
                                        .frame(width: 44, height: 44)
                                    VStack(alignment: .leading, spacing: 1) {
                                        Text(al.album)
                                            .font(.system(size: 13.5, weight: .semibold))
                                            .foregroundStyle(t.ink).lineLimit(1)
                                        Text(al.artist + (al.year.map { " · \($0)" } ?? ""))
                                            .font(.system(size: 11.5))
                                            .foregroundStyle(t.muted).lineLimit(1)
                                    }
                                    Spacer()
                                    if !al.genres.isEmpty {
                                        Text(al.genres.joined(separator: " · "))
                                            .font(.system(size: 9, weight: .bold)).tracking(0.5)
                                            .foregroundStyle(t.faint)
                                    }
                                    Text("\(al.trackCount) TRK")
                                        .font(.system(size: 9, weight: .heavy)).tracking(1)
                                        .foregroundStyle(t.faint)
                                }
                                .padding(.horizontal, 16).padding(.vertical, 7)
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .overlay(alignment: .bottom) {
                                Rectangle().fill(t.line).frame(height: 1).padding(.leading, 70)
                            }
                        }
                    }
                    .padding(.bottom, 24)
                }
            } else {
                ScrollView {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: 18)], spacing: 22) {
                        ForEach(albums) { al in
                            Button {
                                onPick(al)
                            } label: {
                                VStack(alignment: .leading, spacing: 0) {
                                    CoverTile(al: al, t: t, corner: 6)
                                        .aspectRatio(1, contentMode: .fit)
                                        .shadow(color: .black.opacity(0.45), radius: 12, y: 8)
                                    Text(al.album)
                                        .font(.system(size: 12.5, weight: .semibold))
                                        .foregroundStyle(t.ink).lineLimit(1)
                                        .padding(.top, 9)
                                    Text(al.artist + (al.year.map { " · \($0)" } ?? ""))
                                        .font(.system(size: 10.5))
                                        .foregroundStyle(t.muted).lineLimit(1)
                                        .padding(.top, 1)
                                }
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.horizontal, 18).padding(.bottom, 24)
                }
            }
        }
    }
}

/// One cover: real art when the enricher found it, else the pressed-sleeve
/// gradient + monogram (hue seeded by the album name, like the web's tiles).
struct CoverTile: View {
    @EnvironmentObject var player: Player
    let al: Album
    let t: Theme
    var corner: CGFloat = 5

    var body: some View {
        ZStack {
            let hue = Double(abs(al.album.hashValue % 360)) / 360.0
            LinearGradient(
                colors: [Color(hue: hue, saturation: 0.30, brightness: 0.34),
                         Color(hue: hue, saturation: 0.38, brightness: 0.12)],
                startPoint: .topLeading, endPoint: .bottomTrailing)
            Text(String(al.album.prefix(1)))
                .font(.system(size: 42, weight: .ultraLight))
                .foregroundStyle(.white.opacity(0.92))
            MacNetImage(url: al.coverURL(base: player.stationBase))
        }
        .clipShape(RoundedRectangle(cornerRadius: corner))
    }
}

// ── favourites & history as destinations ─────────────────────────────────

struct FavList: View {
    @EnvironmentObject var player: Player
    let t: Theme

    var body: some View {
        if player.member == nil {
            EmptyNote(t: t, title: "Sign in to keep favourites",
                      sub: "♥ a track and it follows you — this list plays as a station.")
        } else if player.favs.isEmpty {
            EmptyNote(t: t, title: "Nothing here yet",
                      sub: "♥ what's playing and it lands on this list.")
        } else {
            ScrollView {
                VStack(spacing: 0) {
                    Text("FAVOURITES — plays as a station, top to bottom")
                        .font(.system(size: 10, weight: .heavy)).tracking(1.5)
                        .foregroundStyle(t.muted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 16).padding(.vertical, 12)
                    ForEach(Array(player.favs.enumerated()), id: \.element.url) { i, f in
                        Button {
                            player.playFavourites(at: i)
                        } label: {
                            HStack(spacing: 10) {
                                Text("♥").font(.system(size: 13)).foregroundStyle(t.red)
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(f.title.isEmpty ? f.album : f.title)
                                        .font(.system(size: 13.5, weight: .semibold))
                                        .foregroundStyle(t.ink).lineLimit(1)
                                    Text(f.artist)
                                        .font(.system(size: 11)).foregroundStyle(t.muted).lineLimit(1)
                                }
                                Spacer()
                                Text("▶").font(.system(size: 11)).foregroundStyle(t.faint)
                            }
                            .padding(.horizontal, 16).padding(.vertical, 8)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .overlay(alignment: .bottom) {
                            Rectangle().fill(t.line).frame(height: 1).padding(.horizontal, 12)
                        }
                    }
                }
            }
        }
    }
}

struct HistoryList: View {
    @EnvironmentObject var player: Player
    let t: Theme

    var body: some View {
        if player.history.isEmpty {
            EmptyNote(t: t, title: "Quiet so far", sub: "the station's play log lands here.")
        } else {
            ScrollView {
                VStack(spacing: 0) {
                    Text("ON THE STATION LATELY")
                        .font(.system(size: 10, weight: .heavy)).tracking(1.5)
                        .foregroundStyle(t.muted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 16).padding(.vertical, 12)
                    ForEach(player.history) { h in
                        HStack(spacing: 10) {
                            Text(h.channel.uppercased())
                                .font(.system(size: 8, weight: .heavy)).tracking(0.8)
                                .foregroundStyle(t.muted)
                                .frame(width: 90, alignment: .leading)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(h.title.isEmpty ? h.album : h.title)
                                    .font(.system(size: 13, weight: .semibold))
                                    .foregroundStyle(t.ink).lineLimit(1)
                                Text(h.artist)
                                    .font(.system(size: 11)).foregroundStyle(t.muted).lineLimit(1)
                            }
                            Spacer()
                            Text(h.when)
                                .font(.system(size: 10, design: .monospaced))
                                .foregroundStyle(t.faint)
                        }
                        .padding(.horizontal, 16).padding(.vertical, 7)
                        .overlay(alignment: .bottom) {
                            Rectangle().fill(t.line).frame(height: 1).padding(.horizontal, 12)
                        }
                    }
                }
            }
        }
    }
}

struct EmptyNote: View {
    let t: Theme
    let title: String
    let sub: String

    var body: some View {
        VStack(spacing: 6) {
            Text(title).font(.system(size: 13, weight: .bold)).foregroundStyle(t.ink)
            Text(sub).font(.system(size: 11)).foregroundStyle(t.muted)
                .multilineTextAlignment(.center)
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// ── the set list ─────────────────────────────────────────────────────────

struct Tracklist: View {
    @EnvironmentObject var player: Player
    let t: Theme
    @State private var lightbox: AlbumImage?

    var display: Show? { player.browsed?.show ?? player.show }

    var playingIndex: Int {
        if let b = player.browsed {
            return (player.source == .cd && player.currentAlbum?.dir == b.album.dir)
                ? player.trackIndex : -1
        }
        return player.source == .radio ? (player.show?.playing ?? -1) : player.trackIndex
    }

    var body: some View {
        if let sh = display, !sh.tracks.isEmpty {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 10) {
                    Text(sh.album.isEmpty ? "THE SET" : sh.album)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(t.ink)
                    if player.browsed != nil {
                        Button {
                            player.playBrowsed(at: 0)
                        } label: {
                            Text("▶ PLAY").font(.system(size: 9, weight: .heavy)).tracking(1)
                                .padding(.horizontal, 8).padding(.vertical, 4)
                                .background(t.accent).foregroundStyle(t.onAccent)
                                .clipShape(RoundedRectangle(cornerRadius: 2))
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        Button {
                            player.closeBrowse()
                        } label: {
                            Text("✕").font(.system(size: 10, weight: .heavy))
                                .frame(width: 20, height: 20)
                                .foregroundStyle(t.muted)
                                .overlay(RoundedRectangle(cornerRadius: 2).stroke(t.line, lineWidth: 1))
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .help("back to what's playing")
                    }
                    Spacer()
                }
                .padding(.horizontal, 22).padding(.top, 12).padding(.bottom, 6)
                if !sh.images.isEmpty {
                    // the record's photo strip: cover, tracklist insert, back, disc…
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(sh.images) { img in
                                Button {
                                    lightbox = img
                                } label: {
                                    VStack(spacing: 3) {
                                        MacNetImage(url: img.imageURL(base: player.stationBase))
                                            .frame(width: 64, height: 64)
                                            .background(t.sunk)
                                            .clipShape(RoundedRectangle(cornerRadius: 4))
                                        Text(img.type.uppercased())
                                            .font(.system(size: 7, weight: .heavy)).tracking(1)
                                            .foregroundStyle(t.faint)
                                    }
                                    .contentShape(Rectangle())
                                }
                                .buttonStyle(.plain)
                            }
                        }
                        .padding(.horizontal, 22)
                    }
                    .padding(.bottom, 8)
                }
                ScrollView {
                    VStack(spacing: 0) {
                        ForEach(Array(sh.tracks.enumerated()), id: \.offset) { i, track in
                            TrackRow(index: i, track: track, playing: playingIndex, t: t)
                        }
                    }
                    .padding(.horizontal, 12).padding(.bottom, 16)
                }
            }
            .sheet(item: $lightbox) { img in
                VStack(spacing: 10) {
                    MacNetImage(url: img.imageURL(base: player.stationBase))
                        .aspectRatio(contentMode: .fit)
                        .frame(minWidth: 480, minHeight: 420)
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                    Text(img.type.uppercased())
                        .font(.system(size: 9, weight: .heavy)).tracking(2)
                        .foregroundStyle(t.faint)
                }
                .padding(20)
                .background(t.board)
                .onTapGesture { lightbox = nil }
            }
        } else {
            Text("tune a channel — the set list appears here")
                .font(.system(size: 12)).foregroundStyle(t.faint)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}

struct TrackRow: View {
    @EnvironmentObject var player: Player
    let index: Int
    let track: ShowTrack
    let playing: Int
    let t: Theme
    @State private var hover = false

    var isNow: Bool { index == playing }
    var isDone: Bool { index < playing }
    var clickable: Bool { player.browsed != nil || player.source != .radio }

    var body: some View {
        Button {
            if player.browsed != nil { player.playBrowsed(at: index) }
            else if clickable { player.jump(to: index) }
        } label: {
            HStack(spacing: 12) {
                Text(isDone ? "✓" : (isNow ? "▶" : " "))
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(isDone ? t.live : (isNow ? t.blue : t.faint))
                    .frame(width: 16)
                Text(String(format: "%02d", index + 1))
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(isNow ? t.blue : t.faint)
                Text(track.title.isEmpty ? "Track \(index + 1)" : track.title)
                    .font(.system(size: 13, weight: isNow ? .heavy : .semibold))
                    .foregroundStyle(isNow ? t.blue : t.ink)
                    .lineLimit(1)
                Spacer()
                if isNow {
                    Text("NOW").font(.system(size: 9, weight: .heavy)).tracking(1.4)
                        .foregroundStyle(t.blue)
                } else if isDone {
                    Text("PLAYED").font(.system(size: 9, weight: .heavy)).tracking(1.4)
                        .foregroundStyle(t.faint)
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background(isNow ? t.sunk : (hover && clickable ? t.sunk.opacity(0.6) : .clear))
            .overlay(alignment: .leading) {
                if isNow { Rectangle().fill(t.blue).frame(width: 3) }
            }
            .opacity(isDone ? 0.55 : 1)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!clickable)
        .onHover { hover = $0 }
    }
}
