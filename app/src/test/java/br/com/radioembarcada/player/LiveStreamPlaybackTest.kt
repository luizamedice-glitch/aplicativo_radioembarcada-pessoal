package br.com.radioembarcada.player

import android.app.Application
import android.os.Looper
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.FlagSet
import androidx.media3.common.util.UnstableApi
import androidx.media3.test.utils.StubPlayer
import java.time.Duration
import org.junit.Assert.*
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.LooperMode

@UnstableApi
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
@LooperMode(LooperMode.Mode.PAUSED)
class LiveStreamPlaybackTest {
    private lateinit var player: RecordingPlayer
    private lateinit var radio: LiveStreamPlayback
    private var connected = true
    private val error = PlaybackException("fixture", null, PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_FAILED)
    private val station get() = LiveStreamPlayer.station(RuntimeEnvironment.getApplication(), "alce", "Rádio Alce")
    @Before fun setUp() {
        player = RecordingPlayer()
        radio = LiveStreamPlayback(player, station, { connected }, {})
    }
    @After fun tearDown() { radio.release() }

    @Test fun playOpensOnlyTheConfiguredStreamAtFreshPosition() {
        radio.play()
        assertTrue(radio.requested)
        assertTrue(player.playWhenReady)
        assertEquals(listOf(station), player.media)
        assertEquals(LiveStreamConfiguration.url, player.media.single().localConfiguration!!.uri.toString())
        assertEquals(listOf(true), player.resets)
        assertEquals(1, player.prepares)
    }
    @Test fun pauseClosesLoadingAndResumeDoesNotRestoreAnOldPosition() {
        radio.play(); player.position = 123_000
        radio.pause()
        assertFalse(radio.requested); assertFalse(player.playWhenReady)
        assertEquals(1, player.stops)
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofHours(1))
        radio.play()
        assertEquals(0L, player.position)
        assertEquals(listOf(true, true), player.resets)
    }
    @Test fun repeatedPlayWhileConnectingDoesNotCreateDuplicateConnections() {
        radio.play(); radio.play(); radio.play()
        assertEquals(1, player.prepares)
    }
    @Test fun newInstanceAlwaysStartsAtCurrentSignalWithoutReadingQueueOrHistory() {
        radio.play(); player.position = 180_000; radio.release()
        radio = LiveStreamPlayback(player, station, { connected }, {})
        radio.play()
        assertEquals(0L, player.position)
        assertEquals(2, player.prepares)
    }
    @Test fun networkErrorsReconnectToSameStreamWithCappedExponentialBackoff() {
        radio.play()
        val waits = listOf(1L, 2L, 4L, 8L, 16L, 32L, 32L)
        waits.forEachIndexed { index, seconds ->
            radio.onPlayerError(error)
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(seconds * 1_000 - 1))
            assertEquals(index + 1, player.prepares)
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(1))
            assertEquals(index + 2, player.prepares)
            assertEquals(listOf(station), player.media)
        }
        assertEquals(PlaybackMode.STREAM, PlaybackMode.active)
    }
    @Test fun offlineDoesNotDiscardAudibleBufferAndReturnRecoversAStalledStream() {
        radio.play(); player.playing()
        connected = false; radio.networkChanged()
        assertEquals(0, player.stops); assertTrue(player.playWhenReady)
        player.state = Player.STATE_BUFFERING
        connected = true; radio.networkChanged()
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1))
        assertEquals(2, player.prepares)
        assertEquals(0, player.stops)
    }
    @Test fun healthyWifiMobileSwapDoesNotResetThePlayer() {
        radio.play(); player.playing()
        radio.networkChanged(); radio.networkChanged()
        assertEquals(1, player.prepares)
    }
    @Test fun openingOfflineWaitsForNetworkWithoutActivatingLocalProgramming() {
        connected = false; radio.play()
        assertTrue(radio.requested); assertEquals(0, player.prepares)
        connected = true; radio.networkChanged()
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1))
        assertEquals(1, player.prepares)
    }
    @Test fun pauseCancelsPendingRetriesAndNetworkReturnCannotRestartAudio() {
        radio.play(); radio.onPlayerError(error); radio.pause()
        radio.networkChanged()
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMinutes(2))
        assertFalse(radio.requested); assertEquals(1, player.prepares)
    }
    @Test fun focusOrHeadsetPauseIsRespectedWithoutAutomaticRetry() {
        radio.play()
        player.setPlayWhenReady(false)
        radio.onPlayerError(error)
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMinutes(1))
        assertFalse(radio.requested); assertEquals(1, player.prepares)
    }
    @Test fun streamEndReconnectsRatherThanAdvancingToLocalItems() {
        radio.play(); radio.onPlaybackStateChanged(Player.STATE_ENDED)
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1))
        assertEquals(2, player.prepares); assertEquals(1, player.media.size)
    }
    @Test fun audioKeepsPlayingWhenNoUiControllerIsAttached() {
        radio.play(); player.playing()
        assertTrue(player.isPlaying)
        assertTrue(radio.requested)
    }

    private class RecordingPlayer : StubPlayer() {
        var media = emptyList<MediaItem>()
        val resets = mutableListOf<Boolean>()
        var prepares = 0; var stops = 0
        var position = 0L
        var state = Player.STATE_IDLE
        private var requested = false
        private val listeners = mutableListOf<Player.Listener>()
        override fun getApplicationLooper(): Looper = Looper.getMainLooper()
        override fun addListener(listener: Player.Listener) { listeners += listener }
        override fun removeListener(listener: Player.Listener) { listeners -= listener }
        override fun getPlaybackState() = state
        override fun getPlaybackSuppressionReason() = Player.PLAYBACK_SUPPRESSION_REASON_NONE
        override fun getPlayerError(): PlaybackException? = null
        override fun getPlayWhenReady() = requested
        override fun setPlayWhenReady(playWhenReady: Boolean) {
            val changed = requested != playWhenReady
            requested = playWhenReady
            if (changed) listeners.toList().forEach { it.onPlayWhenReadyChanged(playWhenReady, Player.PLAY_WHEN_READY_CHANGE_REASON_USER_REQUEST) }
        }
        override fun setMediaItems(mediaItems: List<MediaItem>, resetPosition: Boolean) {
            media = mediaItems; resets += resetPosition
            if (resetPosition) position = 0
        }
        override fun prepare() { prepares++; state = Player.STATE_BUFFERING }
        override fun stop() { stops++; state = Player.STATE_IDLE }
        override fun getCurrentPosition() = position
        fun playing() {
            state = Player.STATE_READY
            listeners.toList().forEach { it.onEvents(this, Player.Events(FlagSet.Builder().add(Player.EVENT_IS_PLAYING_CHANGED).build())) }
        }
    }
}
