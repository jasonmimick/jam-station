import SwiftUI
import SessionCore

// ── the popover ──────────────────────────────────────────────────────────

struct PopoverView: View {
    @EnvironmentObject var player: Player
    @Environment(\.colorScheme) var scheme
    @AppStorage("accent") var accentHex = "#FFD200"
    @AppStorage("theme") var themePref = "auto"
    @AppStorage("dance") var dance = false
    @State var showSettings = false
    @State var confirmSkip = false

    var t: Theme {
        Theme.current(scheme, accentHex: accentHex,
                      dance: dance && player.status == .playing ? player.dancePhase : nil)
    }

    var body: some View {
        VStack(spacing: 0) {
            Masthead(t: t, confirmSkip: $confirmSkip)
            if showSettings {
                SettingsPane(t: t)
            } else {
                NowPlayingPane(t: t, confirmSkip: $confirmSkip)
                Divider().overlay(t.line)
                TunerList(t: t)
            }
            FooterBar(t: t, showSettings: $showSettings)
        }
        .frame(width: 390)
        .background(t.board)
        .preferredColorScheme(themePref == "dark" ? .dark : themePref == "light" ? .light : nil)
        .onAppear { Task { await player.refreshChannels() } }
    }
}

// ── masthead: the signage bar, modes riding in it ────────────────────────

struct Masthead: View {
    @EnvironmentObject var player: Player
    let t: Theme
    @Binding var confirmSkip: Bool
    var onGear: (() -> Void)? = nil
    var onSaver: (() -> Void)? = nil

    var body: some View {
        HStack(spacing: 10) {
            ZStack {
                RoundedRectangle(cornerRadius: 3).fill(Color(hex: "#1C1C20"))
                    .frame(width: 26, height: 22)
                Capsule().fill(t.accent).frame(width: 2.6, height: 15).offset(x: 6)
                Circle().fill(Color(hex: "#F0402F")).frame(width: 4.5, height: 4.5)
                    .offset(x: 6, y: -7.5)
                Capsule().fill(t.accent.opacity(0.85)).frame(width: 13, height: 2)
                    .offset(x: -2, y: 5.5)
            }
            Text("SESSION")
                .font(.system(size: 12, weight: .heavy))
                .tracking(2)
                .foregroundStyle(t.onAccent)
            Text("· \(stationName)")
                .font(.system(size: 9, weight: .bold)).tracking(1)
                .foregroundStyle(t.onAccent.opacity(0.6))
            Spacer()
            if let onSaver {
                Button(action: onSaver) {
                    Text("▓")
                        .font(.system(size: 12, weight: .bold))
                        .frame(width: 28, height: 28)
                        .foregroundStyle(t.onAccent)
                        .overlay(RoundedRectangle(cornerRadius: 2).stroke(t.onAccent, lineWidth: 2))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("screensaver now (it also starts on its own after 3 idle minutes)")
            }
            if let onGear {
                Button(action: onGear) {
                    Image(systemName: "gearshape")
                        .font(.system(size: 12, weight: .bold))
                        .frame(width: 28, height: 28)
                        .foregroundStyle(t.onAccent)
                        .overlay(RoundedRectangle(cornerRadius: 2).stroke(t.onAccent, lineWidth: 2))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("settings — station, sign-in, signage colour (⌘,)")
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 9)
        .background(t.accent)
    }

    var stationName: String {
        (player.stationBase.host ?? "JAM-STATION")
            .replacingOccurrences(of: ".runslab.run", with: "")
            .uppercased()
    }
}

// ── now playing: the board, miniaturized ─────────────────────────────────

struct NowPlayingPane: View {
    @EnvironmentObject var player: Player
    let t: Theme
    @Binding var confirmSkip: Bool
    @State private var lampOn = true

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("NOW PLAYING").font(.system(size: 10, weight: .bold)).tracking(2.6)
                    .foregroundStyle(t.faint)
                Spacer()
                statusBadge
            }
            HStack(alignment: .top, spacing: 14) {
                ArtTile(t: t)
                VStack(alignment: .leading, spacing: 5) {
                    Text(title)
                        .font(.system(size: 22, weight: .semibold))
                        .foregroundStyle(t.ink)
                        .lineLimit(2)
                        .id(title)                     // clean swap, not flaps
                        .transition(.opacity)
                    if !byline.isEmpty {
                        Text(byline).font(.system(size: 12.5)).foregroundStyle(t.muted).lineLimit(2)
                    }
                    Text(spec)
                        .font(.system(size: 10.5, design: .monospaced))
                        .foregroundStyle(t.faint)
                }
                Spacer(minLength: 0)
            }
            .padding(.top, 10)
            .animation(.easeInOut(duration: 0.26), value: title)

            TransportRow(t: t, confirmSkip: $confirmSkip)
            if player.source != .radio { ScrubRow(t: t) }
        }
        .padding(14)
    }

