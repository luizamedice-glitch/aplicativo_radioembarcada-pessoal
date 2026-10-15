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

# BEGIN AUDIO TRANSITIONS
log("AUDIO pipeline=clock-envelope-v1; measured cues; no overlap")
# The planner measured decoded duration/cue points before enqueueing this request.
# Use that duration and the source clock, not an estimated remaining-time trigger.
# Only volume changes: no skip, sleep, network I/O, overlap or track replacement.
track_started_at = ref(0.)
track_duration = ref(0.)
track_gain = ref(0.9)
track_fade_out = ref(0.)
track_fade_in = ref(0.)
track_fade_floor = ref(0.03)

def start_envelope(m) =
  track_started_at.set(program.time())
  track_duration.set(max(0., float_of_string(default=0., m["radio_duration"])))
  track_gain.set(max(0., min(1., float_of_string(default=0.9, m["liq_gain"]))))
  # Defensive type check: an insert can NEVER inherit a MUSIC fade-out.
  track_fade_out.set(
    if m["program_type"] == "MUSIC" then
      max(0., min(track_duration() / 2., float_of_string(default=15., m["liq_fade_out"])))
    else 0. end)
  track_fade_in.set(max(0., min(0.3, float_of_string(default=0., m["liq_fade_in"]))))
  track_fade_floor.set(max(0.01, min(1., float_of_string(default=0.03, m["radio_fade_floor"]))))
  kind = m["program_type"]
  log("AUDIO envelope type=#{kind} duration=#{track_duration()}s fade_out=#{track_fade_out()}s gain=#{track_gain()}")
end
program.on_track(synchronous=true, start_envelope)

def envelope_gain() =
  elapsed = max(0., program.time() - track_started_at())
  remaining = max(0., track_duration() - elapsed)
  entrance = if track_fade_in() > 0. then min(1., elapsed / track_fade_in()) else 1. end
  exit_gain =
    if track_fade_out() > 0. and remaining < track_fade_out() then
      track_fade_floor() + (1. - track_fade_floor()) * sin(1.5707963267948966 * remaining / track_fade_out())
    else 1. end
  track_gain() * entrance * exit_gain
end
program = amplify(override=null, envelope_gain, program)
# END AUDIO TRANSITIONS
radio = fallback(track_sensitive=true, [program, emergency])

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
