import SwiftUI
import PhotosUI
import SessionCore

/// A record's photo strip: front cover plus the owner's typed companion shots
/// (tracklist, back, disc…). Swipe through them big; add one from the camera
/// roll — a phone photographing a CD insert is the natural capture device.
struct AlbumPhotosView: View {
    @EnvironmentObject var player: Player
    @Environment(\.dismiss) var dismiss
    let album: Album
    let t: IOSTheme

    @State private var images: [AlbumImage] = []
    @State private var pick: PhotosPickerItem?
    @State private var pendingType = "tracklist"
    @State private var busy = false

    let types = ["front", "tracklist", "back", "disc", "notes"]

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 1) {
                    Text(album.album).font(.system(size: 16, weight: .bold))
                        .foregroundStyle(t.ink).lineLimit(1)
                    Text(album.artist).font(.system(size: 12)).foregroundStyle(t.muted)
                }
                Spacer()
                Button {
                    dismiss()
                } label: {
                    Image(systemName: "xmark").font(.system(size: 12, weight: .bold))
                        .frame(width: 30, height: 30)
                        .foregroundStyle(t.muted)
                        .overlay(Circle().stroke(t.line, lineWidth: 1))
                }
                .buttonStyle(.plain)
            }
            .padding(16)

            if images.isEmpty {
                Spacer()
                Text("No photos yet")
                    .font(.system(size: 14, weight: .bold)).foregroundStyle(t.ink)
                Text("Photograph the cover, the tracklist insert, the disc —\nthey file with the record for everyone.")
                    .font(.system(size: 12)).foregroundStyle(t.muted)
                    .multilineTextAlignment(.center).padding(.top, 4)
                Spacer()
            } else {
                TabView {
                    ForEach(images) { img in
                        VStack(spacing: 10) {
                            NetImage(url: img.imageURL(base: player.stationBase))
                                .aspectRatio(contentMode: .fit)
                                .clipShape(RoundedRectangle(cornerRadius: 10))
                            Text(img.type.uppercased())
                                .font(.system(size: 9, weight: .heavy)).tracking(1.8)
                                .foregroundStyle(t.faint)
                        }
                        .padding(.horizontal, 20)
                    }
                }
                .tabViewStyle(.page)
                .indexViewStyle(.page(backgroundDisplayMode: .always))
            }

            // owner capture: pick the type, then the photo
            VStack(spacing: 10) {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 7) {
                        ForEach(types, id: \.self) { ty in
                            SectionChip(label: ty.uppercased(), on: pendingType == ty, t: t) {
                                pendingType = ty
                            }
                        }
                    }
                    .padding(.horizontal, 16)
                }
                PhotosPicker(selection: $pick, matching: .images) {
                    HStack(spacing: 8) {
                        if busy {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: "camera").font(.system(size: 12, weight: .bold))
                        }
                        Text("ADD \(pendingType.uppercased()) PHOTO")
                            .font(.system(size: 11, weight: .heavy)).tracking(1)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .background(t.accent).foregroundStyle(t.onAccent)
                    .clipShape(Capsule())
                }
                .disabled(busy || player.member == nil)
                .padding(.horizontal, 16)
            }
            .padding(.bottom, 18)
        }
        .background(t.board.ignoresSafeArea())
        .task { await load() }
        .onChange(of: pick) { _, item in
            guard let item else { return }
            pick = nil
            Task { await upload(item) }
        }
    }

    func load() async {
        if let sh = try? await player.api.album(dir: album.dir) {
            images = sh.images
        }
    }

    func upload(_ item: PhotosPickerItem) async {
        busy = true
        defer { busy = false }
        guard let raw = try? await item.loadTransferable(type: Data.self),
              let img = UIImage(data: raw),
              let jpeg = img.jpegData(compressionQuality: 0.85) else { return }
        if await player.uploadAlbumArt(dir: album.dir, type: pendingType, jpeg: jpeg) {
            tapHaptic()
            await load()
        }
    }
}