    var title: String {
        switch player.status {
        case .idle: return "Tune in"
        case .offAir: return "OFF AIR"
        default: return player.now.title.isEmpty ? (player.current?.name ?? "—") : player.now.title
        }
    }
    var byline: String {
        let a = player.now.artist, al = player.now.album
        if a.isEmpty { return al }
        return al.isEmpty ? a : "\(a) · \(al)"
    }
    var spec: String {
        switch player.status {
        case .tuning: return "TUNING IN…"
        case .idle, .offAir: return " "
        default:
            let n = player.show?.tracks.count ?? 0
            switch player.source {
            case .radio: return "256 kbps · mp3 · live"
            case .tape: return "on demand · track \(player.trackIndex + 1)/\(n)"
            case .cd: return "cd · track \(player.trackIndex + 1)/\(n)"
            }
        }
    }

    @ViewBuilder var statusBadge: some View {
        switch player.source {
        case .radio where player.status == .playing:
            HStack(spacing: 6) {
                Circle().fill(t.red).frame(width: 7, height: 7).opacity(lampOn ? 1 : 0.25)
                    .onAppear {
                        withAnimation(.easeInOut(duration: 0.75).repeatForever()) { lampOn.toggle() }
                    }
                Text("ON AIR").font(.system(size: 10, weight: .bold)).tracking(2)
            }
            .foregroundStyle(t.red)
        case .tape:
            Text("TAPE").font(.system(size: 10, design: .monospaced)).foregroundStyle(t.faint)
        case .cd:
            Text("CD").font(.system(size: 10, design: .monospaced)).foregroundStyle(t.faint)
        default:
            EmptyView()
        }
    }
}

/// The receiver's input switch, compact: radio | tape, active side lit.
struct SourceSwitch: View {
    @EnvironmentObject var player: Player
    let t: Theme

    var body: some View {
        HStack(spacing: 0) {
            seg("dot.radiowaves.left.and.right", on: player.source == .radio,
                help: "the live broadcast — what everyone hears") {
                player.setSource(.radio)
            }
            seg("recordingtape", on: player.source != .radio,
                help: "your own copy of the show — scrub, jump, rewind") {
                player.setSource(.tape)
            }
        }
        .overlay(RoundedRectangle(cornerRadius: 3).stroke(t.line, lineWidth: 2))
        .clipShape(RoundedRectangle(cornerRadius: 3))
    }

    func seg(_ icon: String, on: Bool, help: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: 11, weight: .bold))
                .frame(width: 34, height: 26)
                .background(on ? t.accent : .clear)
                .foregroundStyle(on ? t.onAccent : t.muted)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(help)
    }
}

struct ArtTile: View {
    @EnvironmentObject var player: Player
    let t: Theme
    var size: CGFloat = 86

    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(hex: "#34353b"), Color(hex: "#161719")],
                           startPoint: .topLeading, endPoint: .bottomTrailing)
            if let url = artURL {
                AsyncImage(url: url) { img in
                    img.resizable().aspectRatio(contentMode: .fill)
                } placeholder: { monogram }
            } else { monogram }
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: 5))
        .shadow(color: .black.opacity(0.5), radius: 10, y: 6)
    }

    var artURL: URL? {
        if let b = player.browsed { return b.album.coverURL(base: player.stationBase) }
        if player.source == .cd {
            return player.currentAlbum?.coverURL(base: player.stationBase)
        }
        return player.current?.artURL(base: player.stationBase)
    }

    var monogram: some View {
        let seed = player.browsed?.album.album
            ?? (player.source == .cd ? (player.currentAlbum?.album ?? "♪")
                                     : (player.current?.name ?? "♪"))
        return Text(String(seed.prefix(1)))
            .font(.system(size: size * 0.37, weight: .ultraLight))
            .foregroundStyle(.white.opacity(0.94))
    }
}

// ── transport: square signage buttons, the yellow go ─────────────────────

struct TransportRow: View {
    @EnvironmentObject var player: Player
    let t: Theme
    @Binding var confirmSkip: Bool

