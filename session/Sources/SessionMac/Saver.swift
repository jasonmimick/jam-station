import SwiftUI
import SessionCore

/// The screensaver — Bars · Ring · Scope (or Rotate), the web's ▓ overlay gone native.
/// Levels are a smooth pseudo-signal for now; a real audio tap can drive them later.
struct SaverOverlay: View {
    @EnvironmentObject var player: Player
    let t: Theme
    let mode: String            // bars | ring | scope | rotate
    let dismiss: () -> Void

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            Color.black.ignoresSafeArea()
            TimelineView(.animation) { tl in
                let time = tl.date.timeIntervalSinceReferenceDate
                let shown = mode == "rotate"
                    ? ["bars", "ring", "scope"][Int(time / 30) % 3] : mode
                Canvas { ctx, size in
                    switch shown {
                    case "ring": ring(ctx, size, time)
                    case "scope": scope(ctx, size, time)
                    default: bars(ctx, size, time)
                    }
                }
            }
            VStack(alignment: .leading, spacing: 4) {
                if !player.now.title.isEmpty {
                    Text(player.now.title)
                        .font(.system(size: 34, weight: .semibold))
                        .foregroundStyle(Color(hex: "#F2F2EE"))
                        .shadow(color: t.accent.opacity(0.55), radius: 30)
                    Text(player.now.artist)
                        .font(.system(size: 16))
                        .foregroundStyle(Color(hex: "#F2F2EE").opacity(0.7))
                }
                if let ch = player.current, player.source == .radio {
                    Text("ON AIR · \(ch.name.uppercased())")
                        .font(.system(size: 11, weight: .heavy)).tracking(2)
                        .foregroundStyle(t.accent)
                        .padding(.top, 6)
                }
            }
            .padding(36)
        }
        .contentShape(Rectangle())
        .onTapGesture { dismiss() }
    }

    // one smooth pseudo-signal shared by all three faces
    private func level(_ i: Int, _ time: Double) -> Double {
        let x = Double(i)
        let v = sin(time * 2.1 + x * 0.55) + sin(time * 3.3 + x * 1.31)
              + 0.5 * sin(time * 5.7 + x * 2.17)
        return min(1, max(0.06, abs(v) / 2.5))
    }

    private func bars(_ ctx: GraphicsContext, _ size: CGSize, _ time: Double) {
        let n = 48
        let gap: CGFloat = 4
        let w = (size.width - gap * CGFloat(n - 1)) / CGFloat(n)
        for i in 0..<n {
            let h = size.height * 0.62 * level(i, time)
            let rect = CGRect(x: CGFloat(i) * (w + gap),
                              y: (size.height - h) / 2, width: w, height: h)
            ctx.fill(Path(roundedRect: rect, cornerRadius: 1),
                     with: .color(t.accent.opacity(0.35 + 0.65 * level(i, time))))
        }
    }

    private func ring(_ ctx: GraphicsContext, _ size: CGSize, _ time: Double) {
        let c = CGPoint(x: size.width / 2, y: size.height / 2)
        let base = min(size.width, size.height) * 0.22
        let n = 90
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
        let steps = 240
        for s in 0...steps {
            let x = size.width * CGFloat(s) / CGFloat(steps)
            let ph = Double(s) / 18.0
            let y = mid + CGFloat((sin(time * 2.4 + ph) + 0.6 * sin(time * 4.1 + ph * 1.7))
                                  * Double(size.height) * 0.16)
            if s == 0 { p.move(to: CGPoint(x: x, y: y)) }
            else { p.addLine(to: CGPoint(x: x, y: y)) }
        }
        ctx.stroke(p, with: .color(t.accent), lineWidth: 2)
        var glow = ctx
        glow.addFilter(.blur(radius: 6))
        glow.stroke(p, with: .color(t.accent.opacity(0.5)), lineWidth: 4)
    }
}
