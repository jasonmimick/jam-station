import SwiftUI
import AppKit

/// The station's design system, verbatim from brain/app/static/index.html.
/// Session invents no look of its own (docs/DESIGN-session-p0.md).
struct Theme {
    let board: Color, panel: Color, sunk: Color, line: Color
    let ink: Color, muted: Color, faint: Color
    let accent: Color, onAccent: Color
    let blue: Color, red: Color, live: Color

    static func current(_ scheme: ColorScheme, accentHex: String, dance: Double? = nil) -> Theme {
        // dance: sway the signage hue ±26° with the clock; the on-colour rule still holds
        let hex = dance.map { Theme.hueShifted(accentHex, by: sin($0) * 26) } ?? accentHex
        let accent = Color(hex: hex)
        let onAccent = Theme.luminance(hex) > 0.45 ? Color(hex: "#12120C") : .white
        if scheme == .light {
            return Theme(
                board: Color(hex: "#FFFFFF"), panel: Color(hex: "#F4F4F4"),
                sunk: Color(hex: "#ECECEE"), line: Color(hex: "#12120C").opacity(0.2),
                ink: Color(hex: "#12120C"), muted: Color(hex: "#5B5B62"), faint: Color(hex: "#8E8E96"),
                accent: accent, onAccent: onAccent,
                blue: Color(hex: "#0B4FD0"), red: Color(hex: "#D62818"), live: Color(hex: "#0E7A44"))
        }
        return Theme(
            board: Color(hex: "#0F0F11"), panel: Color(hex: "#17171A"),
            sunk: Color(hex: "#0A0A0C"), line: Color(hex: "#2B2B31"),
            ink: .white, muted: Color(hex: "#8C8C94"), faint: Color(hex: "#5A5A62"),
            accent: accent, onAccent: onAccent,
            blue: Color(hex: "#3B82F6"), red: Color(hex: "#F0402F"), live: Color(hex: "#2FD16A"))
    }

    /// The web's exact rule: relative luminance decides the text that rides the accent.
    static func luminance(_ hex: String) -> Double {
        let v = rgb(hex).map { c -> Double in
            c <= 0.03928 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]
    }

    static func hueShifted(_ hex: String, by degrees: Double) -> String {
        let c = rgb(hex)
        let ns = NSColor(calibratedRed: c[0], green: c[1], blue: c[2], alpha: 1)
        var h: CGFloat = 0, s: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        ns.getHue(&h, saturation: &s, brightness: &b, alpha: &a)
        h = (h + degrees / 360).truncatingRemainder(dividingBy: 1)
        if h < 0 { h += 1 }
        let out = NSColor(calibratedHue: h, saturation: s, brightness: b, alpha: 1)
        return String(format: "#%02X%02X%02X",
                      Int(out.redComponent * 255), Int(out.greenComponent * 255),
                      Int(out.blueComponent * 255))
    }

    static func rgb(_ hex: String) -> [Double] {
        var s = hex.trimmingCharacters(in: .whitespaces)
        if s.hasPrefix("#") { s.removeFirst() }
        guard s.count == 6, let n = UInt64(s, radix: 16) else { return [1, 0.82, 0] }
        return [Double((n >> 16) & 0xFF) / 255, Double((n >> 8) & 0xFF) / 255, Double(n & 0xFF) / 255]
    }
}

/// The web's curated signage palette, verbatim.
let ACCENTS: [(name: String, hex: String)] = [
    ("Amber", "#FFD200"), ("Sodium", "#FF8C1A"), ("Crimson", "#FF3B3B"), ("Magenta", "#FF4FA3"),
    ("Teal", "#12D6B6"), ("Cyan", "#38BDF8"), ("Lime", "#86E01E"), ("Violet", "#A98BFF"),
]

extension Color {
    init(hex: String) {
        let c = Theme.rgb(hex)
        self.init(.sRGB, red: c[0], green: c[1], blue: c[2])
    }
}
