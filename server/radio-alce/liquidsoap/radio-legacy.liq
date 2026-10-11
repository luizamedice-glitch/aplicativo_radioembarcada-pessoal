log.stdout.set(true)
log.level.set(3)

source_password = environment.get("ICECAST_SOURCE_PASSWORD")

music = playlist("/data/music.m3u", mode="randomize", reload=30)
radio = mksafe(music)

output.icecast(
  %mp3(bitrate=128),
  host="icecast",
  port=8000,
  password=source_password,
  mount="/alce.mp3",
  name="Rádio Alce",
  description="Sua Rádio em Movimento",
  genre="Variedades",
  public=false,
  radio
)
