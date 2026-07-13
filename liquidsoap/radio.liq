# jam-station radio engine (liquidsoap 2.2.x — pinned via savonet/liquidsoap:v2.2.5)
#
# One Icecast mount per channel. Each channel is a dynamic queue that asks the
# brain for its next track: GET http://brain:8080/api/next?channel=<slug>
# The brain replies with an annotate: URI (title/artist/album) or empty.
#
# Channels are fetched from the brain at startup. A channel created later is
# picked up automatically: we watch the list and restart ourselves (see bottom).

settings.server.telnet := true
settings.server.telnet.bind_addr := "0.0.0.0"
settings.server.telnet.port := 1234

# Hosts are env-overridable so the same script runs under docker-compose
# (defaults) and slab (wires set BRAIN_URL / ICECAST_HOST).
brain = environment.get(default="http://brain:8080", "BRAIN_URL")
icecast_host = environment.get(default="icecast", "ICECAST_HOST")
icecast_pw = environment.get("ICECAST_SOURCE_PASSWORD")

def make_channel(line) =
  # NB: separator is a regex — "|" alone is alternation and splits every char
  parts = string.split(separator="\\|", line)
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
      host=icecast_host, port=8000,
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

# A channel needs its own icecast mount, and mounts can only be opened at
# startup — so a channel the DJ creates while we're running is inaudible until
# we boot again. Watch the list and exit when it changes; the container's
# restart policy brings us straight back with the new mounts. Same trick as the
# brain-unreachable path above: let the supervisor do the restarting.
def watch_channels() =
  resp = try http.get("#{brain}/api/channels.liq") catch _ do "" end
  body = string.trim("#{resp}")
  if body != "" and body != chan_body then
    log("jam-station: channel list changed — restarting to open the new mounts")
    shutdown(code=1)
  end
end

thread.run(delay=30., every=30., watch_channels)
