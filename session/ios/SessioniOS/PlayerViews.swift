import SwiftUI
import SessionCore

/// The floating pill above the tab bar.
struct MiniPlayer: View {
    @EnvironmentObject var player: Player
    let t: IOSTheme
    let open: () -> Void

    var body: some View {
        Button(action: open) {
            HStack(spacing: 10) {
                ZStack {
                    RoundedRectangle(cornerRadius: 8).fill(t.sunk)
                    Text(String((player.now.title.isEmpty
                                 ? (player.current?.name ?? "♪") : player.now.title).prefix(1)))
                        .font(.system(size: 16, weight: .light)).foregroundStyle(.white)
                }
                .frame(width: 40, height: 40)
                VStack(alignment: .leading, spacing: 1) {
                    Text(player.now.title.isEmpty ? (player.current?.name ?? "Tune in")
                                                  : player.now.title)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(t.ink).lineLimit(1)
                    Text(player.now.artist)
                        .font(.system(size: 11)).foregroundStyle(t.muted).lineLimit(1)
                }
                Spacer()
                Button {
                    player.toggle()
                } label: {
                    Text(player.isPlaying ? "❚❚" : "▶")
                        .font(.system(size: 14, weight: .bold))
                        .frame(width: 40, height: 40)
                        .background(Circle().fill(t.accent))
                        .foregroundStyle(t.onAccent)
                }
                .buttonStyle(.plain)
            }
            .padding(8)
            .background(RoundedRectangle(cornerRadius: 14).fill(t.panel)
                .shadow(color: .black.opacity(0.5), radius: 16, y: 8))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(t.line, lineWidth: 1))
            .padding(.horizontal, 10).padding(.bottom, 4)
        }
        .buttonStyle(.plain)
    }
}

/// The full player sheet — big art, transport, source button, tape scrubbing.
struct PlayerSheet: View {
    @EnvironmentObject var player: Player
    let t: IOSTheme
    @State private var confirmSkip = false

