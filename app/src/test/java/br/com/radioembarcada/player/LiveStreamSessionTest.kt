package br.com.radioembarcada.player

import android.os.Bundle
import androidx.media3.common.C
import androidx.media3.common.MediaMetadata
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.RenderersFactory
import androidx.media3.session.MediaController
import androidx.media3.session.MediaLibraryService.MediaLibrarySession
import androidx.media3.test.utils.FakeMediaSource
import org.robolectric.Shadows.shadowOf
import androidx.media3.test.utils.FakeClock
import androidx.media3.test.utils.FakeMediaSourceFactory
import androidx.media3.test.utils.FakeRenderer
import androidx.media3.test.utils.robolectric.RobolectricUtil.runMainLooperUntil
import androidx.media3.test.utils.robolectric.TestPlayerRunHelper.advance
import br.com.radioembarcada.RadioApplication
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.LooperMode

@UnstableApi
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = RadioApplication::class)
@LooperMode(LooperMode.Mode.PAUSED)
class LiveStreamSessionTest {
    @Test fun defaultBuildDeclaresOnlyTheStreamServiceAndDisablesLocalProviders() {
        val app = (RuntimeEnvironment.getApplication() as RadioApplication)
        assertEquals(PlaybackMode.STREAM, PlaybackMode.active)
        assertEquals(RadioService::class.java, PlaybackMode.serviceClass)
        val services = app.packageManager.getPackageInfo(app.packageName, android.content.pm.PackageManager.GET_SERVICES).services.orEmpty()
        assertEquals(listOf(RadioService::class.java.name), services.map { it.name })
        assertThrows(IllegalStateException::class.java) { app.musicProvider }
        assertThrows(IllegalStateException::class.java) { app.programming }
        assertThrows(IllegalStateException::class.java) { app.news }
    }
    @Test fun stationHasLiveIdentityArtworkAndNoFakeDurationOrTrackArtist() {
        val app = (RuntimeEnvironment.getApplication() as RadioApplication)
        val item = LiveStreamPlayer.station(app, "alce", "Rádio Alce")
        assertEquals("Rádio Alce", item.mediaMetadata.title)
        assertEquals("AO VIVO", item.mediaMetadata.artist)
        assertEquals("Sua Rádio em Movimento", item.mediaMetadata.description)
        assertEquals(RadioMediaIdentity(app).artworkUri, item.mediaMetadata.artworkUri)
        assertNull(item.mediaMetadata.durationMs)
        assertEquals(LiveStreamConfiguration.url, item.localConfiguration!!.uri.toString())
        assertEquals(1f, item.liveConfiguration.minPlaybackSpeed, 0f)
    }
    @Test fun defaultStreamIsHttpsHlsWithLiveOffset() {
        val item = LiveStreamPlayer.station(RuntimeEnvironment.getApplication(), "alce", "Rádio Alce")
        assertTrue(LiveStreamConfiguration.isHls)
        assertEquals("https", item.localConfiguration!!.uri.scheme)
        assertEquals(androidx.media3.common.MimeTypes.APPLICATION_M3U8, item.localConfiguration!!.mimeType)
        assertEquals(30_000L, item.liveConfiguration.targetOffsetMs)
    }
    @Test fun creatingStreamServiceDoesNotInitializeAnyLocalProgramming() {
        val service = Robolectric.buildService(RadioService::class.java).create()
        try {
            assertEquals(1, service.get().sessions.size)
            val app = service.get().application as RadioApplication
            assertThrows(IllegalStateException::class.java) { app.programming }
            assertThrows(IllegalStateException::class.java) { app.news }
        } finally { service.destroy() }
    }
    @Test fun serviceRemainsForegroundDuringRebufferingWithoutActivityAndReleasesAfterPause() {
        val lifecycle = Robolectric.buildService(RadioService::class.java).create()
        val service = lifecycle.get()
        // Replace the HTTP source with a source that stays BUFFERING; no Activity or network.
        val field = RadioService::class.java.getDeclaredField("player").apply { isAccessible = true }
        val player = field.get(service) as ExoPlayer
        try {
            player.setMediaSource(FakeMediaSource().apply { setAllowPreparation(false) })
            player.prepare()
            player.play()
            runMainLooperUntil { service.isPlaybackOngoing }
            assertEquals(Player.STATE_BUFFERING, player.playbackState)
            assertNotNull(shadowOf(service).lastForegroundNotification)
            player.pause()
            player.stop()
            // Media3 intentionally keeps a grace period after playback stops.
            shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofMinutes(11))
            runMainLooperUntil { !service.isPlaybackOngoing }
        } finally { lifecycle.destroy() }
    }

    @Test fun notificationAndAutoControllersKeepLiveIdentityWithoutSeekOrSkip() {
        val app = (RuntimeEnvironment.getApplication() as RadioApplication)
        val station = LiveStreamPlayer.station(app, "alce", "Rádio Alce")
        val player = ExoPlayer.Builder(app, RenderersFactory { _, _, _, _, _ -> arrayOf(FakeRenderer(C.TRACK_TYPE_AUDIO)) })
            .setMediaSourceFactory(FakeMediaSourceFactory()).setClock(FakeClock(true)).build()
        val exposed = StationSessionPlayer(player, station.mediaMetadata)
        val session = MediaLibrarySession.Builder(app, exposed, RadioSessionCallback())
            // Keep artwork identity but use a tiny bitmap fixture instead of parceling a 1280px
            // logo repeatedly through Robolectric's expensive legacy Bitmap shadow.
            .setBitmapLoader(object : androidx.media3.common.util.BitmapLoader {
                private val image = android.graphics.Bitmap.createBitmap(2, 2, android.graphics.Bitmap.Config.ARGB_8888)
                override fun supportsMimeType(mimeType: String) = true
                override fun decodeBitmap(data: ByteArray) = com.google.common.util.concurrent.Futures.immediateFuture(image)
                override fun loadBitmap(uri: android.net.Uri) = com.google.common.util.concurrent.Futures.immediateFuture(image)
            }).build()
        val controllers = mutableListOf<MediaController>()
        try {
            player.setMediaItem(station); player.prepare()
            advance(player).untilState(Player.STATE_READY)
            for (notification in listOf(false, true)) {
                val future = MediaController.Builder(app, session.token).setConnectionHints(Bundle().apply {
                    putBoolean(MediaController.KEY_MEDIA_NOTIFICATION_CONTROLLER_FLAG, notification)
                }).buildAsync()
                runMainLooperUntil { future.isDone }
                val controller = future.get().also { controllers += it }
                assertTrue(controller.isCommandAvailable(Player.COMMAND_PLAY_PAUSE))
                assertTrue(controller.isCommandAvailable(Player.COMMAND_GET_METADATA))
                listOf(Player.COMMAND_SEEK_TO_NEXT, Player.COMMAND_SEEK_TO_NEXT_MEDIA_ITEM,
                    Player.COMMAND_SEEK_TO_PREVIOUS, Player.COMMAND_SEEK_TO_PREVIOUS_MEDIA_ITEM,
                    Player.COMMAND_SEEK_IN_CURRENT_MEDIA_ITEM, Player.COMMAND_SEEK_TO_MEDIA_ITEM,
                    Player.COMMAND_SEEK_BACK, Player.COMMAND_SEEK_FORWARD).forEach {
                    assertFalse(controller.isCommandAvailable(it))
                }
                assertEquals("Rádio Alce", controller.mediaMetadata.title)
                assertEquals("AO VIVO", controller.mediaMetadata.artist)
                assertEquals(C.TIME_UNSET, controller.duration)
                assertTrue(controller.isCurrentMediaItemLive)
                controller.play(); runMainLooperUntil { player.playWhenReady }
                controller.pause(); runMainLooperUntil { !player.playWhenReady }
            }
            val received = mutableListOf<String>()
            val listener = object : Player.Listener {
                override fun onMediaMetadataChanged(mediaMetadata: MediaMetadata) { received += mediaMetadata.title.toString() }
                override fun onPlaylistMetadataChanged(mediaMetadata: MediaMetadata) { received += mediaMetadata.title.toString() }
            }
            exposed.addListener(listener)
            player.setPlaylistMetadata(MediaMetadata.Builder().setTitle("ICY music title").setArtist("ICY artist").build())
            runMainLooperUntil { received.isNotEmpty() }
            assertEquals(listOf("Rádio Alce"), received)
            assertEquals("Rádio Alce", exposed.mediaMetadata.title)
            controllers.forEach { assertEquals("Rádio Alce", it.mediaMetadata.title) }
            exposed.removeListener(listener)
        } finally { controllers.forEach { it.release() }; session.release(); player.release() }
    }
    @Test fun liveBufferIsBoundedAndStartsQuicklyWithoutOldFilePreloadSettings() {
        assertEquals(10_000, LiveStreamConfiguration.MIN_BUFFER_MS)
        assertEquals(20_000, LiveStreamConfiguration.MAX_BUFFER_MS)
        assertEquals(1_500, LiveStreamConfiguration.START_BUFFER_MS)
        assertEquals(5_000, LiveStreamConfiguration.REBUFFER_MS)
        assertTrue(LiveStreamConfiguration.MAX_BUFFER_MS < PlaybackConfiguration.MAX_BUFFER_MS)
    }
    @Test fun cleartextIsAllowedOnlyForProvisionalHost() {
        val app = (RuntimeEnvironment.getApplication() as RadioApplication)
        val resource = app.resources.getIdentifier("network_security_config", "xml", app.packageName)
        val xml = app.resources.getXml(resource)
        val domains = mutableListOf<String>()
        var basePermitted: String? = null
        while (xml.eventType != org.xmlpull.v1.XmlPullParser.END_DOCUMENT) {
            if (xml.eventType == org.xmlpull.v1.XmlPullParser.START_TAG) {
                if (xml.name == "base-config") basePermitted = xml.getAttributeValue(null, "cleartextTrafficPermitted")
                if (xml.name == "domain") domains += xml.nextText()
            }
            xml.next()
        }
        assertEquals("false", basePermitted)
        assertEquals(listOf("15.229.83.121"), domains)
        xml.close()
    }
}
