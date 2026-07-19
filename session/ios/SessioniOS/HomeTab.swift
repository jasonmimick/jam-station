import SwiftUI
import SessionCore

/// The front door: what's happening at the station right now — not a wall of
/// choices. One-tap back into the music, the rip moment, what's fresh.
struct HomeTab: View {
    @EnvironmentObject var player: Player
    let t: IOSTheme
    let openPlayer: () -> Void
    let goTuner: () -> Void
    @State private var heroNP = NowPlaying.empty

    var freshAlbums: [Album] {
        Array(player.albums.sorted { $0.mtime > $1.mtime }.prefix(10))
    }

    var body: some View {
        VStack(spacing: 0) {
            SignageHeader(t: t)
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    hero
                    if let rip = player.rip, rip.ripping {
                        ripBand(rip)
                    }
                    if !freshAlbums.isEmpty { freshRow }
                    if !player.history.isEmpty { latelyRows }
                }
                .padding(.horizontal, 14).padding(.bottom, 24)
            }
            .refreshable {
                await player.refreshChannels()
                await player.refreshHistory()
                await player.refreshMembership()
            }
        }
        .background(t.board)
        .task {
            await player.refreshHistory()
            if let ch = player.current, !player.isPlaying {
                heroNP = (try? await player.api.nowPlaying(channel: ch.slug)) ?? .empty
            }
        }
    }

    // ── the on-air hero: your channel, one tap from sound ────────────────

    var hero: some View {
        Button {
            tapHaptic()
            if player.isPlaying {
                openPlayer()
            } else if player.status == .paused {
                player.toggle()
                openPlayer()
            } else if let ch = player.current {
                player.tune(ch)
                openPlayer()
            }
        } label: {
            ZStack(alignment: .bottomLeading) {
                ZStack {
                    let seed = player.current?.name ?? "♪"
                    let hue = Double(abs(seed.hashValue % 360)) / 360.0
                    LinearGradient(
                        colors: [Color(hue: hue, saturation: 0.32, brightness: 0.4),
                                 Color(hue: hue, saturation: 0.42, brightness: 0.1)],
                        startPoint: .topLeading, endPoint: .bottomTrailing)
                    if let url = player.current?.artURL(base: player.stationBase) {
                        NetImage(url: url)
                    }
                    LinearGradient(colors: [.clear, .black.opacity(0.75)],
                                   startPoint: .center, endPoint: .bottom)
                }
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        if player.isPlaying && player.source == .radio {
                            Circle().fill(t.red).frame(width: 7, height: 7)
                            Text("ON AIR").font(.system(size: 9, weight: .heavy)).tracking(1.8)
                                .foregroundStyle(t.red)
                        } else {
                            Text("YOUR STATION").font(.system(size: 9, weight: .heavy)).tracking(1.8)
                                .foregroundStyle(.white.opacity(0.65))
                        }
                    }
                    Text(player.current?.name ?? "Pick a channel")
                        .font(.system(size: 24, weight: .bold))
                        .foregroundStyle(.white)
                    Text(heroLine)
                        .font(.system(size: 13))
                        .foregroundStyle(.white.opacity(0.8))
                        .lineLimit(1)
                }
                .padding(16)
                HStack {
                    Spacer()
                    Text(player.isPlaying ? "❚❚" : "▶")
                        .font(.system(size: 18, weight: .bold))
                        .frame(width: 54, height: 54)
                        .background(Circle().fill(t.accent))
                        .foregroundStyle(t.onAccent)
                        .padding(14)
                }
                .frame(maxHeight: .infinity, alignment: .bottom)
            }
            .frame(height: 200)
            .clipShape(RoundedRectangle(cornerRadius: 16))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    var heroLine: String {
        let np = player.isPlaying ? player.now : heroNP
        if np.isEmpty { return "tap to tune in" }
        return np.title + (np.artist.isEmpty ? "" : " — \(np.artist)")
    }

    // ── the rip moment ───────────────────────────────────────────────────

    func ripBand(_ rip: RipStatus) -> some View {
        HStack(spacing: 8) {
            Circle().fill(t.red).frame(width: 7, height: 7)
            Text("NOW RIPPING · \(rip.album) · \(rip.track)/\(rip.total)")
                .font(.system(size: 11, weight: .bold)).lineLimit(1)
            Spacer()
        }
        .padding(.horizontal, 12).padding(.vertical, 9)
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
    }

    // ── fresh on the shelf ───────────────────────────────────────────────

    var freshRow: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("FRESH ON THE SHELF")
                .font(.system(size: 10, weight: .heavy)).tracking(1.8)
                .foregroundStyle(t.accent)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 12) {
                    ForEach(freshAlbums) { al in
                        Button {
                            tapHaptic()
                            player.playAlbum(al)
                            openPlayer()
                        } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                ZStack {
                                    let hue = Double(abs(al.album.hashValue % 360)) / 360.0
                                    LinearGradient(
                                        colors: [Color(hue: hue, saturation: 0.3, brightness: 0.34),
                                                 Color(hue: hue, saturation: 0.38, brightness: 0.12)],
                                        startPoint: .topLeading, endPoint: .bottomTrailing)
                                    Text(String(al.album.prefix(1)))
                                        .font(.system(size: 24, weight: .ultraLight))
                                        .foregroundStyle(.white.opacity(0.92))
                                    if let url = al.coverURL(base: player.stationBase) {
                                        NetImage(url: url)
                                    }
                                }
                                .frame(width: 108, height: 108)
                                .clipShape(RoundedRectangle(cornerRadius: 10))
                                Text(al.album)
                                    .font(.system(size: 11.5, weight: .semibold))
                                    .foregroundStyle(t.ink).lineLimit(1)
                                    .frame(width: 108, alignment: .leading)
                            }
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }

    // ── on the station lately ────────────────────────────────────────────

    var latelyRows: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("ON THE STATION LATELY")
                    .font(.system(size: 10, weight: .heavy)).tracking(1.8)
                    .foregroundStyle(t.accent)
                Spacer()
                Button {
                    goTuner()
                } label: {
                    Text("THE DIAL →").font(.system(size: 10, weight: .heavy)).tracking(1)
                        .foregroundStyle(t.muted)
                }
                .buttonStyle(.plain)
            }
            .padding(.bottom, 6)
            ForEach(player.history.prefix(6)) { h in
                HStack(spacing: 9) {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(h.title.isEmpty ? h.album : h.title)
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(t.ink).lineLimit(1)
                        Text("\(h.channel) · \(h.artist)")
                            .font(.system(size: 10.5)).foregroundStyle(t.muted).lineLimit(1)
                    }
                    Spacer()
                    Text(h.when)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(t.faint)
                }
                .padding(.vertical, 6)
                .overlay(alignment: .bottom) { Rectangle().fill(t.line).frame(height: 1) }
            }
        }
    }
}
