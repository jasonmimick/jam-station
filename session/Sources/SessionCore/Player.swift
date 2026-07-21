import Foundation
import AVFoundation
import MediaPlayer
import os

let engineLog = Logger(subsystem: "run.jam-station.session", category: "engine")

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
    @Published public private(set) var memberEmail: String?

    /// The member's personal-radio handle — the server's rule, mirrored:
    /// the email local part, lowercased, URL-safe characters only.
    public var memberHandle: String? {
        guard let email = memberEmail, let local = email.lowercased()
            .split(separator: "@").first else { return nil }
        let safe = local.unicodeScalars.filter {
            CharacterSet.lowercaseLetters.contains($0)
            || CharacterSet.decimalDigits.contains($0)
            || "._+-".unicodeScalars.contains($0)
        }
        let h = String(String.UnicodeScalarView(safe)).prefix(48)
        return h.isEmpty ? nil : String(h)
    }
    @Published public private(set) var albums: [Album] = [] // the shelf (empty when anonymous)
    @Published public private(set) var currentAlbum: Album?
    @Published public private(set) var rip: RipStatus?      // LISTEN AND RIP, live
    @Published public private(set) var favs: [Fav] = []
    @Published public private(set) var history: [HistoryRow] = []
    /// "Let it dance" clock — advances only while music plays and the toggle is on;
    /// the UI sways the accent hue with it. (True audio-reactive comes with an engine tap.)
    @Published public private(set) var dancePhase: Double = 0
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
    // AVQueuePlayer: the next tracks are enqueued and PRE-BUFFERING while the
    // current one plays — near-gapless advances, instant skips (the cold-start
    // per track was painfully audible on cellular in the car).
    private let player = AVQueuePlayer()
    private var timeObserver: Any?
    private var pollTask: Task<Void, Never>?
    private var presenceTask: Task<Void, Never>?
    private var endObserver: NSObjectProtocol?
    private var stallObserver: NSObjectProtocol?
    private var napActivity: NSObjectProtocol?
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
        stallObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemPlaybackStalled, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.status == .playing else { return }
                if self.source == .radio { self.playRadio() }   // re-tune the stream
                else { self.player.play() }                      // nudge the tape
            }
        }
        #if os(macOS)
        // App Nap pauses timers and throttles networking for background apps —
        // a radio must not nap.
        napActivity = ProcessInfo.processInfo.beginActivity(
            options: [.userInitiated, .automaticTerminationDisabled],
            reason: "Session audio playback")
        #endif
        setupRemoteCommands()
        Task {
            await refreshChannels()
            await refreshMembership()
        }
        Task { [weak self] in           // the dance clock: 8 Hz, only ticks when wanted
            while !Task.isCancelled {
                guard let self else { return }
                if UserDefaults.standard.bool(forKey: "dance"), self.status == .playing {
                    self.dancePhase += 0.24
                }
                try? await Task.sleep(for: .milliseconds(125))
            }
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
            if current == nil {
                // resume where you left off — the dial remembers its position
                let last = UserDefaults.standard.string(forKey: "lastChannel")
                current = chans.first(where: { $0.slug == last && $0.playable })
                    ?? chans.first(where: \.playable)
            }
        }
    }

    // ── membership & the shelf ───────────────────────────────────────────

    @Published public private(set) var spots: [SpotResult] = []
    @Published public private(set) var genres: [GenreCount] = []
    @Published public private(set) var vinyl: [VinylRecord] = []
    @Published public private(set) var vinylSections: [GenreCount] = []
    @Published public private(set) var attic: [Album] = []   // the rescued crate
    @Published public private(set) var dialNow: [String: NowPlaying] = [:]

    public func refreshDial() async {
        dialNow = (try? await api.dial()) ?? dialNow
    }

    public func refreshMembership() async {
        // a network hiccup must NOT masquerade as a sign-out and wipe the shelf
        let result: StationAPI.Whoami?
        do { result = try await api.me() } catch { return }       // offline: keep current state
        member = result?.name
        memberEmail = result?.email
        if member != nil {
            albums = (try? await api.albums()) ?? albums
            favs = (try? await api.favourites()) ?? favs
            spots = (try? await api.spots()) ?? spots
            genres = (try? await api.genres()) ?? genres
            vinyl = (try? await api.vinyl()) ?? vinyl
            vinylSections = (try? await api.vinylSections()) ?? vinylSections
            attic = (try? await api.atticAlbums()) ?? attic
            await refreshChannels()               // private channels appear
        } else {
            albums = []                            // server CONFIRMED anonymous
            favs = []
            spots = []
            genres = []
            vinyl = []
            vinylSections = []
            attic = []
        }
    }

    public func refreshSpots() async {
        spots = (try? await api.spots()) ?? []
    }

    public func deleteSpot(_ s: SpotResult) {
        spots.removeAll { $0.id == s.id }
        Task { await api.deleteSpot(id: s.id) }
    }

    // ── favourites: ♥ what's playing, play them back as a set ────────────

    public var nowIsFavourite: Bool {
        !now.url.isEmpty && favs.contains { $0.url == now.url }
    }

    /// The art for what's playing RIGHT NOW: on tape/CD/mix, the playing
    /// track's own record sleeve; nil means "fall back to channel art".
    public var nowCoverURL: URL? {
        guard source != .radio, let sh = show, sh.tracks.indices.contains(trackIndex),
              let p = sh.tracks[trackIndex].coverPath else { return nil }
        return URL(string: p, relativeTo: stationBase)?.absoluteURL
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

    /// Owner drops a photo on a record; the browsed/playing album refreshes so
    /// the strip shows the new picture immediately.
    public func uploadAlbumArt(dir: String, type: String, jpeg: Data) async -> Bool {
        do { try await api.uploadAlbumArt(dir: dir, type: type, jpeg: jpeg) }
        catch { return false }
        if let fresh = try? await api.album(dir: dir) {
            if browsed?.album.dir == dir, let al = browsed?.album {
                browsed = (al, fresh)
            } else if currentAlbum?.dir == dir {
                let idx = trackIndex
                show = fresh
                trackIndex = idx        // display only — playback untouched
            }
        }
        albums = (try? await api.albums()) ?? albums
        return true
    }

    // ── sleep timer ──────────────────────────────────────────────────────

    @Published public private(set) var sleepAt: Date?
    private var sleepTask: Task<Void, Never>?

    public func setSleepTimer(minutes: Int?) {
        sleepTask?.cancel(); sleepTask = nil; sleepAt = nil
        guard let m = minutes, m > 0 else { return }
        sleepAt = Date().addingTimeInterval(Double(m) * 60)
        sleepTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(Double(m) * 60))
            guard let self, !Task.isCancelled else { return }
            if self.isPlaying { self.toggle() }
            self.sleepAt = nil
        }
    }

    public func signIn(code: String) async throws {
        try await api.signIn(code: code)
        await refreshMembership()
    }

    public func signOut() async {
        await api.signOut()
        member = nil
        memberEmail = nil
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

    /// Endless feeds: a shelf-section mix, a mix-only channel (shelf-*/vault-*),
    /// or an attic artist. One engine — fetch, splice/replace, append before dry.
    public enum MixFeed: Equatable {
        case genre(String)      // /api/library/mix?genre=
        case slug(String)       // /api/mix?slug=      (the forward path)
        case artist(String)     // /api/attic/artist?name=
    }
    private var mixFeed: MixFeed?
    private var feedTopUp = false           // an append is already in flight

    private func fetchFeed(_ feed: MixFeed) async -> Show? {
        switch feed {
        case .genre(let g): return try? await api.mix(genre: g)
        case .slug(let s): return try? await api.mixChannel(slug: s)
        case .artist(let a): return try? await api.atticArtist(name: a)
        }
    }

    public func playMix(_ genre: String, label: String? = nil, seamless: Bool = true) {
        startFeed(.genre(genre), label: label ?? "\(genre) Mix", seamless: seamless)
    }

    /// Tune a mix-only channel (shelf-* / vault-*) — instant personal lineup.
    public func playMixChannel(_ channel: Channel, seamless: Bool = true) {
        startFeed(.slug(channel.slug), label: channel.name, seamless: seamless)
    }

    /// Everything by an attic artist, shuffled, endless.
    public func playAtticArtist(_ name: String) {
        startFeed(.artist(name), label: "\(name) — from the attic", seamless: true)
    }

    private func startFeed(_ feed: MixFeed, label: String, seamless: Bool) {
        Task {
            guard let sh = await fetchFeed(feed), !sh.tracks.isEmpty else {
                engineLog.error("startFeed \(String(describing: feed), privacy: .public): empty")
                return
            }
            currentAlbum = nil
            browsed = nil
            mixFeed = feed
            let title = label
            // Seamless handoff: if a song is already playing on-demand, it KEEPS
            // playing — the station's lineup queues up behind it. No cut.
            // ONLY valid while a live player item actually exists: at end-of-mix
            // refill the finished item is already gone, and handing off from
            // nothing silently stopped playback with now-playing frozen.
            if seamless, source != .radio, status == .playing || status == .paused,
               player.currentItem != nil,
               let curShow = show, curShow.tracks.indices.contains(trackIndex) {
                let cur = curShow.tracks[trackIndex]
                show = Show(channel: "mix", album: title, tracks: [cur] + sh.tracks)
                trackIndex = 0
                source = .tape
                for item in player.items().dropFirst() { player.remove(item) }
                for i in 1...min(2, sh.tracks.count) {
                    if let item = queueItem(at: i) {
                        player.insert(item, after: player.items().last)
                    }
                }
                engineLog.info("feed handoff: \(title, privacy: .public) behind '\(cur.title, privacy: .public)' items=\(self.player.items().count)")
                pushNowPlayingInfo()
            } else {
                show = Show(channel: "mix", album: title, tracks: sh.tracks)
                source = .tape
                engineLog.info("feed fresh: \(title, privacy: .public) tracks=\(sh.tracks.count) seamless=\(seamless)")
                playTrack(0)
            }
        }
    }

    /// The doc's endless pattern: two tracks from the end, fetch the next batch
    /// and APPEND — the feed never has an edge to fall off.
    private func topUpFeed() {
        guard let feed = mixFeed, !feedTopUp,
              let sh = show, sh.channel == "mix",
              trackIndex >= sh.tracks.count - 2 else { return }
        feedTopUp = true
        Task {
            defer { feedTopUp = false }
            guard let more = await fetchFeed(feed), !more.tracks.isEmpty,
                  let cur = show, cur.channel == "mix" else { return }
            show = Show(channel: "mix", album: cur.album, tracks: cur.tracks + more.tracks)
            engineLog.info("feed top-up: +\(more.tracks.count) → \(self.show?.tracks.count ?? 0)")
        }
    }

    /// Flip to RADIO = "take me live, with music LIKE this."
    /// From a record or a mix, that means finding the station that matches what
    /// you're hearing: the genre's own shelf station first, then any channel
    /// whose name speaks the genre (Late Night Jazz for a jazz record). A tape
    /// of a radio show simply rejoins its broadcast — same music, now live.
    public func flipToRadio() {
        guard source != .radio else { return }
        var contextGenres: [String] = []
        if source == .cd, let al = currentAlbum {
            contextGenres = al.genres
        } else if show?.channel == "mix" {
            switch mixFeed {
            case .genre(let g): contextGenres = [g]
            case .slug(let s): contextGenres = channels.first { $0.slug == s }?.mixGenre.map { [$0] } ?? []
            default: break
            }
        }
        for g in contextGenres {
            if let ch = shelfStation(for: g) { tune(ch); return }
        }
        for g in contextGenres {
            if let ch = channels.first(where: {
                $0.playable && $0.name.localizedCaseInsensitiveContains(g)
            }) { tune(ch); return }
        }
        setSource(.radio)      // a show's own tape, favourites, or no match: rejoin live
    }

    private func shelfStation(for genre: String) -> Channel? {
        var slug = "shelf-"
        var lastDash = true
        for ch in genre.lowercased() {
            if ch.isLetter || ch.isNumber { slug.append(ch); lastDash = false }
            else if !lastDash { slug.append("-"); lastDash = true }
        }
        if slug.hasSuffix("-") { slug.removeLast() }
        return channels.first { $0.slug == slug && $0.playable }
    }

    /// Owner curation: pin a record's sections, then refresh what the shelf knows.
    public func setAlbumGenres(_ album: Album, genres newGenres: [String]) {
        Task {
            await api.setGenres(dir: album.dir, genres: newGenres)
            albums = (try? await api.albums()) ?? albums
            genres = (try? await api.genres()) ?? genres
        }
    }

    // ── attic jumps: from a playing vault track to its record / artist ──

    /// "/attic/root/folder/file.mp3" (percent-encoded) → the record's opaque
    /// key "attic:root/folder" — the same door /api/library/album opens.
    public func atticRecordDir(fromTrackURL url: String) -> String? {
        guard url.hasPrefix("/attic/") else { return nil }
        let decoded = url.removingPercentEncoding ?? url
        var parts = decoded.dropFirst("/attic/".count).split(separator: "/")
        guard parts.count >= 2 else { return nil }
        parts.removeLast()                        // drop the filename
        return "attic:" + parts.joined(separator: "/")
    }

    /// Play the record the current attic track came from, in order.
    public func playAtticRecord(dir: String) {
        if let al = attic.first(where: { $0.dir == dir }) {
            playAlbum(al)                         // full CD treatment: chip, art, tracklist
            return
        }
        Task {                                    // crate not loaded / stale — play it anyway
            guard let sh = try? await api.album(dir: dir), !sh.tracks.isEmpty else { return }
            currentAlbum = nil; browsed = nil; mixFeed = nil
            show = Show(channel: "mix", album: sh.album, tracks: sh.tracks)
            source = .tape
            playTrack(0)
        }
    }

    // ── browsing the shelf: look at a record without dropping the needle ──

    @Published public private(set) var browsed: (album: Album, show: Show)?

    public func browseAlbum(_ album: Album) {
        Task {
            guard let sh = try? await api.album(dir: album.dir), !sh.tracks.isEmpty else { return }
            browsed = (album, sh)
        }
    }

    public func closeBrowse() { browsed = nil }

    public func playBrowsed(at index: Int) {
        guard let b = browsed else { return }
        currentAlbum = b.album
        show = b.show
        source = .cd
        browsed = nil
        playTrack(index)
    }

    // ── tune / sources ───────────────────────────────────────────────────

    public func tune(_ channel: Channel) {
        guard channel.playable else { return }
        UserDefaults.standard.set(channel.slug, forKey: "lastChannel")
        current = channel
        // a genre station is mix-only: the song changes NOW and the lineup
        // queues behind it — no live stream to join mid-song
        if channel.mixGenre != nil {
            playMixChannel(channel)           // the generic mix door, station's name on
            return
        }
        source = .radio
        show = nil; currentAlbum = nil; browsed = nil
        trackIndex = -1; position = 0; duration = 0
        playRadio()
    }

    /// Straight onto the tape deck: tune a channel directly into its current
    /// show, on demand — without joining the broadcast first.
    public func playTape(_ channel: Channel) {
        guard channel.playable else { return }
        UserDefaults.standard.set(channel.slug, forKey: "lastChannel")
        current = channel
        browsed = nil; currentAlbum = nil
        Task {
            if let sh = try? await api.show(channel: channel.slug), !sh.tracks.isEmpty {
                show = sh
                source = .tape
                playTrack(max(sh.playing, 0))
            } else {
                tune(channel)      // nothing on the reel — ride the broadcast
            }
        }
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

    public func nextTrack() {
        guard let sh = show, trackIndex + 1 < sh.tracks.count else { return }
        if player.items().count > 1 {
            player.advanceToNextItem()      // already buffered — instant
            advancedInQueue()
            player.playImmediately(atRate: 1.0)
        } else {
            playTrack(trackIndex + 1)
        }
    }
    public func prevTrack() {
        if position > 4 { seek(to: 0) }
        else if trackIndex > 0 { playTrack(trackIndex - 1) }
    }

    // ── history stepping: the transport walks time, not just tracks ──────
    // Radio ⏮ = step back in time onto the tape at the previous track.
    // Tape ⏭ past the end of a radio show = rejoin the live broadcast.

    public func stepBack() {
        guard source == .radio else { prevTrack(); return }
        guard let ch = current else { return }
        Task {
            guard let sh = try? await api.show(channel: ch.slug), !sh.tracks.isEmpty else { return }
            show = sh
            source = .tape
            playTrack(max(sh.playing - 1, 0))
        }
    }

    public func stepForward() {
        guard source != .radio else { return }   // radio forward = skip (UI confirms)
        // only a radio show's own tape rejoins the broadcast at its end —
        // mixes and favourites just stop (there's no "live" to rejoin)
        if let sh = show, trackIndex + 1 >= sh.tracks.count,
           sh.channel == current?.slug, currentAlbum == nil {
            setSource(.radio)                    // ran off the tape's end → back to LIVE
        } else if let sh = show, trackIndex + 1 >= sh.tracks.count,
                  sh.channel == "mix", let feed = mixFeed {
            startFeed(feed, label: sh.album, seamless: false)   // a skip CUTS — next batch, now
        } else {
            nextTrack()
        }
    }
    public func jump(to index: Int) { playTrack(index) }

    public func seek(to seconds: Double) {
        position = seconds
        player.seek(to: CMTime(seconds: seconds, preferredTimescale: 600))
    }

    // ── internals ────────────────────────────────────────────────────────

    /// AVPlayer does NOT attach the app's cookies by itself — and the members-only
    /// /music files (CD source, private streams) 403 without the session cookie.
    private func makeItem(url: URL) -> AVPlayerItem {
        let opts = [AVURLAssetHTTPCookiesKey: HTTPCookieStorage.shared.cookies ?? []]
        return AVPlayerItem(asset: AVURLAsset(url: url, options: opts))
    }

    private func playRadio() {
        guard let ch = current else { return }
        let item = makeItem(url: api.streamURL(slug: ch.slug))
        watch(item)
        player.removeAllItems()
        player.insert(item, after: nil)
        player.play()
        status = .tuning
        startPolling()
        pushNowPlayingInfo()
    }

    private func queueItem(at index: Int) -> AVPlayerItem? {
        guard let sh = show, sh.tracks.indices.contains(index),
              let url = api.trackURL(sh.tracks[index].url) else { return nil }
        return makeItem(url: url)
    }

    private func playTrack(_ index: Int) {
        guard let sh = show, sh.tracks.indices.contains(index) else {
            engineLog.error("playTrack(\(index)): out of range (count=\(self.show?.tracks.count ?? -1))")
            return
        }
        trackIndex = index
        let t = sh.tracks[index]
        engineLog.info("playTrack \(index): '\(t.title, privacy: .public)' show=\(sh.channel, privacy: .public)")
        now = NowPlaying(title: t.title, artist: t.artist, album: t.album, url: t.url)
        position = 0; duration = 0
        player.removeAllItems()
        for i in index..<min(index + 3, sh.tracks.count) {   // current + 2 pre-buffering
            if let item = queueItem(at: i) {
                if i == index { watch(item) }
                player.insert(item, after: player.items().last)
            }
        }
        player.playImmediately(atRate: 1.0)
        status = .tuning
        startPolling()
        pushNowPlayingInfo()
    }

    /// The queue advanced (naturally or by skip) — sync state, top up lookahead.
    private func advancedInQueue() {
        guard source != .radio, let sh = show, trackIndex + 1 < sh.tracks.count else {
            // a mix never runs dry — fetch the next shuffled batch and roll on
            if let sh2 = show, sh2.channel == "mix", let feed = mixFeed {
                engineLog.info("feed ran dry → restart")
                startFeed(feed, label: sh2.album, seamless: false)
            } else {
                engineLog.info("show ended (idx=\(self.trackIndex)) → paused")
                status = .paused
                pushNowPlayingInfo()
            }
            return
        }
        trackIndex += 1
        let t = sh.tracks[trackIndex]
        engineLog.info("advanced → \(self.trackIndex): '\(t.title, privacy: .public)' items=\(self.player.items().count)")
        topUpFeed()                               // append before a feed can run dry
        now = NowPlaying(title: t.title, artist: t.artist, album: t.album, url: t.url)
        position = 0; duration = 0
        if let cur = player.currentItem { watch(cur) }
        let lookahead = trackIndex + 2
        if lookahead < sh.tracks.count, player.items().count < 3,
           let item = queueItem(at: lookahead) {
            player.insert(item, after: player.items().last)
        }
        pushNowPlayingInfo()
    }

    private func trackEnded() {
        guard source != .radio else { return }
        advancedInQueue()      // AVQueuePlayer already moved on; follow it
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
        // silent-death watchdog: we believe we're playing but AVPlayer isn't
        // moving and isn't buffering either — the stream died without a word
        if status == .playing, player.timeControlStatus == .paused {
            engineLog.error("radio silent death — re-tuning \(ch.slug, privacy: .public)")
            playRadio()
            return
        }
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
        #if os(macOS)
        MPNowPlayingInfoCenter.default().playbackState = status == .playing ? .playing : .paused
        #endif
    }
}
