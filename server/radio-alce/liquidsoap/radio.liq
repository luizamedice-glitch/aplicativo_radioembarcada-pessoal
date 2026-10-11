# One global signal. Only verified local requests reach the decoders; never resolve R2 on air.
log.stdout.set(true)
log.level.set(3)

source_password = environment.get("ICECAST_SOURCE_PASSWORD")
planner_url = "http://catalog:8081"

def next_request() =
  try
    uri = string.trim(http.get(timeout=2., "#{planner_url}/next"))
    if uri == "" then null else request.create(uri) end
  catch err do
    ignore(err)
    log("Planner unavailable; using prepared/emergency audio")
    null
  end
end

try
  ignore(http.post(timeout=2., "#{planner_url}/reset", data=""))
catch err do
    ignore(err)
  log("Planner reset unavailable; emergency audio remains available")
end

program = request.dynamic(id="alce_program", prefetch=4, retry_delay=1., next_request)
# Recheck the actual on-air clock: decoder prefetch must not announce a stale hour.
def guard_time(track_metadata) =
  deadline = float_of_string(default=0., list.assoc(default="0", "time_valid_until", track_metadata))
  if deadline > 0. and time() > deadline then
    log("TIME omitted: actual boundary conflicts with scheduled hour")
    program.skip()
  end
end
program.on_track(synchronous=true, guard_time)
# Small persistent verified MUSIC pool if planner fails. Never a second output/sequence per listener.
emergency = playlist(id="alce_emergency", "/data/emergency.m3u", mode="normal", reload=5)
radio = fallback(track_sensitive=true, [program, emergency])
radio = amplify(override="liq_gain", 0.9, radio)
# Overrides are explicit for EVERY request: MUSIC=15s, all short content=0s fade-out.
# No crossfade, early skip, trimming or overlap; pieces retain their complete duration.
radio = fade.out(duration=0., type="sin", radio)
radio = fade.in(duration=0., type="sin", radio)

def acknowledge(track_metadata) =
  token = list.assoc(default="", "radio_token", track_metadata)
  item_id = list.assoc(default="", "radio_id", track_metadata)
  if token != "" then
    try
      ignore(http.post(timeout=2., "#{planner_url}/played?token=#{token}&id=#{url.encode(item_id)}", data=""))
    catch err do
    ignore(err)
      log("Playback acknowledgement unavailable")
    end
  end
end
radio.on_track(synchronous=false, acknowledge)

def heartbeat() =
  try
    ignore(http.get(timeout=2., "#{planner_url}/heartbeat"))
  catch err do
    ignore(err)
    log("Planner heartbeat unavailable")
  end
  10.
end
thread.run.recurrent(delay=10., heartbeat)

# Keeps Icecast connected even at cold boot before any valid catalog/audio is available.
radio = mksafe(radio)
output.icecast(
  %mp3(bitrate=128), host="icecast", port=8000, password=source_password,
  mount="/alce.mp3", name="Rádio Alce", description="Sua Rádio em Movimento",
  genre="Variedades", public=false, radio
)
