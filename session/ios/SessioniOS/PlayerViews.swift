import SwiftUI
import AVKit
import SessionCore

func tapHaptic() {
    UIImpactFeedbackGenerator(style: .light).impactOccurred()
}

/// The system AirPlay route picker — send the station to speakers, HomePods, the TV.
struct AirPlayButton: UIViewRepresentable {
    let tint: UIColor

    func makeUIView(context: Context) -> AVRoutePickerView {
        let v = AVRoutePickerView()
        v.tintColor = tint
        v.activeTintColor = tint
        v.prioritizesVideoDevices = false
        return v
    }

    func updateUIView(_ v: AVRoutePickerView, context: Context) {
        v.tintColor = tint
    }
}

/// The floating pill above the tab bar.
struct MiniPlayer: View {
    @EnvironmentObject var player: Player
    let t: IOSTheme
    var bare = false           // true inside tabViewBottomAccessory (system draws the chrome)
    let open: () -> Void

    var body: some View {
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
        .padding(bare ? 6 : 8)
        .background(bare ? AnyView(Color.clear)
            : AnyView(RoundedRectangle(cornerRadius: 14).fill(t.panel)
                .shadow(color: .black.opacity(0.5), radius: 16, y: 8)))
        .overlay(bare ? nil : RoundedRectangle(cornerRadius: 14).stroke(t.line, lineWidth: 1))
        .padding(.horizontal, bare ? 4 : 10)
        .padding(.bottom, bare ? 0 : 4)
        // a plain tap gesture, not a Button: the tab-bar accessory swallowed
        // the outer Button's tap, so the pill couldn't reopen the player
        .contentShape(Rectangle())
        .onTapGesture { open() }
    }
}

/// The full player — a pure SwiftUI overlay panel (the web's #now, native).
/// No UIKit presentation: the grab handle and a downward drag close it.
struct PlayerSheet: View {
    @EnvironmentObject var player: Player
    let t: IOSTheme
    let close: () -> Void
    @AppStorage("saver") var saverMode = "rotate"
    @State private var confirmSkip = false
    @State private var showSaver = false
    @State private var dragY: CGFloat = 0

    var body: some View {
        VStack(spacing: 0) {
            VStack(spacing: 10) {
                Capsule().fill(t.line).frame(width: 40, height: 5)
                    .padding(.top, 12)
                HStack {
                    Spacer()
                    if !chipText.isEmpty {
                        Text(chipText)
                            .font(.system(size: 11, weight: .heavy)).tracking(1.5)
                            .padding(.horizontal, 14).padding(.vertical, 7)
                            .overlay(Capsule().stroke(t.line, lineWidth: 1))
                            .foregroundStyle(t.muted)
                    }
                    Spacer()
                    Button {
                        showSaver = true
                    } label: {
                        Text("▓").font(.system(size: 13, weight: .bold))
                            .frame(width: 32, height: 32)
                            .foregroundStyle(t.muted)
                            .overlay(Circle().stroke(t.line, lineWidth: 1))
                    }
                    .buttonStyle(.plain)
                }
                .padding(.horizontal, 18)
            }
            .contentShape(Rectangle())
            .onTapGesture { close() }
            .gesture(
                DragGesture()
                    .onChanged { v in
                        if v.translation.height > 0 { dragY = v.translation.height }
                    }
                    .onEnded { v in
                        if v.translation.height > 110 { close() }
                        dragY = 0
                    }
            )
            .fullScreenCover(isPresented: $showSaver) {
                SaverView(t: t, mode: saverMode) { showSaver = false }
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
                    tapHaptic()
                    player.stepBack()      // radio: step back in time onto the tape
                } label: { Text("⏮").font(.system(size: 26)) }
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
                    tapHaptic()
                    if player.source == .radio { confirmSkip = true } else { player.stepForward() }
                } label: { Text("⏭").font(.system(size: 26)) }
                Button {
                    tapHaptic()
                    player.toggleFavourite()
                } label: {
                    Text("♥").font(.system(size: 22))
                        .foregroundStyle(player.nowIsFavourite ? t.red : t.faint)
                }
                .disabled(player.member == nil || player.now.url.isEmpty)
                AirPlayButton(tint: UIColor(t.ink))
                    .frame(width: 30, height: 30)
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
                tapHaptic()
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
        .background(t.board.ignoresSafeArea())
        .offset(y: max(dragY, 0))
        .animation(.interactiveSpring, value: dragY)
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
            if player.show?.channel == "mix" { return "🎛 " + (player.show?.album ?? "MIX").uppercased() }
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

/// The screensaver, phone edition — Bars · Ring · Scope, keeps the display awake.
struct SaverView: View {
    @EnvironmentObject var player: Player
    let t: IOSTheme
    let mode: String
    let dismiss: () -> Void

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            Color.black.ignoresSafeArea()
            TimelineView(.animation) { tl in
                let time = tl.date.timeIntervalSinceReferenceDate
                let shown = mode == "rotate" ? ["bars", "ring", "scope"][Int(time / 30) % 3] : mode
                Canvas { ctx, size in
                    switch shown {
                    case "ring": ring(ctx, size, time)
                    case "scope": scope(ctx, size, time)
                    default: bars(ctx, size, time)
                    }
                }
                .ignoresSafeArea()
            }
            VStack(alignment: .leading, spacing: 4) {
                if !player.now.title.isEmpty {
                    Text(player.now.title)
                        .font(.system(size: 26, weight: .semibold))
                        .foregroundStyle(Color(hexStr: "#F2F2EE"))
                        .shadow(color: t.accent.opacity(0.55), radius: 24)
                    Text(player.now.artist)
                        .font(.system(size: 14))
                        .foregroundStyle(Color(hexStr: "#F2F2EE").opacity(0.7))
                }
                if let ch = player.current, player.source == .radio {
                    Text("ON AIR · \(ch.name.uppercased())")
                        .font(.system(size: 10, weight: .heavy)).tracking(2)
                        .foregroundStyle(t.accent)
                        .padding(.top, 5)
                }
            }
            .padding(28)
        }
        .contentShape(Rectangle())
        .onTapGesture { dismiss() }
        .statusBarHidden()
        .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
        .onDisappear { UIApplication.shared.isIdleTimerDisabled = false }
    }

