import Foundation

/// Thin client for the brain. The station Session is tuned to is data, not a constant
/// (the Tuner concept, level 1) — pass a new base URL and every call follows it.
public struct StationAPI {
    public var base: URL

    public init(base: URL) { self.base = base }

    public static let defaultBase = URL(string: "https://jam-station.runslab.run")!

    private func get<T: Decodable>(_ path: String, _ query: [String: String] = [:]) async throws -> T {
        var comps = URLComponents(url: base.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty {
            comps.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) }
        }
        let (data, resp) = try await URLSession.shared.data(from: comps.url!)
        guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func post(_ path: String, json: [String: Any]) async throws -> Data {
        var req = URLRequest(url: base.appendingPathComponent(path))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: json)
        let (data, _) = try await URLSession.shared.data(for: req)
        return data
    }

    public func channels() async throws -> [Channel] {
        try await get("api/channels")
    }

    public func nowPlaying(channel: String) async throws -> NowPlaying {
        try await get("api/nowplaying", ["channel": channel])
    }

    public func show(channel: String) async throws -> Show {
        try await get("api/show", ["channel": channel])
    }

    public func skip(channel: String) async throws {
        _ = try await post("api/skip", json: ["channel": channel])
    }

    // ── membership (the session cookie lives in HTTPCookieStorage and
    //    persists across launches — no token scheme, same as the web) ──

    /// THROWS on network failure — a dropped packet is not a sign-out. Only a
    /// successful response saying "user: null" means anonymous.
    public func me() async throws -> String? {
        struct Me: Decodable { let user: User? }
        struct User: Decodable { let name: String? }
        let me: Me = try await get("api/me")
        return me.user.map { $0.name ?? "member" }
    }

    /// One box: the brain tries the input as an access code, then a passphrase.
    public func signIn(code: String) async throws {
        var req = URLRequest(url: base.appendingPathComponent("api/auth/key"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["code": code])
        let (_, resp) = try await URLSession.shared.data(for: req)
        guard (resp as? HTTPURLResponse)?.statusCode == 200 else {
            throw URLError(.userAuthenticationRequired)
        }
    }

    public func signOut() async {
        _ = try? await post("api/auth/signout", json: [:])
    }

    // ── the shelf (CD source) ──

    public func albums() async throws -> [Album] {
        try await get("api/library/albums")
    }

    public func album(dir: String) async throws -> Show {
        try await get("api/library/album", ["dir": dir])
    }

    public func rip() async -> RipStatus? {
        try? await get("api/rip")
    }

    // ── the shelf's sections ──

    public func genres() async throws -> [GenreCount] {
        try await get("api/library/genres")
    }

    /// "A jazz mix from the shelf" — Show-shaped, plays on the tape deck as-is.
    public func mix(genre: String, count: Int = 30) async throws -> Show {
        try await get("api/library/mix", ["genre": genre, "count": String(count)])
    }

    public func setGenres(dir: String, genres: [String]) async {
        _ = try? await post("api/library/genre", json: ["dir": dir, "genres": genres])
    }

    // ── favourites (members; a favourite is only real if it carries a url) ──

    public func favourites() async throws -> [Fav] {
        struct Wrap: Decodable { let favourites: [Fav] }
        let w: Wrap = try await get("api/favourites")
        return w.favourites
    }

    public func addFavourite(_ f: Fav) async {
        _ = try? await post("api/favourites/add", json: [
            "url": f.url, "title": f.title, "artist": f.artist,
            "album": f.album, "channel": f.channel,
        ])
    }

    public func removeFavourite(url: String) async {
        _ = try? await post("api/favourites/remove", json: ["url": url])
    }

    // ── spot: photograph music in the wild ──

    public func spot(jpeg: Data) async throws -> SpotResult {
        let boundary = "session-spot-\(UUID().uuidString)"
        var req = URLRequest(url: base.appendingPathComponent("api/spot"))
        req.httpMethod = "POST"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data()
        body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"spot.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".utf8))
        body.append(jpeg)
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        req.httpBody = body
        req.timeoutInterval = 90        // the vision call takes its time
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard (resp as? HTTPURLResponse)?.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
        return try JSONDecoder().decode(SpotResult.self, from: data)
    }

    public func spots() async throws -> [SpotResult] {
        try await get("api/spots")
    }

    public func deleteSpot(id: Int) async {
        _ = try? await post("api/spot/delete", json: ["id": id])
    }

    // ── the play log ──

    public func history(limit: Int = 40) async throws -> [HistoryRow] {
        try await get("api/history", ["limit": String(limit)])
    }

    public func presence(channel: String, aid: String) async {
        _ = try? await post("api/presence", json: ["channel": channel, "aid": aid])
    }

    public func streamURL(slug: String) -> URL {
        base.appendingPathComponent("stream/\(slug)")
    }

    /// Track urls from /api/show are absolute for archive.org and root-relative
    /// for the brain's own /music volume — resolve either against the station.
    public func trackURL(_ raw: String) -> URL? {
        URL(string: raw, relativeTo: base)?.absoluteURL
    }
}
