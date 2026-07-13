# jam-station radio engine (liquidsoap 2.2.x — pinned via savonet/liquidsoap:v2.2.5)
#
# One Icecast mount per channel. Each channel is a dynamic queue that asks the
# brain for its next track: GET http://brain:8080/api/next?channel=<slug>
# The brain replies with an annotate: URI (title/artist/album) or empty.
#
# Channels are fetched from the brain at startup — to pick up a channel the AI
# just created, run: docker compose restart liquidsoap

settings.server.telnet := true
settings.server.telnet.bind_addr := "0.0.0.0"
settings.server.telnet.port := 1234

brain = "http://brain:8080"
icecast_pw = environment.get("ICECAST_SOURCE_PASSWORD")

def make_channel(line) =
  parts = string.split(separator="|", line)
  slug = list.nth(default="", parts, 0)
  name = list.nth(default=slug, parts, 1)

  if slug != "" then
    log("jam-station: starting channel #{slug} (#{name})")

    def next_track() =
      resp = try http.get("#{brain}/api/next?channel=#{slug}") catch _ do "" end
      uri = string.trim("#{resp}")
      if uri == "" then
        null()
      else
        request.create(uri)
      end
    end

    q = request.dynamic(id=slug, retry_delay=5., next_track)

    # report track changes back to the brain (drives the web UI's now-playing)
    def on_track(m) =
      body = json.stringify({
        channel = slug,
        title = m["title"],
        artist = m["artist"],
        album = m["album"]
      })
      ignore(try
        http.post(data=body,
                  headers=[("Content-Type", "application/json")],
                  "#{brain}/api/nowplaying")
      catch _ do
        null()
      end)
    end
    q.on_track(on_track)

    s = crossfade(fade_in=1.5, fade_out=2.5, q)
    s = mksafe(s)

    output.icecast(
      %mp3(bitrate=128),
      id="out_#{slug}",
      host="icecast", port=8000,
      password=icecast_pw,
      mount="/#{slug}",
      name=name,
      description="jam-station — personal AI radio",
      s
    )
  end
end

# fetch channel list from the brain (compose healthcheck guarantees it's up)
chan_resp = try http.get("#{brain}/api/channels.liq") catch _ do "" end
chan_body = string.trim("#{chan_resp}")

if chan_body == "" then
  log("jam-station: could not fetch channels from brain — exiting so docker restarts us")
  shutdown(code=1)
else
  lines = string.split(separator="\n", chan_body)
  list.iter(make_channel, lines)
end
