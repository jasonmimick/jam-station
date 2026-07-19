import SwiftUI
import AppKit
import SessionCore

/// P1 pulled forward: the desktop Session. Left pane = the Tuner (with search),
/// stage = board + transport + the set list, rip bar on top when a disc is going.
/// While this window is open the app is a regular Dock citizen; close it and
/// Session slips back to being a menu-bar app (the music keeps playing).
struct MainWindowView: View {
    @EnvironmentObject var player: Player
    @Environment(\.colorScheme) var scheme
    @AppStorage("accent") var accentHex = "#FFD200"
    @AppStorage("theme") var themePref = "auto"
    @AppStorage("dance") var dance = false
    @AppStorage("saver") var saverMode = "rotate"
    @AppStorage("zoom") var zoom = 1.0
    @State var confirmSkip = false
    @State var showSettings = false
    @State var saverOn = false
    @State var lastActive = Date()

    var t: Theme {
        Theme.current(scheme, accentHex: accentHex,
                      dance: dance && player.status == .playing ? player.dancePhase : nil)
    }

    var body: some View {
        // ⌘= / ⌘- / ⌘0 zoom: render at the inverse size, scale up — crisp, no reflow bugs
        GeometryReader { geo in
        ZStack {
            VStack(spacing: 0) {
                Masthead(t: t, confirmSkip: $confirmSkip,
                         onGear: { showSettings = true },
                         onSaver: { saverOn = true })
                if let rip = player.rip, rip.ripping {
                    RipBar(rip: rip, t: t)
                }
                HSplitView {
                    TunerList(t: t, fixedHeight: nil, browseAlbums: true)
                        .frame(minWidth: 190, idealWidth: 270, maxWidth: 380)
                        .background(t.panel)
                    StagePane(t: t, confirmSkip: $confirmSkip)
                        .frame(minWidth: 360, maxWidth: .infinity)
                    RightPane(t: t)
                        .frame(minWidth: 210, idealWidth: 300, maxWidth: 380)
                        .background(t.panel)
                }
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
        // the scaled-down layout must never dip below the panes' combined minimums
        // (190+360+210) or NSSplitView's constraints go unsatisfiable and AppKit traps —
        // so the window's own minimum grows with the zoom
        .frame(minWidth: 800 * max(1, zoom), minHeight: 540 * max(1, zoom))
        .preferredColorScheme(themePref == "dark" ? .dark : themePref == "light" ? .light : nil)
        .onContinuousHover { _ in
            lastActive = Date()
            if saverOn { saverOn = false }
        }
        .sheet(isPresented: $showSettings) {
            SettingsSheet().environmentObject(player)
        }
        .task {   // idle watchdog: 3 quiet minutes in the window → the saver
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(10))
                if !saverOn, Date().timeIntervalSince(lastActive) > 180 {
                    saverOn = true
                }
            }
        }
        .onAppear {
            NSApp.setActivationPolicy(.regular)   // show in the Dock while the window lives
            NSApp.activate(ignoringOtherApps: true)
        }
        .onDisappear {
            NSApp.setActivationPolicy(.accessory) // back to a pure menu-bar app
        }
    }
}

/// LISTEN AND RIP, first-class: the web's #ripBar, native.
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

struct StagePane: View {
    @EnvironmentObject var player: Player
    let t: Theme
    @Binding var confirmSkip: Bool
    @State private var tab = "playing"

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if player.member != nil {
                HStack(spacing: 8) {
                    PillTab(label: "PLAYING", on: tab == "playing", t: t) { tab = "playing" }
                    PillTab(label: "SHELF", on: tab == "shelf", t: t) { tab = "shelf" }
                    Spacer()
                }
                .padding(.horizontal, 14).padding(.vertical, 9)
                .overlay(alignment: .bottom) { Rectangle().fill(t.line).frame(height: 1) }
            }
            if tab == "shelf", player.member != nil {
                ShelfGallery(t: t) { al in
                    player.browseAlbum(al)
                    tab = "playing"
                }
            } else {
                NowPlayingPane(t: t, confirmSkip: $confirmSkip)
                Divider().overlay(t.line)
                Tracklist(t: t)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(t.board)
    }
}

/// The record gallery — the web's CDs view: covers in a grid, search, click to browse.
struct ShelfGallery: View {
    @EnvironmentObject var player: Player
    let t: Theme
    let onPick: (Album) -> Void
    @State private var find = ""
    @State private var section = ""
    @AppStorage("shelfView") var shelfView = "grid"

    var albums: [Album] {
        player.albums.filter { al in
            (section.isEmpty || al.genres.contains(section))
            && (find.isEmpty
                || al.album.localizedCaseInsensitiveContains(find)
                || al.artist.localizedCaseInsensitiveContains(find))
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("THE SHELF").font(.system(size: 10, weight: .heavy)).tracking(2)
                    .foregroundStyle(t.muted)
                TextField("search the shelf", text: $find)
                    .textFieldStyle(.plain)
                    .font(.system(size: 12))
                    .padding(.horizontal, 10).padding(.vertical, 6)
                    .frame(maxWidth: 260)
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
            if !player.genres.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 7) {
                        MacChip(label: "ALL", on: section.isEmpty, t: t) { section = "" }
                        ForEach(player.genres) { g in
                            MacChip(label: "\(g.name.uppercased()) · \(g.count)",
                                    on: section == g.name, t: t) {
                                section = section == g.name ? "" : g.name
                            }
                        }
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
                        }
                    }
                    .padding(.horizontal, 18)
                }
                .padding(.bottom, 10)
            }
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

