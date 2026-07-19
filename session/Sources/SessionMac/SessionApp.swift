import SwiftUI
import SessionCore

@main
struct SessionApp: App {
    @StateObject private var player = Player()

    var body: some Scene {
        // Window scene FIRST: launching the app (Finder, Dock) opens the desktop
        // window; the popover belongs to the menu-bar antenna alone.
        Window("Session", id: "main") {
            MainWindowView()
                .environmentObject(player)
        }
        .defaultSize(width: 1000, height: 660)
        .windowResizability(.contentMinSize)   // let the green button actually zoom
        .commands {
            CommandGroup(after: .sidebar) {
                Button("Zoom In") { bumpZoom(+0.1) }.keyboardShortcut("=", modifiers: .command)
                Button("Zoom Out") { bumpZoom(-0.1) }.keyboardShortcut("-", modifiers: .command)
                Button("Actual Size") {
                    UserDefaults.standard.set(1.0, forKey: "zoom")
                }.keyboardShortcut("0", modifiers: .command)
            }
        }

        MenuBarExtra {
            PopoverView()
                .environmentObject(player)
        } label: {
            Image(systemName: player.isPlaying
                  ? "antenna.radiowaves.left.and.right"
                  : "antenna.radiowaves.left.and.right.slash")
        }
        .menuBarExtraStyle(.window)

        Settings {                       // the standard ⌘, door to the same pane
            SettingsSheet()
                .environmentObject(player)
        }
    }

    private func bumpZoom(_ d: Double) {
        let z = UserDefaults.standard.object(forKey: "zoom") as? Double ?? 1.0
        UserDefaults.standard.set(min(1.6, max(0.8, z + d)), forKey: "zoom")
    }
}
