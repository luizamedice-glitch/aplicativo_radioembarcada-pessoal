# One global signal. Only verified local requests reach the decoders; never resolve R2 on air.
log.stdout.set(true)
log.level.set(3)

source_password = environment.get("ICECAST_SOURCE_PASSWORD")
planner_url = "http://catalog:8081"

planner_unavailable = ref(false)
emergency_active = ref(false)
emergency_ready_logged = ref(false)

def planner_failed() =
  if not planner_unavailable() then
    log("Planner unavailable; using prepared/emergency audio")
    planner_unavailable.set(true)
  end
end

def next_request() =
  try
    response = http.get(timeout=2., "#{planner_url}/next")
    if response.status_code != 200 then
      planner_failed()
      null
    else
      planner_unavailable.set(false)
      uri = string.trim(response)
      if uri == "" then null else request.create(uri) end
    end
  catch err do
    ignore(err)
    planner_failed()
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
emergency = playlist(id="alce_emergency", "/data/emergency.m3u",
  mime_type="audio/x-mpegurl", mode="normal", reload=5, prefetch=2)

# Provide generic metadata even on MP3s without tags; never inherit a delivery token.
emergency = metadata.map(update=false, insert_missing=true,
  fun (_) -> [("program_type", "MUSIC"), ("radio_token", ""), ("radio_id", "")], emergency)
emergency = amplify(0.9, emergency)

def emergency_started(_track_metadata) =
  ignore(_track_metadata)
  if not emergency_active() then
    log("EMERGENCY active")
    emergency_active.set(true)
  end
end
emergency.on_track(synchronous=true, emergency_started)

def program_started(_track_metadata) =
  ignore(_track_metadata)
  if emergency_active() then
    log("EMERGENCY ended / planner resumed")
    emergency_active.set(false)
  end
end
program.on_track(synchronous=true, program_started)

# Keep source selection on the raw prepared program. Fade operators around the primary
# source can transiently report it unready at track boundaries, which makes fallback
# jump to the MUSIC-only emergency playlist and effectively hides station IDs/jingles.
radio = fallback(track_sensitive=true, [program, emergency])

# Process the already-selected global signal instead. Program requests carry metadata:
# MUSIC => 15s fade-out; station IDs/jingles/news => 0s fade-out and short fade-in.
# Emergency tracks have no fade override, so they stay continuous during real outages.
radio = amplify(override="liq_gain", 0.9, radio)
radio = fade.out(duration=0., override_duration="liq_fade_out",
  track_sensitive=true, type="sin", radio)
radio = fade.in(duration=0., override_duration="liq_fade_in",
  track_sensitive=true, type="sin", radio)

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
  if emergency.is_ready() and not emergency_ready_logged() then
    log("EMERGENCY fallback ready")
    emergency_ready_logged.set(true)
  end
  try
    ignore(http.get(timeout=2., "#{planner_url}/heartbeat"))
  catch err do
    ignore(err)
    planner_failed()
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
