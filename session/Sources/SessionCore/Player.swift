import Foundation
import AVFoundation
import MediaPlayer

/// One engine, two sources (CD arrives with sign-in in P1).
/// RADIO rides the live icecast proxy — no seeking, the open connection is the
/// listener's presence. TAPE plays the current show's tracklist directly — scrub,
/// jump, rewind — and heartbeats /api/presence instead.
@MainActor
public final class Player: ObservableObject {

    public enum Source: String { case radio, tape, cd }
    public enum Status: Equatable { case idle, tuning, playing, paused, offAir }

    @Published public private(set) var channels: [Channel] = []
    @Published public private(set) var current: Channel?
    @Published public private(set) var source: Source = .radio
    @Published public private(set) var status: Status = .idle
    @Published public private(set) var now = NowPlaying.empty
    @Published public private(set) var show: Show?
    @Published public private(set) var trackIndex = -1
    @Published public private(set) var member: String?      // signed-in name, nil = anonymous
    @Published public private(set) var albums: [Album] = [] // the shelf (empty when anonymous)
    @Published public private(set) var currentAlbum: Album?
    @Published public private(set) var rip: RipStatus?      // LISTEN AND RIP, live
    @Published public private(set) var favs: [Fav] = []
    @Published public private(set) var history: [HistoryRow] = []
    @Published public var position: Double = 0
    @Published public private(set) var duration: Double = 0
    @Published public var isScrubbing = false

    @Published public var stationBase: URL {
        didSet {
            UserDefaults.standard.set(stationBase.absoluteString, forKey: "station")
            api = StationAPI(base: stationBase)
            Task { await refreshChannels() }
        }
    }

    public var volume: Float {
        get { player.volume }
        set { player.volume = newValue; UserDefaults.standard.set(newValue, forKey: "volume") }
    }

    public private(set) var api: StationAPI
    private let player = AVPlayer()
    private var timeObserver: Any?
    private var pollTask: Task<Void, Never>?
    private var presenceTask: Task<Void, Never>?
    private var endObserver: NSObjectProtocol?
    private var retryDelay: TimeInterval = 1
    private let aid: String

    public var isPlaying: Bool { status == .playing || status == .tuning }

