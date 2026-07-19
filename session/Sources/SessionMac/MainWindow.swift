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
    @State var confirmSkip = false

    var t: Theme { Theme.current(scheme, accentHex: accentHex) }

    var body: some View {
        VStack(spacing: 0) {
            Masthead(t: t, confirmSkip: $confirmSkip)
            if let rip = player.rip, rip.ripping {
                RipBar(rip: rip, t: t)
            }
            HSplitView {
                TunerList(t: t, fixedHeight: nil)
                    .frame(minWidth: 220, idealWidth: 270, maxWidth: 380)
                    .background(t.panel)
                StagePane(t: t, confirmSkip: $confirmSkip)
                    .frame(minWidth: 480, maxWidth: .infinity)
            }
        }
        .background(t.board)
        .frame(minWidth: 760, minHeight: 540)
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

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            NowPlayingPane(t: t, confirmSkip: $confirmSkip)
            Divider().overlay(t.line)
            Tracklist(t: t)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(t.board)
    }
}

/// The set list — the schedule rows from the web's center pane.
/// Radio: read-only (✓ played · NOW · coming up). Tape/CD: click a row to jump.
struct Tracklist: View {
    @EnvironmentObject var player: Player
    let t: Theme

    var playingIndex: Int {
        player.source == .radio ? (player.show?.playing ?? -1) : player.trackIndex
    }

    var body: some View {
        if let sh = player.show, !sh.tracks.isEmpty {
            VStack(alignment: .leading, spacing: 0) {
                Text(sh.album.isEmpty ? "THE SET" : sh.album)
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(t.ink)
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

struct TrackRow: View {
    @EnvironmentObject var player: Player
    let index: Int
    let track: ShowTrack
    let playing: Int
    let t: Theme
    @State private var hover = false

    var isNow: Bool { index == playing }
    var isDone: Bool { index < playing }
    var clickable: Bool { player.source != .radio }

    var body: some View {
        Button {
            if clickable { player.jump(to: index) }
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
