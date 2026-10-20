package br.com.radioembarcada.player

import androidx.media3.common.util.UnstableApi
import androidx.media3.session.MediaLibraryService
import br.com.radioembarcada.BuildConfig

/** A build exposes exactly one service; a stream failure never selects the fallback. */
enum class PlaybackMode {
    STREAM, LOCAL_FALLBACK;
    companion object {
        val active: PlaybackMode get() = valueOf(BuildConfig.PLAYBACK_MODE)
        @get:UnstableApi val serviceClass: Class<out MediaLibraryService> get() =
            if (active == STREAM) RadioService::class.java else LocalFallbackRadioService::class.java
    }
}

object LiveStreamConfiguration {
    val url: String get() = BuildConfig.RADIO_STREAM_URL
    val isHls: Boolean get() = java.net.URI(url).path.endsWith(".m3u8", ignoreCase = true)
    const val HLS_TARGET_OFFSET_MS = 30_000L
    const val MIN_BUFFER_MS = 10_000
    const val MAX_BUFFER_MS = 20_000
    const val START_BUFFER_MS = 1_500
    const val REBUFFER_MS = 5_000
    // 16 KiB is approximately one second at the station's 128 kbit/s.
    const val LOADING_CHECK_INTERVAL_BYTES = 16 * 1024
    const val READ_TIMEOUT_MS = 30_000
}