    var body: some View {
        HStack(spacing: 9) {
            SquareButton(label: "◂◂", t: t, disabled: player.source == .radio) {
                player.prevTrack()
            }
            Button {
                player.toggle()
            } label: {
                Text(player.isPlaying ? "❚❚" : "▶")
                    .font(.system(size: 15, weight: .bold))
                    .frame(width: 46, height: 46)
                    .background(t.accent)
                    .foregroundStyle(t.onAccent)
                    .clipShape(RoundedRectangle(cornerRadius: 2))
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            SquareButton(label: "▸▸", t: t) {
                if player.source == .radio { confirmSkip = true } else { player.nextTrack() }
            }
            .confirmationDialog("Skip moves the station for everyone listening.",
                                isPresented: $confirmSkip, titleVisibility: .visible) {
                Button("Skip the show") { player.skipRadio() }
                Button("Stay with it", role: .cancel) {}
            }
            Button {
                player.toggleFavourite()
            } label: {
                Text("♥")
                    .font(.system(size: 15))
                    .frame(width: 40, height: 40)
                    .foregroundStyle(player.nowIsFavourite ? t.red : t.faint)
                    .overlay(RoundedRectangle(cornerRadius: 2)
                        .stroke(player.nowIsFavourite ? t.red : t.line, lineWidth: 2))
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(player.member == nil || player.now.url.isEmpty)
            .opacity(player.member == nil ? 0.3 : 1)
            .help(player.member == nil ? "sign in to keep favourites" : "favourite this track")
            SourceSwitch(t: t)
            Spacer()
            Image(systemName: "speaker.wave.2").font(.system(size: 11)).foregroundStyle(t.muted)
            VolumeSlider(t: t).frame(width: 84)
        }
        .padding(.top, 14)
    }
}

struct SquareButton: View {
    let label: String
    let t: Theme
    var disabled = false
    var small = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(label)
                .font(.system(size: small ? 11 : 13, weight: .heavy))
                .frame(width: small ? 30 : 40, height: small ? 30 : 40)
                .foregroundStyle(t.ink)
                .overlay(RoundedRectangle(cornerRadius: 2).stroke(t.line, lineWidth: 2))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .opacity(disabled ? 0.3 : 1)
    }
}

struct VolumeSlider: View {
    @EnvironmentObject var player: Player
    let t: Theme
    @State private var v: Float = 0.9

    var body: some View {
        Slider(value: Binding(
            get: { v },
            set: { v = $0; player.volume = $0 }
        ), in: 0...1)
        .controlSize(.mini)
        .tint(t.blue)
        .onAppear { v = player.volume }
    }
}

struct ScrubRow: View {
    @EnvironmentObject var player: Player
    let t: Theme

    var body: some View {
        HStack(spacing: 10) {
            Text(mmss(player.position)).font(.system(size: 11, design: .monospaced))
                .foregroundStyle(t.muted)
            Slider(value: Binding(
                get: { player.position },
                set: { player.position = $0 }
            ), in: 0...max(player.duration, 1)) { editing in
                player.isScrubbing = editing
                if !editing { player.seek(to: player.position) }
            }
            .controlSize(.small)
            .tint(t.blue)
            Text(mmss(player.duration)).font(.system(size: 11, design: .monospaced))
                .foregroundStyle(t.muted)
        }
        .padding(.top, 10)
    }

    func mmss(_ s: Double) -> String {
        let n = Int(s.isFinite ? max(s, 0) : 0)
        return String(format: "%d:%02d", n / 60, n % 60)
    }
}

// ── the tuner: departure rows ────────────────────────────────────────────

struct TunerList: View {
    @EnvironmentObject var player: Player
    let t: Theme
    /// MenuBarExtra windows collapse a ScrollView's maxHeight to 0, so the popover
    /// pins a fixed height; the main window passes nil and fills its pane.
    var fixedHeight: CGFloat? = 320
    /// Window: clicking an album BROWSES it (tracklist in the stage, nothing
    /// interrupted). Popover: clicking an album just plays it — quick-draw.
    var browseAlbums = false
    @State private var find = ""