    var body: some View {
        VStack(spacing: 0) {
            if !chipText.isEmpty {
                Text(chipText)
                    .font(.system(size: 11, weight: .heavy)).tracking(1.5)
                    .padding(.horizontal, 14).padding(.vertical, 7)
                    .overlay(Capsule().stroke(t.line, lineWidth: 1))
                    .foregroundStyle(t.muted)
                    .padding(.top, 18)
            }
            ZStack {
                let seed = player.currentAlbum?.album ?? player.current?.name ?? "♪"
                let hue = Double(abs(seed.hashValue % 360)) / 360.0
                LinearGradient(
                    colors: [Color(hue: hue, saturation: 0.30, brightness: 0.36),
                             Color(hue: hue, saturation: 0.40, brightness: 0.12)],
                    startPoint: .topLeading, endPoint: .bottomTrailing)
                Text(String(seed.prefix(1)))
                    .font(.system(size: 64, weight: .ultraLight))
                    .foregroundStyle(.white.opacity(0.92))
                if let url = artURL {
                    NetImage(url: url)
                }
            }
            .frame(width: 260, height: 260)
            .clipShape(RoundedRectangle(cornerRadius: 16))
            .shadow(color: .black.opacity(0.5), radius: 26, y: 14)
            .padding(.top, 22)

            Text(player.now.title.isEmpty ? (player.current?.name ?? "Tune in")
                                          : player.now.title)
                .font(.system(size: 21, weight: .bold))
                .foregroundStyle(t.ink)
                .multilineTextAlignment(.center)
                .lineLimit(2)
                .padding(.top, 20).padding(.horizontal, 24)
            Text(byline)
                .font(.system(size: 13)).foregroundStyle(t.muted)
                .lineLimit(1).padding(.top, 3)
            specLine.padding(.top, 8)

            if player.source != .radio {
                HStack(spacing: 10) {
                    Text(mmss(player.position))
                        .font(.system(size: 11, design: .monospaced)).foregroundStyle(t.muted)
                    Slider(value: Binding(
                        get: { player.position },
                        set: { player.position = $0 }
                    ), in: 0...max(player.duration, 1)) { editing in
                        player.isScrubbing = editing
                        if !editing { player.seek(to: player.position) }
                    }
                    .tint(t.accent)
                    Text(mmss(player.duration))
                        .font(.system(size: 11, design: .monospaced)).foregroundStyle(t.muted)
                }
                .padding(.horizontal, 28).padding(.top, 14)
            }

            HStack(spacing: 34) {
                Button {
                    player.prevTrack()
                } label: { Text("⏮").font(.system(size: 26)) }
                    .disabled(player.source == .radio)
                    .opacity(player.source == .radio ? 0.28 : 1)
                Button {
                    player.toggle()
                } label: {
                    Text(player.isPlaying ? "❚❚" : "▶")
                        .font(.system(size: 24, weight: .bold))
                        .frame(width: 68, height: 68)
                        .background(Circle().fill(t.accent))
                        .foregroundStyle(t.onAccent)
                }
                Button {
                    if player.source == .radio { confirmSkip = true } else { player.nextTrack() }
                } label: { Text("⏭").font(.system(size: 26)) }
                Button {
                    player.toggleFavourite()
                } label: {
                    Text("♥").font(.system(size: 22))
                        .foregroundStyle(player.nowIsFavourite ? t.red : t.faint)
                }
                .disabled(player.member == nil || player.now.url.isEmpty)
            }
            .foregroundStyle(t.ink)
            .buttonStyle(.plain)
            .padding(.top, 22)
            .confirmationDialog("Skip moves the station for everyone listening.",
                                isPresented: $confirmSkip, titleVisibility: .visible) {
                Button("Skip the show") { player.skipRadio() }
                Button("Stay with it", role: .cancel) {}
            }

            Button {
                player.setSource(player.source == .radio ? .tape : .radio)
            } label: {
                HStack(spacing: 7) {
                    if player.source == .radio {
                        Image(systemName: "recordingtape")
                        Text("LISTEN TO THE TAPE")
                    } else {
                        Circle().fill(t.red).frame(width: 7, height: 7)
                        Text("BACK TO THE RADIO — LIVE")
                    }
                }
                .font(.system(size: 11, weight: .heavy)).tracking(1)
                .padding(.horizontal, 20).padding(.vertical, 11)
                .foregroundStyle(player.source == .radio ? t.ink : t.red)
                .overlay(Capsule().stroke(player.source == .radio ? t.line : t.red, lineWidth: 2))
            }
            .buttonStyle(.plain)
            .padding(.top, 20)

            if let sh = player.show, !sh.tracks.isEmpty {
                VStack(alignment: .leading, spacing: 0) {
                    Text(sh.album.isEmpty ? "THE SET" : sh.album.uppercased())
                        .font(.system(size: 9, weight: .heavy)).tracking(1.8)
                        .foregroundStyle(t.faint)
                        .padding(.horizontal, 4).padding(.bottom, 6)
                    ScrollView {
                        VStack(spacing: 0) {
                            ForEach(Array(sh.tracks.enumerated()), id: \.offset) { i, tr in
                                Button {
                                    if player.source != .radio { player.jump(to: i) }
                                } label: {
                                    HStack(spacing: 10) {
                                        Text(String(format: "%02d", i + 1))
                                            .font(.system(size: 11, design: .monospaced))
                                            .foregroundStyle(i == playingIndex ? t.accent : t.faint)
                                        Text(tr.title.isEmpty ? "Track \(i + 1)" : tr.title)
                                            .font(.system(size: 13,
                                                          weight: i == playingIndex ? .heavy : .medium))
                                            .foregroundStyle(i == playingIndex ? t.accent : t.ink)
                                            .lineLimit(1)
                                        Spacer()
                                        if i == playingIndex {
                                            Text("NOW").font(.system(size: 8, weight: .heavy)).tracking(1)
                                                .foregroundStyle(t.accent)
                                        }
                                    }
                                    .padding(.vertical, 7).padding(.horizontal, 6)
                                    .background(i == playingIndex ? t.sunk : .clear)
                                    .clipShape(RoundedRectangle(cornerRadius: 6))
                                    .contentShape(Rectangle())
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                    .frame(maxHeight: 190)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 18).padding(.horizontal, 12)
            }

            Spacer(minLength: 10)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(t.board)
    }

    var playingIndex: Int {
        player.source == .radio ? (player.show?.playing ?? -1) : player.trackIndex
    }

    /// What Session is playing FROM — the channel on radio/tape, the record on CD.
    var chipText: String {
        switch player.source {
        case .cd: return "💿 " + (player.currentAlbum?.album ?? player.now.album).uppercased()
        case .tape:
            if player.show?.channel == "favourites" { return "♥ FAVOURITES" }
            return "◉ " + (player.current?.name ?? "").uppercased()
        case .radio: return "◉ " + (player.current?.name ?? "").uppercased()
        }
    }

    var artURL: URL? {
        if player.source == .cd { return player.currentAlbum?.coverURL(base: player.stationBase) }
        return player.current?.artURL(base: player.stationBase)
    }

    var byline: String {
        let a = player.now.artist, al = player.now.album
        if a.isEmpty { return al }
        return al.isEmpty ? a : "\(a) · \(al)"
    }

    @ViewBuilder var specLine: some View {
        switch player.status {
        case .tuning:
            Text("TUNING IN…").font(.system(size: 10, weight: .heavy)).tracking(2)
                .foregroundStyle(t.muted)
        case .playing where player.source == .radio:
            HStack(spacing: 6) {
                Circle().fill(t.red).frame(width: 7, height: 7)
                Text("ON AIR · 256 KBPS · LIVE")
                    .font(.system(size: 10, weight: .heavy)).tracking(2)
            }
            .foregroundStyle(t.red)
        case .playing, .paused:
            let n = player.show?.tracks.count ?? 0
            Text(player.source == .cd ? "CD · TRACK \(player.trackIndex + 1)/\(n)"
                                      : "ON DEMAND · TRACK \(player.trackIndex + 1)/\(n)")
                .font(.system(size: 10, weight: .heavy)).tracking(2)
                .foregroundStyle(t.muted)
        default:
            Text(" ").font(.system(size: 10))
        }
    }

    func mmss(_ s: Double) -> String {
        let n = Int(s.isFinite ? max(s, 0) : 0)
        return String(format: "%d:%02d", n / 60, n % 60)
    }
}