struct MacChip: View {
    let label: String
    let on: Bool
    let t: Theme
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(label)
                .font(.system(size: 10, weight: .heavy)).tracking(0.5)
                .padding(.horizontal, 11).padding(.vertical, 6)
                .background(on ? t.accent : t.panel)
                .foregroundStyle(on ? t.onAccent : t.muted)
                .clipShape(Capsule())
                .overlay(Capsule().stroke(on ? t.accent : t.line, lineWidth: 1))
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
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
            if let url = al.coverURL(base: player.stationBase) {
                AsyncImage(url: url) { img in
                    img.resizable().aspectRatio(contentMode: .fill)
                } placeholder: { Color.clear }
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: corner))
    }
}

/// The set list — the schedule rows from the web's center pane.
/// Radio: read-only (✓ played · NOW · coming up). Tape/CD: click a row to jump.
struct Tracklist: View {
    @EnvironmentObject var player: Player
    let t: Theme

    /// A browsed record takes the stage list over; otherwise the playing show.
    var display: Show? { player.browsed?.show ?? player.show }

    var playingIndex: Int {
        if let b = player.browsed {
            // only mark NOW if the browsed record is the one actually playing
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
                ScrollView {
                    VStack(spacing: 0) {
                        ForEach(Array(sh.tracks.enumerated()), id: \.offset) { i, track in
                            TrackRow(index: i, track: track, playing: playingIndex, t: t)
                        }
                    }
                    .padding(.horizontal, 12).padding(.bottom, 16)
                }
            }
        } else {
            Text("tune a channel — the set list appears here")
                .font(.system(size: 12)).foregroundStyle(t.faint)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}

/// The right rail: Favourites / History (Shelf lives in the Tuner; You in settings).
struct RightPane: View {
    @EnvironmentObject var player: Player
    let t: Theme
    @State private var tab = "favs"

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                PillTab(label: "FAVOURITES", on: tab == "favs", t: t) { tab = "favs" }
                PillTab(label: "HISTORY", on: tab == "hist", t: t) {
                    tab = "hist"
                    Task { await player.refreshHistory() }
                }
                Spacer()
            }
            .padding(.horizontal, 12).padding(.vertical, 10)
            .overlay(alignment: .bottom) { Rectangle().fill(t.line).frame(height: 1) }

            if tab == "favs" { FavList(t: t) } else { HistoryList(t: t) }
        }
        .onAppear { Task { await player.refreshHistory() } }
    }
}

struct PillTab: View {
    let label: String
    let on: Bool
    let t: Theme
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(label)
                .font(.system(size: 10, weight: .bold)).tracking(0.5)
                .padding(.horizontal, 12).padding(.vertical, 6)
                .foregroundStyle(on ? t.onAccent : t.muted)
                .background(Capsule().fill(on ? t.accent : .clear))
                .overlay(Capsule().stroke(on ? t.accent : t.line, lineWidth: 1))
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
    }
}

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
                    ForEach(Array(player.favs.enumerated()), id: \.element.url) { i, f in
                        Button {
                            player.playFavourites(at: i)
                        } label: {
                            HStack(spacing: 9) {
                                Text("♥").font(.system(size: 12)).foregroundStyle(t.red)
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(f.title.isEmpty ? f.album : f.title)
                                        .font(.system(size: 12.5, weight: .semibold))
                                        .foregroundStyle(t.ink).lineLimit(1)
                                    Text(f.artist)
                                        .font(.system(size: 10.5)).foregroundStyle(t.muted).lineLimit(1)
                                }
                                Spacer()
                                Text("▶").font(.system(size: 10)).foregroundStyle(t.faint)
                            }
                            .padding(.horizontal, 12).padding(.vertical, 7)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .overlay(alignment: .bottom) {
                            Rectangle().fill(t.line).frame(height: 1).padding(.horizontal, 10)
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
                    ForEach(player.history) { h in
                        HStack(spacing: 9) {
                            Text(h.channel.uppercased())
                                .font(.system(size: 8, weight: .heavy)).tracking(0.8)
                                .foregroundStyle(t.muted)
                                .frame(width: 74, alignment: .leading)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(h.title.isEmpty ? h.album : h.title)
                                    .font(.system(size: 12, weight: .semibold))
                                    .foregroundStyle(t.ink).lineLimit(1)
                                Text(h.artist)
                                    .font(.system(size: 10.5)).foregroundStyle(t.muted).lineLimit(1)
                            }
                            Spacer()
                            Text(h.when)
                                .font(.system(size: 10, design: .monospaced))
                                .foregroundStyle(t.faint)
                        }
                        .padding(.horizontal, 12).padding(.vertical, 7)
                        .overlay(alignment: .bottom) {
                            Rectangle().fill(t.line).frame(height: 1).padding(.horizontal, 10)
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