    public init() {
        let saved = UserDefaults.standard.string(forKey: "station")
        let base = saved.flatMap(URL.init(string:)) ?? StationAPI.defaultBase
        stationBase = base
        api = StationAPI(base: base)
        if UserDefaults.standard.string(forKey: "aid") == nil {
            UserDefaults.standard.set(UUID().uuidString, forKey: "aid")
        }
        aid = UserDefaults.standard.string(forKey: "aid")!
        player.volume = UserDefaults.standard.object(forKey: "volume") as? Float ?? 0.9

        timeObserver = player.addPeriodicTimeObserver(
            forInterval: CMTime(seconds: 0.5, preferredTimescale: 10), queue: .main
        ) { [weak self] t in
            Task { @MainActor [weak self] in
                guard let self, self.source != .radio, !self.isScrubbing else { return }
                self.position = t.seconds.isFinite ? t.seconds : 0
                let d = self.player.currentItem?.duration.seconds ?? 0
                self.duration = d.isFinite ? d : 0
                self.pushNowPlayingInfo()
            }
        }
        endObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in self?.trackEnded() }
        }
        setupRemoteCommands()
        Task {
            await refreshChannels()
            await refreshMembership()
        }
        Task { [weak self] in           // the rip bar: cheap poll, always on
            while !Task.isCancelled {
                guard let self else { return }
                let r = await self.api.rip()
                let wasRipping = self.rip?.ripping ?? false
                self.rip = r
                // a rip just FINISHED — the disc landed on the shelf; refresh it
                if wasRipping, !(r?.ripping ?? false), self.member != nil {
                    self.albums = (try? await self.api.albums()) ?? self.albums
                }
                try? await Task.sleep(for: .seconds(10))
            }
        }
    }

    // ── channels ─────────────────────────────────────────────────────────

    public func refreshChannels() async {
        if let chans = try? await api.channels() {
            channels = chans
            if current == nil { current = chans.first(where: \.playable) }
        }
    }

    // ── membership & the shelf ───────────────────────────────────────────

    public func refreshMembership() async {
        member = await api.me()
        if member != nil {
            albums = (try? await api.albums()) ?? []
            favs = (try? await api.favourites()) ?? []
            await refreshChannels()               // private channels appear
        } else {
            albums = []
            favs = []
        }
    }

    // ── favourites: ♥ what's playing, play them back as a set ────────────

    public var nowIsFavourite: Bool {
        !now.url.isEmpty && favs.contains { $0.url == now.url }
    }

    public func toggleFavourite() {
        guard member != nil, !now.url.isEmpty else { return }
        if nowIsFavourite {
            let url = now.url
            favs.removeAll { $0.url == url }
            Task { await api.removeFavourite(url: url) }
        } else {
            let f = Fav(url: now.url, title: now.title, artist: now.artist,
                        album: now.album, channel: current?.slug ?? "")
            favs.append(f)
            Task { await api.addFavourite(f) }
        }
    }

    /// Favourites play as a station: the whole list on the tape deck, from here.
    public func playFavourites(at index: Int) {
        guard !favs.isEmpty else { return }
        currentAlbum = nil
        show = Show(channel: "favourites", album: "Favourites",
                    tracks: favs.map {
                        ShowTrack(title: $0.title, artist: $0.artist,
                                  album: $0.album, url: $0.url)
                    })
        source = .tape
        playTrack(index)
    }

    public func refreshHistory() async {
        history = (try? await api.history()) ?? []
    }

    public func signIn(code: String) async throws {
        try await api.signIn(code: code)
        await refreshMembership()
    }

    public func signOut() async {
        await api.signOut()
        member = nil
        albums = []
        if source == .cd { setSource(.radio) }
        await refreshChannels()
    }

    /// CD: an album off the shelf, played on demand.
    public func playAlbum(_ album: Album) {
        Task {
            guard let sh = try? await api.album(dir: album.dir), !sh.tracks.isEmpty else { return }
            currentAlbum = album
            show = sh
            source = .cd
            playTrack(0)
        }
    }

    // ── tune / sources ───────────────────────────────────────────────────

    public func tune(_ channel: Channel) {
        guard channel.playable else { return }
        current = channel
        source = .radio
        show = nil; currentAlbum = nil; trackIndex = -1; position = 0; duration = 0
        playRadio()
    }

    public func setSource(_ s: Source) {
        guard s != source, let ch = current else { return }
        source = s
        switch s {
        case .cd:
            break                                  // playAlbum() is the door to CD
        case .radio:
            currentAlbum = nil
            show = nil; trackIndex = -1
            playRadio()
        case .tape:
            Task {
                if let sh = try? await api.show(channel: ch.slug), !sh.tracks.isEmpty {
                    show = sh
                    playTrack(max(sh.playing, 0))
                } else {
                    show = nil
                    source = .radio   // nothing on the reel — stay honest
                }
            }
        }
    }

    // ── transport ────────────────────────────────────────────────────────

    public func toggle() {
        switch status {
        case .playing, .tuning:
            player.pause()
            status = .paused
            stopPolling()
        case .paused:
            player.play()
            status = .playing
            startPolling()
        case .idle, .offAir:
            if source == .radio { playRadio() } else if trackIndex >= 0 { playTrack(trackIndex) }
        }
        pushNowPlayingInfo()
    }

    /// RADIO skip — the UI confirms first (it moves the station for everyone).
    public func skipRadio() {
        guard let ch = current else { return }
        Task {
            try? await api.skip(channel: ch.slug)
            try? await Task.sleep(for: .seconds(2))
            await pollNow()
        }
    }

    public func nextTrack() { if let sh = show, trackIndex + 1 < sh.tracks.count { playTrack(trackIndex + 1) } }
    public func prevTrack() {
        if position > 4 { seek(to: 0) }
        else if trackIndex > 0 { playTrack(trackIndex - 1) }
    }
    public func jump(to index: Int) { playTrack(index) }

    public func seek(to seconds: Double) {
        position = seconds
        player.seek(to: CMTime(seconds: seconds, preferredTimescale: 600))
    }

    // ── internals ────────────────────────────────────────────────────────

    private func playRadio() {
        guard let ch = current else { return }
        let item = AVPlayerItem(url: api.streamURL(slug: ch.slug))
        watch(item)
        player.replaceCurrentItem(with: item)
        player.play()
        status = .tuning
        startPolling()
        pushNowPlayingInfo()
    }

    private func playTrack(_ index: Int) {
        guard let sh = show, sh.tracks.indices.contains(index),
              let url = api.trackURL(sh.tracks[index].url) else { return }
        trackIndex = index
        let t = sh.tracks[index]
        now = NowPlaying(title: t.title, artist: t.artist, album: t.album, url: t.url)
        position = 0; duration = 0
        let item = AVPlayerItem(url: url)
        watch(item)
        player.replaceCurrentItem(with: item)
        player.play()
        status = .tuning
        startPolling()
        pushNowPlayingInfo()
    }

    private func trackEnded() {
        guard source != .radio, let sh = show else { return }
        if trackIndex + 1 < sh.tracks.count { playTrack(trackIndex + 1) }
        else { status = .paused }
    }

    private var itemObservation: NSKeyValueObservation?
    private func watch(_ item: AVPlayerItem) {
        itemObservation = item.observe(\.status, options: [.new]) { [weak self] it, _ in
            Task { @MainActor [weak self] in
                guard let self else { return }
                switch it.status {
                case .readyToPlay:
                    self.status = .playing
                    self.retryDelay = 1
                case .failed:
                    self.streamTrouble()
                default: break
                }
                self.pushNowPlayingInfo()
            }
        }
    }

    /// RADIO drop → backoff re-tune (1s → 2s → … cap 30s). TAPE → try the next track once.
    private func streamTrouble() {
        if source == .radio {
            status = .tuning
            let delay = retryDelay
            retryDelay = min(retryDelay * 2, 30)
            Task {
                try? await Task.sleep(for: .seconds(delay))
                if source == .radio, status == .tuning { playRadio() }
            }
        } else {
            if let sh = show, trackIndex + 1 < sh.tracks.count { playTrack(trackIndex + 1) }
            else { status = .offAir }
        }
    }

    // ── polling & presence ───────────────────────────────────────────────

    private func startPolling() {
        stopPolling()
        pollTask = Task {
            while !Task.isCancelled {
                await pollNow()
                try? await Task.sleep(for: .seconds(5))
            }
        }
        if source != .radio {
            presenceTask = Task {
                while !Task.isCancelled {
                    if let ch = current { await api.presence(channel: ch.slug, aid: aid) }
                    try? await Task.sleep(for: .seconds(30))
                }
            }
        }
    }

    private func stopPolling() {
        pollTask?.cancel(); pollTask = nil
        presenceTask?.cancel(); presenceTask = nil
    }

    private func pollNow() async {
        guard source == .radio, let ch = current else { return }
        if let np = try? await api.nowPlaying(channel: ch.slug) {
            if np != now {
                now = np
                pushNowPlayingInfo()
                // keep the set list in view on radio too (read-only — jumping is Tape's job)
                show = try? await api.show(channel: ch.slug)
            }
        } else if show == nil {
            show = try? await api.show(channel: ch.slug)
        }
    }

    // ── lock screen / media keys ─────────────────────────────────────────

    private func setupRemoteCommands() {
        let c = MPRemoteCommandCenter.shared()
        c.playCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.toggle() }; return .success
        }
        c.pauseCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.toggle() }; return .success
        }
        c.togglePlayPauseCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.toggle() }; return .success
        }
        c.nextTrackCommand.addTarget { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                if self.source != .radio { self.nextTrack() }  // radio skip needs the confirm
            }
            return .success
        }
        c.previousTrackCommand.addTarget { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                if self.source != .radio { self.prevTrack() }
            }
            return .success
        }
    }

    private func pushNowPlayingInfo() {
        var info: [String: Any] = [
            MPMediaItemPropertyTitle: now.title.isEmpty ? (current?.name ?? "Session") : now.title,
            MPMediaItemPropertyArtist: now.artist,
            MPMediaItemPropertyAlbumTitle: now.album,
            MPNowPlayingInfoPropertyIsLiveStream: source == .radio,
            MPNowPlayingInfoPropertyPlaybackRate: status == .playing ? 1.0 : 0.0,
        ]
        if source != .radio, duration > 0 {
            info[MPMediaItemPropertyPlaybackDuration] = duration
            info[MPNowPlayingInfoPropertyElapsedPlaybackTime] = position
        }
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
        MPNowPlayingInfoCenter.default().playbackState = status == .playing ? .playing : .paused
    }
}
