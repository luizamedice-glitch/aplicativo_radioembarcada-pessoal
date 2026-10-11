package br.com.radioembarcada.player

import android.os.Handler
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi

/** Every explicit resume/reconnect opens a new live source on the SAME player/session. */
@UnstableApi
internal class LiveStreamPlayback(
    private val player: Player,
    private val station: MediaItem,
    private val connected: () -> Boolean,
    private val changed: () -> Unit,
    private val diagnostic: (String) -> Unit = {},
    private val handler: Handler = Handler(player.applicationLooper),
) : Player.Listener {
    var requested = false
        private set
    var recovering = false
        private set
    private var attempt = 0
    private var scheduled = false
    private var hasPlayed = false
    private var wasOffline = false
    private var connecting = false
    private val retry = Runnable {
        scheduled = false
        if (requested && connected()) connectFresh()
        changed()
    }

    init { player.addListener(this) }

    fun play() {
        if (requested) {
            if (player.playerError != null || player.playbackState in setOf(Player.STATE_IDLE, Player.STATE_ENDED)) scheduleRecovery()
            return
        }
        requested = true
        if (connected()) connectFresh() else { wasOffline = true; recovering = true }
        changed()
    }

    fun pause() {
        requested = false
        cancelRetry()
        recovering = false
        // Close HTTP and discard the paused buffer. Play is radio-now, never a saved position.
        player.pause()
        player.stop()
        changed()
    }

    private fun connectFresh() {
        connecting = true
        try {
            player.setMediaItem(station, true)
            player.prepare()
            player.play()
            diagnostic("Live stream: fresh connection; no saved position or local programming")
        } finally { connecting = false }
    }

    fun networkChanged() {
        if (!connected()) { wasOffline = true; changed(); return } // Buffered audio may still be audible.
        if (requested && (player.playerError != null || player.playbackState in setOf(Player.STATE_IDLE, Player.STATE_ENDED) ||
                (wasOffline && player.playbackState == Player.STATE_BUFFERING))) scheduleRecovery()
        wasOffline = false
        changed()
    }

    override fun onPlayerError(error: PlaybackException) {
        diagnostic("Live stream error: ${error.errorCodeName}; causes=" +
            generateSequence<Throwable>(error) { it.cause }.take(5).joinToString { it.javaClass.simpleName })
        scheduleRecovery()
    }

    override fun onPlaybackStateChanged(playbackState: Int) {
        if (requested && playbackState == Player.STATE_ENDED) scheduleRecovery()
    }

    override fun onPlayWhenReadyChanged(playWhenReady: Boolean, reason: Int) {
        if (!playWhenReady && !connecting && requested) {
            // ExoPlayer handles audio focus/noisy. Never fight a user/call/headset pause with retries.
            requested = false
            cancelRetry()
            recovering = false
        }
    }

    override fun onEvents(player: Player, events: Player.Events) {
        if (player.isPlaying) { hasPlayed = true; recovering = false; attempt = 0; cancelRetry() }
        else if (requested && hasPlayed && player.playbackState == Player.STATE_BUFFERING) recovering = true
        changed()
    }

    private fun scheduleRecovery() {
        if (!requested || scheduled) return
        recovering = true
        if (connected()) {
            scheduled = true
            val delay = RetryPolicy.delayMillis(attempt)
            attempt = (attempt + 1).coerceAtMost(5)
            handler.postDelayed(retry, delay)
            diagnostic("Live stream retry in $delay ms; fallback disabled")
        }
        changed()
    }
    private fun cancelRetry() { handler.removeCallbacks(retry); scheduled = false }
    fun release() { requested = false; cancelRetry(); player.removeListener(this) }
}
