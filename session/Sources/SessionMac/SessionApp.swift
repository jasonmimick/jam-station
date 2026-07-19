import SwiftUI
import SessionCore

@main
struct SessionApp: App {
    @StateObject private var player = Player()

    var body: some Scene {
        MenuBarExtra {
            PopoverView()
                .environmentObject(player)
        } label: {
            Image(systemName: player.isPlaying
                  ? "antenna.radiowaves.left.and.right"
                  : "antenna.radiowaves.left.and.right.slash")
        }
        .menuBarExtraStyle(.window)

        Window("Session", id: "main") {
            MainWindowView()
                .environmentObject(player)
        }
        .defaultSize(width: 1000, height: 660)
    }
}
