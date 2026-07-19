import Foundation

public struct Channel: Decodable, Identifiable, Equatable {
    public let slug: String
    public let name: String
    public let source: String
    public let playable: Bool
    public let isPrivate: Bool
    public let artPath: String?

    public var id: String { slug }

    enum CodingKeys: String, CodingKey {
        case slug, name, source, playable
        case isPrivate = "private"
        case artPath = "art_url"
    }

    public func artURL(base: URL) -> URL? {
        guard let artPath else { return nil }
        return URL(string: artPath, relativeTo: base)?.absoluteURL
    }
}

public struct NowPlaying: Decodable, Equatable {
    public var title: String
    public var artist: String
    public var album: String
    public var url: String

    enum CodingKeys: String, CodingKey { case title, artist, album, url }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        title = (try? c.decode(String.self, forKey: .title)) ?? ""
        artist = (try? c.decode(String.self, forKey: .artist)) ?? ""
        album = (try? c.decode(String.self, forKey: .album)) ?? ""
        url = (try? c.decode(String.self, forKey: .url)) ?? ""
    }

    public init(title: String = "", artist: String = "", album: String = "", url: String = "") {
        self.title = title; self.artist = artist; self.album = album; self.url = url
    }

    public static let empty = NowPlaying()
    public var isEmpty: Bool { title.isEmpty && artist.isEmpty && album.isEmpty }
}

public struct ShowTrack: Decodable, Equatable, Identifiable {
    public let title: String
    public let artist: String
    public let album: String
    public let url: String
    public let served: Bool
    public var id: String { url }

    enum CodingKeys: String, CodingKey { case title, artist, album, url, served }

    public init(title: String, artist: String, album: String, url: String, served: Bool = false) {
        self.title = title; self.artist = artist; self.album = album
        self.url = url; self.served = served
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        title = (try? c.decode(String.self, forKey: .title)) ?? ""
        artist = (try? c.decode(String.self, forKey: .artist)) ?? ""
        album = (try? c.decode(String.self, forKey: .album)) ?? ""
        url = (try? c.decode(String.self, forKey: .url)) ?? ""
        // Postgres may hand this back as a bool or an int depending on the column
        if let b = try? c.decode(Bool.self, forKey: .served) { served = b }
        else if let i = try? c.decode(Int.self, forKey: .served) { served = i != 0 }
        else { served = false }
    }
}

public struct Album: Decodable, Identifiable, Equatable {
    public let dir: String
    public let artist: String
    public let album: String
    public let trackCount: Int
    public let coverPath: String?
    public let year: Int?

    public var id: String { dir }

    enum CodingKeys: String, CodingKey {
        case dir, artist, album, year
        case trackCount = "tracks"
        case coverPath = "cover_url"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        dir = (try? c.decode(String.self, forKey: .dir)) ?? ""
        artist = (try? c.decode(String.self, forKey: .artist)) ?? ""
        album = (try? c.decode(String.self, forKey: .album)) ?? ""
        trackCount = (try? c.decode(Int.self, forKey: .trackCount)) ?? 0
        coverPath = try? c.decode(String.self, forKey: .coverPath)
        if let y = try? c.decode(Int.self, forKey: .year) { year = y }
        else if let s = try? c.decode(String.self, forKey: .year) { year = Int(s) }
        else { year = nil }
    }

    public func coverURL(base: URL) -> URL? {
        guard let coverPath else { return nil }
        return URL(string: coverPath, relativeTo: base)?.absoluteURL
    }
}

public struct Fav: Codable, Equatable, Identifiable {
    public let url: String
    public let title: String
    public let artist: String
    public let album: String
    public let channel: String
    public var id: String { url }

    public init(url: String, title: String, artist: String, album: String, channel: String) {
        self.url = url; self.title = title; self.artist = artist
        self.album = album; self.channel = channel
    }

    enum CodingKeys: String, CodingKey { case url, title, artist, album, channel }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        url = (try? c.decode(String.self, forKey: .url)) ?? ""
        title = (try? c.decode(String.self, forKey: .title)) ?? ""
        artist = (try? c.decode(String.self, forKey: .artist)) ?? ""
        album = (try? c.decode(String.self, forKey: .album)) ?? ""
        channel = (try? c.decode(String.self, forKey: .channel)) ?? ""
    }
}

public struct HistoryRow: Decodable, Equatable, Identifiable {
    public let channel: String
    public let title: String
    public let artist: String
    public let album: String
    public let playedAt: String

    public var id: String { playedAt + title }

    enum CodingKeys: String, CodingKey {
        case channel, title, artist, album
        case playedAt = "played_at"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        channel = (try? c.decode(String.self, forKey: .channel)) ?? ""
        title = (try? c.decode(String.self, forKey: .title)) ?? ""
        artist = (try? c.decode(String.self, forKey: .artist)) ?? ""
        album = (try? c.decode(String.self, forKey: .album)) ?? ""
        playedAt = (try? c.decode(String.self, forKey: .playedAt)) ?? ""
    }

    /// "2026-07-18T17:03:11…" → "5:03 PM" (fall back to the raw tail)
    public var when: String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let g = ISO8601DateFormatter()
        let date = f.date(from: playedAt) ?? g.date(from: playedAt)
        guard let date else { return String(playedAt.suffix(8).prefix(5)) }
        return date.formatted(date: .omitted, time: .shortened)
    }
}

public struct SpotResult: Decodable, Equatable, Identifiable {
    public let id: Int
    public let status: String       // matched | wishlist | unknown
    public let artist: String
    public let title: String
    public let album: String
    public let links: [String: String]
    public let matchedDir: String

    enum CodingKeys: String, CodingKey {
        case id, status, artist, title, album, links
        case matchedDir = "matched_dir"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decode(Int.self, forKey: .id)) ?? 0
        status = (try? c.decode(String.self, forKey: .status)) ?? "unknown"
        artist = (try? c.decode(String.self, forKey: .artist)) ?? ""
        title = (try? c.decode(String.self, forKey: .title)) ?? ""
        album = (try? c.decode(String.self, forKey: .album)) ?? ""
        links = (try? c.decode([String: String].self, forKey: .links)) ?? [:]
        matchedDir = (try? c.decode(String.self, forKey: .matchedDir)) ?? ""
    }
}

public struct RipStatus: Decodable, Equatable {
    public let state: String
    public let album: String
    public let track: Int
    public let total: Int

    enum CodingKeys: String, CodingKey { case state, album, track, total }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        state = (try? c.decode(String.self, forKey: .state)) ?? "idle"
        album = (try? c.decode(String.self, forKey: .album)) ?? ""
        track = (try? c.decode(Int.self, forKey: .track)) ?? 0
        total = (try? c.decode(Int.self, forKey: .total)) ?? 0
    }

    public var ripping: Bool { state == "ripping" }
}

public struct Show: Decodable, Equatable {
    public let channel: String
    public let album: String
    public let tracks: [ShowTrack]
    public let playing: Int

    enum CodingKeys: String, CodingKey { case channel, album, tracks, playing }

    public init(channel: String, album: String, tracks: [ShowTrack], playing: Int = -1) {
        self.channel = channel; self.album = album; self.tracks = tracks; self.playing = playing
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        channel = (try? c.decode(String.self, forKey: .channel)) ?? ""
        album = (try? c.decode(String.self, forKey: .album)) ?? ""
        tracks = (try? c.decode([ShowTrack].self, forKey: .tracks)) ?? []
        playing = (try? c.decode(Int.self, forKey: .playing)) ?? -1
    }
}
