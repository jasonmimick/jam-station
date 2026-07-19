import SwiftUI
import PhotosUI
import SessionCore

/// Spot a song: pick a photo of music in the wild, the station's vision call
/// identifies it, and it lands matched / wishlist / unknown. Photo library for
/// now (works in the simulator); direct camera capture is a later polish.
struct SpotButton: View {
    @EnvironmentObject var player: Player
    let t: IOSTheme
    @State private var pick: PhotosPickerItem?
    @State private var busy = false
    @State private var result: SpotResult?
    @State private var failed = false

    var body: some View {
        PhotosPicker(selection: $pick, matching: .images) {
            HStack(spacing: 11) {
                Text("📷").font(.system(size: 20))
                VStack(alignment: .leading, spacing: 1) {
                    Text("Spot a song").font(.system(size: 13, weight: .bold))
                        .foregroundStyle(t.ink)
                    Text(failed ? "couldn't identify that one — try another shot"
                                : "a record bin, a poster, a tee — snap it")
                        .font(.system(size: 10.5))
                        .foregroundStyle(failed ? t.red : t.muted)
                }
                Spacer()
                if busy { ProgressView().controlSize(.small) }
            }
            .padding(12)
            .background(t.panel)
            .clipShape(RoundedRectangle(cornerRadius: 13))
            .overlay(RoundedRectangle(cornerRadius: 13)
                .strokeBorder(t.line, style: StrokeStyle(lineWidth: 1, dash: [5, 4])))
        }
        .padding(.horizontal, 14).padding(.bottom, 10)
        .disabled(busy)
        .onChange(of: pick) { _, item in
            guard let item else { return }
            pick = nil
            Task { await upload(item) }
        }
        .sheet(item: $result) { r in
            SpotResultView(r: r, t: t)
                .presentationDetents([.medium])
        }
    }

    func upload(_ item: PhotosPickerItem) async {
        busy = true; failed = false
        defer { busy = false }
        guard let raw = try? await item.loadTransferable(type: Data.self),
              let img = UIImage(data: raw),
              let jpeg = img.jpegData(compressionQuality: 0.8) else { failed = true; return }
        do { result = try await player.api.spot(jpeg: jpeg) }
        catch { failed = true }
    }
}

struct SpotResultView: View {
    @EnvironmentObject var player: Player
    @Environment(\.dismiss) var dismiss
    let r: SpotResult
    let t: IOSTheme

    var badgeColor: Color {
        r.status == "matched" ? t.live : r.status == "wishlist" ? t.accent : t.faint
    }
    var badgeText: String {
        r.status == "matched" ? "ON YOUR SHELF" :
        r.status == "wishlist" ? "WISHLIST" : "COULDN'T PLACE IT"
    }

    var body: some View {
        VStack(spacing: 14) {
            Text(badgeText)
                .font(.system(size: 10, weight: .heavy)).tracking(1.6)
                .padding(.horizontal, 12).padding(.vertical, 6)
                .background(badgeColor)
                .foregroundStyle(Color(hexStr: "#12120C"))
                .clipShape(Capsule())
                .padding(.top, 26)
            if !r.title.isEmpty || !r.album.isEmpty {
                Text(r.title.isEmpty ? r.album : r.title)
                    .font(.system(size: 21, weight: .bold))
                    .foregroundStyle(t.ink)
                    .multilineTextAlignment(.center)
            }
            if !r.artist.isEmpty {
                Text(r.artist).font(.system(size: 14)).foregroundStyle(t.muted)
            }
            if r.status == "matched", !r.matchedDir.isEmpty {
                Button {
                    if let al = player.albums.first(where: { $0.dir == r.matchedDir }) {
                        player.playAlbum(al)
                        dismiss()
                    }
                } label: {
                    Text("▶ PLAY IT — IT'S ON YOUR SHELF")
                        .font(.system(size: 11, weight: .heavy)).tracking(1)
                        .padding(.horizontal, 18).padding(.vertical, 11)
                        .background(t.accent).foregroundStyle(t.onAccent)
                        .clipShape(Capsule())
                }
                .buttonStyle(.plain)
            }
            if !r.links.isEmpty {
                HStack(spacing: 10) {
                    ForEach(r.links.sorted(by: { $0.key < $1.key }), id: \.key) { name, url in
                        if let u = URL(string: url) {
                            Link(name.capitalized, destination: u)
                                .font(.system(size: 12, weight: .bold))
                                .foregroundStyle(t.accent)
                                .padding(.horizontal, 12).padding(.vertical, 8)
                                .overlay(Capsule().stroke(t.line, lineWidth: 1))
                        }
                    }
                }
            }
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(t.board)
    }
}
