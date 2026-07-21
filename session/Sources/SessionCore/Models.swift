import Foundation

public struct Channel: Decodable, Identifiable, Equatable {
    public let slug: String
    public let name: String
    public let source: String
    public let playable: Bool
    public let isPrivate: Bool
    public let artPath: String?
    /// Set on genre stations: play as an instant on-demand mix, not a stream.
    public let mixGenre: String?

    public var id: String { slug }

    enum CodingKeys: String, CodingKey {
        case slug, name, source, playable, query
        case isPrivate = "private"
        case artPath = "art_url"
    }

    private struct Query: Decodable { let genre: String? }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        slug = (try? c.decode(String.self, forKey: .slug)) ?? ""
        name = (try? c.decode(String.self, forKey: .name)) ?? ""
        source = (try? c.decode(String.self, forKey: .source)) ?? ""
        playable = (try? c.decode(Bool.self, forKey: .playable)) ?? true
        isPrivate = (try? c.decode(Bool.self, forKey: .isPrivate)) ?? false
        artPath = try? c.decode(String.self, forKey: .artPath)
        mixGenre = (try? c.decode(Query.self, forKey: .query))?.genre
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
    public let coverPath: String?    // the track's own record sleeve (library tracks)
    public var id: String { url }

    enum CodingKeys: String, CodingKey {
        case title, artist, album, url, served
        case coverPath = "cover_url"
    }

    public init(title: String, artist: String, album: String, url: String, served: Bool = false) {
        self.title = title; self.artist = artist; self.album = album
        self.url = url; self.served = served; self.coverPath = nil
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        title = (try? c.decode(String.self, forKey: .title)) ?? ""
        artist = (try? c.decode(String.self, forKey: .artist)) ?? ""
        album = (try? c.decode(String.self, forKey: .album)) ?? ""
        url = (try? c.decode(String.self, forKey: .url)) ?? ""
        coverPath = try? c.decode(String.self, forKey: .coverPath)
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
    public let mtime: Double        // folder mtime IS "date added"
    public let genres: [String]     // the shelf's sections this record lives in

    public var id: String { dir }


    enum CodingKeys: String, CodingKey {
        case dir, artist, album, year, mtime, genres
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
        mtime = (try? c.decode(Double.self, forKey: .mtime)) ?? 0
        genres = (try? c.decode([String].self, forKey: .genres)) ?? []
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

/// One LP on the record wall — catalog only; vinyl has no audio to stream.
public struct VinylRecord: Decodable, Equatable, Identifiable {
    public let id: Int
    public let artist: String
    public let title: String
    public let year: Int?
    public let styles: [String]
    public let genres: [String]
    public let coverPath: String?

    enum CodingKeys: String, CodingKey {
        case id, artist, title, year, styles, genres
        case coverPath = "cover_url"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decode(Int.self, forKey: .id)) ?? 0
        artist = (try? c.decode(String.self, forKey: .artist)) ?? ""
        title = (try? c.decode(String.self, forKey: .title)) ?? ""
        year = try? c.decode(Int.self, forKey: .year)
        styles = (try? c.decode([String].self, forKey: .styles)) ?? []
        genres = (try? c.decode([String].self, forKey: .genres)) ?? []
        coverPath = try? c.decode(String.self, forKey: .coverPath)
    }

    public func coverURL(base: URL) -> URL? {
        guard let coverPath else { return nil }
        return URL(string: coverPath, relativeTo: base)?.absoluteURL
    }

    public var discogsURL: URL? {
        URL(string: "https://www.discogs.com/release/\(id)")
    }

    /// The wall's section membership: styles, genres as fallback.
    public var sections: [String] { styles.isEmpty ? genres : styles }
}

public struct AtticStats: Decodable, Equatable {
    public let tracks: Int
    public let albums: Int
    public let artists: Int

    enum CodingKeys: String, CodingKey { case tracks, albums, artists }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        tracks = (try? c.decode(Int.self, forKey: .tracks)) ?? 0
        albums = (try? c.decode(Int.self, forKey: .albums)) ?? 0
        artists = (try? c.decode(Int.self, forKey: .artists)) ?? 0
    }
}

public struct GenreCount: Decodable, Equatable, Identifiable {
    public let name: String
    public let count: Int
    public var id: String { name }

    enum CodingKeys: String, CodingKey { case name, count }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = (try? c.decode(String.self, forKey: .name)) ?? ""
        count = (try? c.decode(Int.self, forKey: .count)) ?? 0
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

    public let coverPath: String?
    public let shotPath: String?

    enum CodingKeys: String, CodingKey {
        case id, status, artist, title, album, links
        case matchedDir = "matched_dir"
        case coverPath = "cover_url"
        case shotPath = "image_path"
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
        coverPath = try? c.decode(String.self, forKey: .coverPath)
        shotPath = try? c.decode(String.self, forKey: .shotPath)
    }

    /// Best thumbnail: the fetched cover, else your own photo of it.
    public func thumbURL(base: URL) -> URL? {
        guard let p = coverPath ?? shotPath else { return nil }
        return URL(string: p, relativeTo: base)?.absoluteURL
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

public struct AlbumImage: Decodable, Equatable, Identifiable {
    public let type: String        // front / tracklist / back / disc / …
    public let url: String
    public var id: String { url }

    enum CodingKeys: String, CodingKey { case type, url }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        type = (try? c.decode(String.self, forKey: .type)) ?? ""
        url = (try? c.decode(String.self, forKey: .url)) ?? ""
    }

    public func imageURL(base: URL) -> URL? {
        URL(string: url, relativeTo: base)?.absoluteURL
    }
}

public struct Show: Decodable, Equatable {
    public let channel: String
    public let album: String
    public let tracks: [ShowTrack]
    public let playing: Int
    public let images: [AlbumImage]   // the record's photo strip (album shows)

    enum CodingKeys: String, CodingKey { case channel, album, tracks, playing, images }

    public init(channel: String, album: String, tracks: [ShowTrack], playing: Int = -1) {
        self.channel = channel; self.album = album; self.tracks = tracks; self.playing = playing
        self.images = []
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        channel = (try? c.decode(String.self, forKey: .channel)) ?? ""
        album = (try? c.decode(String.self, forKey: .album)) ?? ""
        tracks = (try? c.decode([ShowTrack].self, forKey: .tracks)) ?? []
        playing = (try? c.decode(Int.self, forKey: .playing)) ?? -1
        images = (try? c.decode([AlbumImage].self, forKey: .images)) ?? []
    }
}
