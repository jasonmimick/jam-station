import SwiftUI
import AVFoundation
import SessionCore

@main
struct SessionIOSApp: App {
    @StateObject private var player = Player()

    init() {
        // Background audio: the entire reason the native app exists.
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .default)
        try? AVAudioSession.sharedInstance().setActive(true)
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(player)
        }
    }
}

/// iOS theme — the station's tokens, mobile.html's softer expression.
struct IOSTheme {
    let board: Color, panel: Color, sunk: Color, line: Color
    let ink: Color, muted: Color, faint: Color
    let accent: Color, onAccent: Color
    let red: Color, live: Color

    static func current(_ scheme: ColorScheme, accentHex: String, dance: Double? = nil) -> IOSTheme {
        let hex = dance.map { hueShifted(accentHex, by: sin($0) * 26) } ?? accentHex
        let accent = Color(hexStr: hex)
        let onAccent = luminance(hex) > 0.45 ? Color(hexStr: "#12120C") : .white
        if scheme == .light {
            return IOSTheme(
                board: .white, panel: Color(hexStr: "#F4F4F4"),
                sunk: Color(hexStr: "#ECECEE"), line: Color(hexStr: "#12120C").opacity(0.2),
                ink: Color(hexStr: "#12120C"), muted: Color(hexStr: "#5B5B62"),
                faint: Color(hexStr: "#8E8E96"),
                accent: accent, onAccent: onAccent,
                red: Color(hexStr: "#D62818"), live: Color(hexStr: "#0E7A44"))
        }
        return IOSTheme(
            board: Color(hexStr: "#0F0F11"), panel: Color(hexStr: "#17171A"),
            sunk: Color(hexStr: "#0A0A0C"), line: Color(hexStr: "#2B2B31"),
            ink: .white, muted: Color(hexStr: "#8C8C94"), faint: Color(hexStr: "#5A5A62"),
            accent: accent, onAccent: onAccent,
            red: Color(hexStr: "#F0402F"), live: Color(hexStr: "#2FD16A"))
    }

    static func hueShifted(_ hex: String, by degrees: Double) -> String {
        let c = rgb(hex)
        var h: CGFloat = 0, s: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        UIColor(red: c[0], green: c[1], blue: c[2], alpha: 1)
            .getHue(&h, saturation: &s, brightness: &b, alpha: &a)
        h = (h + degrees / 360).truncatingRemainder(dividingBy: 1)
        if h < 0 { h += 1 }
        let out = UIColor(hue: h, saturation: s, brightness: b, alpha: 1)
        var r2: CGFloat = 0, g2: CGFloat = 0, b2: CGFloat = 0
        out.getRed(&r2, green: &g2, blue: &b2, alpha: &a)
        return String(format: "#%02X%02X%02X", Int(r2 * 255), Int(g2 * 255), Int(b2 * 255))
    }

    static func luminance(_ hex: String) -> Double {
        let v = rgb(hex).map { c -> Double in
            c <= 0.03928 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]
    }

    static func rgb(_ hex: String) -> [Double] {
        var s = hex.trimmingCharacters(in: .whitespaces)
        if s.hasPrefix("#") { s.removeFirst() }
        guard s.count == 6, let n = UInt64(s, radix: 16) else { return [1, 0.82, 0] }
        return [Double((n >> 16) & 0xFF) / 255, Double((n >> 8) & 0xFF) / 255,
                Double(n & 0xFF) / 255]
    }
}

extension Color {
    init(hexStr: String) {
        let c = IOSTheme.rgb(hexStr)
        self.init(.sRGB, red: c[0], green: c[1], blue: c[2])
    }
}

let IOS_ACCENTS: [(name: String, hex: String)] = [
    ("Amber", "#FFD200"), ("Sodium", "#FF8C1A"), ("Crimson", "#FF3B3B"), ("Magenta", "#FF4FA3"),
    ("Teal", "#12D6B6"), ("Cyan", "#38BDF8"), ("Lime", "#86E01E"), ("Violet", "#A98BFF"),
]
