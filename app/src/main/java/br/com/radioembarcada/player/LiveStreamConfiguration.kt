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
    const val MIN_BUFFER_MS = 5_000
    const val MAX_BUFFER_MS = 15_000
    const val START_BUFFER_MS = 1_500
    const val REBUFFER_MS = 3_000
    const val SOURCE_RETRY_LIMIT = 3
}