    var channels: [Channel] {
        find.isEmpty ? player.channels
        : player.channels.filter { $0.name.localizedCaseInsensitiveContains(find) }
    }
    var albums: [Album] {
        find.isEmpty ? player.albums
        : player.albums.filter {
            $0.album.localizedCaseInsensitiveContains(find)
            || $0.artist.localizedCaseInsensitiveContains(find)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("TUNER").font(.system(size: 9, weight: .heavy)).tracking(2.2)
                    .foregroundStyle(t.faint)
                Spacer()
                TextField("find", text: $find)
                    .textFieldStyle(.plain)
                    .font(.system(size: 11))
                    .padding(.horizontal, 8).padding(.vertical, 4)
                    .frame(width: 110)
                    .background(t.sunk)
                    .overlay(RoundedRectangle(cornerRadius: 2).stroke(t.line, lineWidth: 1))
            }
            .padding(.horizontal, 14).padding(.top, 10).padding(.bottom, 6)
            ScrollView {
                VStack(spacing: 0) {
                    ForEach(channels) { ch in
                        ChannelRow(ch: ch, t: t)
                    }
                    if !albums.isEmpty {
                        Text("THE SHELF — CD")
                            .font(.system(size: 9, weight: .heavy)).tracking(1.8)
                            .foregroundStyle(t.accent)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 16).padding(.top, 12).padding(.bottom, 4)
                            .overlay(alignment: .top) { Rectangle().fill(t.line).frame(height: 1) }
                        ForEach(albums) { al in
                            AlbumRow(al: al, t: t, browse: browseAlbums)
                        }
                    }
                }
            }
            .frame(height: fixedHeight)
            .frame(maxHeight: fixedHeight == nil ? .infinity : nil)
        }
    }
}

struct ChannelRow: View {
    @EnvironmentObject var player: Player
    let ch: Channel
    let t: Theme
    @State private var hover = false

    var tuned: Bool { player.current?.slug == ch.slug }

