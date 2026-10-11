package br.com.radioembarcada.player

import android.app.Application
import android.net.Uri
import android.os.PowerManager
import androidx.media3.common.C
import androidx.media3.common.ParserException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSpec
import androidx.media3.exoplayer.source.LoadEventInfo
import androidx.media3.exoplayer.source.MediaLoadData
import androidx.media3.exoplayer.upstream.LoadErrorHandlingPolicy
import androidx.media3.test.utils.FakeMediaSource
import androidx.media3.test.utils.robolectric.RobolectricUtil.runMainLooperUntil
import java.io.IOException
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.LooperMode
import org.robolectric.shadows.ShadowPowerManager

@UnstableApi
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
@LooperMode(LooperMode.Mode.PAUSED)
class LiveStreamBackgroundTest {
    private fun error(count: Int, exception: IOException = IOException("fixture")) =
        LoadErrorHandlingPolicy.LoadErrorInfo(
            LoadEventInfo(1, DataSpec(Uri.parse("https://example.test/live.mp3")), 0),
            MediaLoadData(C.DATA_TYPE_MEDIA), exception, count)

    @Test fun transientErrorsKeepTheLiveLoaderAliveBeyondThreeFailuresWithBoundedBackoff() {
        val policy = LiveStreamLoadErrorPolicy()
        listOf(1, 2, 3, 4, 10, 100).forEach { count ->
            assertEquals(RetryPolicy.delayMillis(count - 1), policy.getRetryDelayMsFor(error(count)))
        }
        assertEquals(Int.MAX_VALUE, policy.getMinimumLoadableRetryCount(C.DATA_TYPE_MEDIA))
    }

    @Test fun invalidAudioStillReachesTheTerminalRecoveryPath() {
        val exception = ParserException.createForMalformedDataOfUnknownType("fixture", null)
        assertEquals(C.TIME_UNSET, LiveStreamLoadErrorPolicy().getRetryDelayMsFor(error(1, exception)))
    }

    @Test fun realPlayerKeepsCpuAwakeWhileBufferingWithScreenOffAndReleasesOnPause() {
        val app = RuntimeEnvironment.getApplication()
        shadowOf(app.getSystemService(PowerManager::class.java)).turnScreenOn(false)
        val player = LiveStreamPlayer.create(app)
        try {
            // No network or codec: a source deliberately waiting for preparation models rebuffering.
            val source = FakeMediaSource().apply { setAllowPreparation(false) }
            player.setMediaSource(source)
            player.prepare()
            player.play()
            runMainLooperUntil { player.playbackState == Player.STATE_BUFFERING }
            // Media3 manages locks on the playback Looper. Inspect there too: Robolectric's
            // legacy WakeLock shadow is not safe for concurrent acquire/isHeld operations.
            fun cpuLockHeld(): Boolean {
                val result = java.util.concurrent.atomic.AtomicReference<Boolean?>()
                android.os.Handler(player.playbackLooper).post {
                    result.set(ShadowPowerManager.getLatestWakeLock()?.isHeld == true)
                }
                runMainLooperUntil { result.get() != null }
                return result.get()!!
            }
            assertTrue(cpuLockHeld())
            assertTrue(player.playWhenReady)
            player.pause()
            assertFalse(cpuLockHeld())
            assertFalse(player.playWhenReady)
        } finally { player.release() }
    }

    @Test fun liveLoadingChecksAreSmallerThanTheStartupBufferAtStationBitrate() {
        val intervalAt128KbitMs = LiveStreamConfiguration.LOADING_CHECK_INTERVAL_BYTES * 1_000L / 16_000
        assertTrue(intervalAt128KbitMs < LiveStreamConfiguration.START_BUFFER_MS)
        assertTrue(LiveStreamConfiguration.READ_TIMEOUT_MS > LiveStreamConfiguration.MAX_BUFFER_MS)
    }
}