    private func level(_ i: Int, _ time: Double) -> Double {
        let x = Double(i)
        let v = sin(time * 2.1 + x * 0.55) + sin(time * 3.3 + x * 1.31)
              + 0.5 * sin(time * 5.7 + x * 2.17)
        return min(1, max(0.06, abs(v) / 2.5))
    }

    private func bars(_ ctx: GraphicsContext, _ size: CGSize, _ time: Double) {
        let n = 40
        let gap: CGFloat = 4
        let w = (size.width - gap * CGFloat(n - 1)) / CGFloat(n)
        for i in 0..<n {
            let h = size.height * 0.55 * level(i, time)
            let rect = CGRect(x: CGFloat(i) * (w + gap),
                              y: (size.height - h) / 2, width: w, height: h)
            ctx.fill(Path(roundedRect: rect, cornerRadius: 1),
                     with: .color(t.accent.opacity(0.35 + 0.65 * level(i, time))))
        }
    }

    private func ring(_ ctx: GraphicsContext, _ size: CGSize, _ time: Double) {
        let c = CGPoint(x: size.width / 2, y: size.height / 2)
        let base = min(size.width, size.height) * 0.2
        let n = 80
        for i in 0..<n {
            let a = Double(i) / Double(n) * 2 * .pi + time * 0.15
            let amp = base * (0.35 + 0.9 * level(i, time))
            var p = Path()
            p.move(to: CGPoint(x: c.x + cos(a) * base, y: c.y + sin(a) * base))
            p.addLine(to: CGPoint(x: c.x + cos(a) * (base + amp),
                                  y: c.y + sin(a) * (base + amp)))
            ctx.stroke(p, with: .color(t.accent.opacity(0.3 + 0.7 * level(i, time))),
                       lineWidth: 2.5)
        }
    }

    private func scope(_ ctx: GraphicsContext, _ size: CGSize, _ time: Double) {
        var p = Path()
        let mid = size.height / 2
        let steps = 200
        for s in 0...steps {
            let x = size.width * CGFloat(s) / CGFloat(steps)
            let ph = Double(s) / 16.0
            let y = mid + CGFloat((sin(time * 2.4 + ph) + 0.6 * sin(time * 4.1 + ph * 1.7))
                                  * Double(size.height) * 0.14)
            if s == 0 { p.move(to: CGPoint(x: x, y: y)) }
            else { p.addLine(to: CGPoint(x: x, y: y)) }
        }
        ctx.stroke(p, with: .color(t.accent), lineWidth: 2)
        var glow = ctx
        glow.addFilter(.blur(radius: 6))
        glow.stroke(p, with: .color(t.accent.opacity(0.5)), lineWidth: 4)
    }
}