    var body: some View {
        Button {
            player.tune(ch)
        } label: {
            HStack(spacing: 8) {
                Text(tuned ? "▸" : " ")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(t.accent)
                    .frame(width: 12)
                Text(ch.name)
                    .font(.system(size: 13, weight: tuned ? .heavy : .semibold, design: .monospaced))
                    .foregroundStyle(ch.playable ? t.ink : t.faint)
                if ch.isPrivate {
                    Text("PRIV").font(.system(size: 8, weight: .heavy)).tracking(1)
                        .padding(.horizontal, 4).padding(.vertical, 1)
                        .overlay(Rectangle().stroke(t.accent.opacity(0.75), lineWidth: 1))
                        .foregroundStyle(t.accent.opacity(0.75))
                }
                Spacer()
                if !ch.playable {
                    Text("NO MUSIC").font(.system(size: 9, weight: .heavy)).tracking(1.2)
                        .foregroundStyle(t.faint)
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background(tuned ? t.sunk : (hover ? t.sunk.opacity(0.6) : .clear))
            .overlay(alignment: .leading) {
                if tuned { Rectangle().fill(t.accent).frame(width: 3) }
            }
            .contentShape(Rectangle())   // whole row clickable, not just the glyphs
        }
        .buttonStyle(.plain)
        .disabled(!ch.playable)
        .onHover { hover = $0 }
    }
}

struct AlbumRow: View {
    @EnvironmentObject var player: Player
    let al: Album
    let t: Theme
    var browse = false
    @State private var hover = false

    var playing: Bool { player.source == .cd && player.currentAlbum?.dir == al.dir }
    var browsing: Bool { player.browsed?.album.dir == al.dir }

    var body: some View {
        Button {
            if browse { player.browseAlbum(al) } else { player.playAlbum(al) }
        } label: {
            HStack(spacing: 8) {
                Text(playing ? "▸" : "♫")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(t.accent)
                    .frame(width: 12)
                CoverTile(al: al, t: t, corner: 4)
                    .frame(width: 30, height: 30)
                VStack(alignment: .leading, spacing: 1) {
                    Text(al.album)
                        .font(.system(size: 12.5, weight: playing ? .heavy : .semibold))
                        .foregroundStyle(t.ink)
                        .lineLimit(1)
                    Text(al.artist + (al.year.map { " · \($0)" } ?? ""))
                        .font(.system(size: 10.5)).foregroundStyle(t.muted).lineLimit(1)
                }
                Spacer()
                Text("\(al.trackCount) TRK")
                    .font(.system(size: 8, weight: .heavy)).tracking(1)
                    .foregroundStyle(t.faint)
                    .padding(.horizontal, 4).padding(.vertical, 1)
                    .overlay(Rectangle().stroke(t.line, lineWidth: 1))
            }
            .padding(.horizontal, 12).padding(.vertical, 7)
            .background(playing || browsing ? t.sunk : (hover ? t.sunk.opacity(0.6) : .clear))
            .overlay(alignment: .leading) {
                if playing { Rectangle().fill(t.accent).frame(width: 3) }
                else if browsing { Rectangle().fill(t.blue).frame(width: 3) }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
    }
}

// ── footer + settings ────────────────────────────────────────────────────

struct FooterBar: View {
    let t: Theme
    @Binding var showSettings: Bool
    @Environment(\.openWindow) var openWindow

    var body: some View {
        HStack {
            Button {
                openWindow(id: "main")
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "macwindow").font(.system(size: 10))
                    Text("OPEN SESSION").font(.system(size: 9, weight: .heavy)).tracking(1)
                }
                .padding(.horizontal, 8).padding(.vertical, 6)
                .foregroundStyle(t.muted)
                .overlay(RoundedRectangle(cornerRadius: 2).stroke(t.line, lineWidth: 2))
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help("the full window — Dock icon and all")
            Spacer()
            Button {
                showSettings.toggle()
            } label: {
                Image(systemName: showSettings ? "xmark" : "gearshape")
                    .font(.system(size: 11))
                    .frame(width: 26, height: 26)
                    .foregroundStyle(t.muted)
                    .overlay(RoundedRectangle(cornerRadius: 2).stroke(t.line, lineWidth: 2))
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            Button {
                NSApp.terminate(nil)
            } label: {
                Image(systemName: "power")
                    .font(.system(size: 11))
                    .frame(width: 26, height: 26)
                    .foregroundStyle(t.muted)
                    .overlay(RoundedRectangle(cornerRadius: 2).stroke(t.line, lineWidth: 2))
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help("Quit Session")
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .overlay(alignment: .top) { Rectangle().fill(t.line).frame(height: 1) }
    }
}

/// Standalone settings (the window's sheet and the ⌘, Settings scene) —
/// same pane the popover shows inline.
struct SettingsSheet: View {
    @Environment(\.colorScheme) var scheme
    @Environment(\.dismiss) var dismiss
    @AppStorage("accent") var accentHex = "#FFD200"
    @AppStorage("theme") var themePref = "auto"

    var body: some View {
        // sheets and the ⌘, scene don't inherit the window's scheme — apply ours
        let effective: ColorScheme = themePref == "dark" ? .dark
                                   : themePref == "light" ? .light : scheme
        let t = Theme.current(effective, accentHex: accentHex)
        VStack(spacing: 0) {
            HStack {
                Text("SETTINGS").font(.system(size: 10, weight: .heavy)).tracking(2.2)
                    .foregroundStyle(t.onAccent)
                Spacer()
                Button { dismiss() } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 10, weight: .bold))
                        .frame(width: 24, height: 24)
                        .foregroundStyle(t.onAccent)
                        .overlay(RoundedRectangle(cornerRadius: 2).stroke(t.onAccent, lineWidth: 2))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background(t.accent)
            SettingsPane(t: t)
        }
        .frame(width: 400)
        .background(t.board)
        .preferredColorScheme(themePref == "dark" ? .dark : themePref == "light" ? .light : nil)
    }
}

struct SettingsPane: View {
    @EnvironmentObject var player: Player
    let t: Theme
    @AppStorage("accent") var accentHex = "#FFD200"
    @AppStorage("theme") var themePref = "auto"
    @AppStorage("dance") var dance = false
    @AppStorage("saver") var saverMode = "rotate"
    @State private var stationText = ""
    @State private var codeText = ""
    @State private var authError = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 6) {
                Text("MEMBERS").font(.system(size: 9, weight: .heavy)).tracking(2.2)
                    .foregroundStyle(t.faint)
                if let name = player.member {
                    HStack {
                        Text("signed in — \(name)")
                            .font(.system(size: 12)).foregroundStyle(t.ink)
                        Spacer()
                        Button {
                            Task { await player.signOut() }
                        } label: {
                            Text("SIGN OUT").font(.system(size: 10, weight: .heavy)).tracking(1)
                                .padding(.horizontal, 8).padding(.vertical, 5)
                                .foregroundStyle(t.muted)
                                .overlay(RoundedRectangle(cornerRadius: 2).stroke(t.line, lineWidth: 2))
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                } else {
                    HStack(spacing: 6) {
                        SecureField("passcode or passphrase", text: $codeText)
                            .textFieldStyle(.plain)
                            .font(.system(size: 12, design: .monospaced))
                            .padding(8)
                            .background(t.sunk)
                            .overlay(RoundedRectangle(cornerRadius: 2)
                                .stroke(authError ? t.red : t.line, lineWidth: 1))
                            .onSubmit { submitCode() }
                        Button {
                            submitCode()
                        } label: {
                            Text("ENTER").font(.system(size: 10, weight: .heavy)).tracking(1)
                                .padding(.horizontal, 10).padding(.vertical, 8)
                                .background(t.accent).foregroundStyle(t.onAccent)
                                .clipShape(RoundedRectangle(cornerRadius: 2))
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                    Text(authError ? "that code or passphrase isn't valid"
                                   : "unlocks the shelf (CD) and private channels")
                        .font(.system(size: 10))
                        .foregroundStyle(authError ? t.red : t.faint)
                }
            }
            VStack(alignment: .leading, spacing: 6) {
                Text("STATION").font(.system(size: 9, weight: .heavy)).tracking(2.2)
                    .foregroundStyle(t.faint)
                TextField("https://…", text: $stationText)
                    .textFieldStyle(.plain)
                    .font(.system(size: 12, design: .monospaced))
                    .padding(8)
                    .background(t.sunk)
                    .overlay(RoundedRectangle(cornerRadius: 2).stroke(t.line, lineWidth: 1))
                    .onSubmit {
                        if let url = URL(string: stationText), url.scheme != nil {
                            player.stationBase = url
                        }
                    }
                Text("the station Session is tuned to — presets come later")
                    .font(.system(size: 10)).foregroundStyle(t.faint)
            }
            VStack(alignment: .leading, spacing: 8) {
                Text("SIGNAGE COLOUR").font(.system(size: 9, weight: .heavy)).tracking(2.2)
                    .foregroundStyle(t.faint)
                HStack(spacing: 8) {
                    ForEach(ACCENTS, id: \.hex) { a in
                        Button {
                            accentHex = a.hex
                        } label: {
                            ZStack {
                                Circle().fill(Color(hex: a.hex)).frame(width: 22, height: 22)
                                if accentHex.uppercased() == a.hex.uppercased() {
                                    Text("✓").font(.system(size: 11, weight: .heavy))
                                        .foregroundStyle(Theme.luminance(a.hex) > 0.45
                                                         ? Color(hex: "#12120C") : .white)
                                }
                            }
                        }
                        .buttonStyle(.plain)
                        .help(a.name)
                    }
                }
            }
            VStack(alignment: .leading, spacing: 8) {
                Text("APPEARANCE").font(.system(size: 9, weight: .heavy)).tracking(2.2)
                    .foregroundStyle(t.faint)
                HStack(spacing: 6) {
                    ForEach(["auto", "dark", "light"], id: \.self) { m in
                        ChoiceChip(label: m.uppercased(), on: themePref == m, t: t) {
                            themePref = m
                        }
                    }
                    Spacer()
                    ChoiceChip(label: dance ? "♪ DANCING" : "LET IT DANCE", on: dance, t: t) {
                        dance.toggle()
                    }
                    .help("the signage colour sways while the music plays")
                }
            }
            VStack(alignment: .leading, spacing: 8) {
                Text("SCREENSAVER").font(.system(size: 9, weight: .heavy)).tracking(2.2)
                    .foregroundStyle(t.faint)
                HStack(spacing: 6) {
                    ForEach(["bars", "ring", "scope", "rotate"], id: \.self) { m in
                        ChoiceChip(label: m.uppercased(), on: saverMode == m, t: t) {
                            saverMode = m
                        }
                    }
                }
                Text("after 3 idle minutes in the window — or ▓ in its masthead, right now")
                    .font(.system(size: 10)).foregroundStyle(t.faint)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .onAppear { stationText = player.stationBase.absoluteString }
    }

    struct ChoiceChip: View {
        let label: String
        let on: Bool
        let t: Theme
        let action: () -> Void

        var body: some View {
            Button(action: action) {
                Text(label)
                    .font(.system(size: 9, weight: .heavy)).tracking(0.8)
                    .padding(.horizontal, 9).padding(.vertical, 6)
                    .foregroundStyle(on ? t.onAccent : t.muted)
                    .background(on ? t.accent : t.sunk)
                    .overlay(RoundedRectangle(cornerRadius: 2)
                        .stroke(on ? t.accent : t.line, lineWidth: 1))
                    .clipShape(RoundedRectangle(cornerRadius: 2))
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
    }

    func submitCode() {
        let code = codeText.trimmingCharacters(in: .whitespaces)
        guard !code.isEmpty else { return }
        Task {
            do {
                try await player.signIn(code: code)
                authError = false
                codeText = ""
            } catch {
                authError = true
            }
        }
    }
}
