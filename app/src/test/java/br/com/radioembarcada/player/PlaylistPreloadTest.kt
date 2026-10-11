package br.com.radioembarcada.player

import android.app.Application
import android.os.Bundle
import androidx.media3.common.*
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.RenderersFactory
import androidx.media3.exoplayer.source.MediaSource
import androidx.media3.test.utils.*
import androidx.media3.test.utils.robolectric.TestPlayerRunHelper.advance
import br.com.radioembarcada.model.ProgramItem
import br.com.radioembarcada.model.ProgramItemType
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.LooperMode

@UnstableApi
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
@LooperMode(LooperMode.Mode.PAUSED)
class PlaylistPreloadTest {
    @Test fun editorialBlockHasRealPreparedIntroAndDropBeforeMusicEnds() {
        val items = listOf(program("music", ProgramItemType.MUSIC, 60_000),
            program("news-intro", ProgramItemType.NEWS_INTRO, 9_000),
            program("news-drop", ProgramItemType.NEWS_DROP, 90_000),
            program("following-music", ProgramItemType.MUSIC, 60_000))
        val readiness = PlaybackReadiness()
        val control = RadioLoadControl(playlistPreload = true).apply { currentAudio = readiness::get }
        val player = ExoPlayer.Builder(RuntimeEnvironment.getApplication(),
            RenderersFactory { _, _, _, _, _ -> arrayOf(FakeRenderer(C.TRACK_TYPE_AUDIO)) })
            .setClock(FakeClock(true)).setLoadControl(control).build()
        player.addListener(object : Player.Listener {
            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) { control.currentMediaId = mediaItem?.mediaId }
        })
        try {
            player.setPreloadConfiguration(ExoPlayer.PreloadConfiguration(45_000_000))
            player.setMediaSources(items.map { readiness.observe(source(it)) }); player.prepare()
            advance(player).untilState(Player.STATE_READY)
            player.play(); advance(player).untilPosition(0, 1_000)
            player.pause(); advance(player).untilPendingCommandsAreFullyHandled()
            assertEquals("music", player.currentMediaItem?.mediaId)
            assertTrue("Intro deve ter MediaPeriod/trilha/buffer: ${readiness.get("news-intro")}", readiness.get("news-intro").ready)
            assertTrue("Drop deve ter MediaPeriod/trilha/buffer: ${readiness.get("news-drop")}", readiness.get("news-drop").ready)
            assertTrue("Música seguinte deve ter preload iniciado", readiness.get("following-music").started)
        } finally { player.release() }
    }

    private fun program(id: String, type: ProgramItemType, duration: Long) =
        ProgramItem(id, type, id, "https://example.invalid/$id", duration)

    private fun source(item: ProgramItem): MediaSource {
        val media = MediaItem.Builder().setMediaId(item.id).setUri(item.audioUrl)
            .setMediaMetadata(MediaMetadata.Builder().setExtras(Bundle().apply {
                putString("programType", item.type.name)
            }).build()).build()
        val timeline = FakeTimeline(FakeTimeline.TimelineWindowDefinition(
            1, item.id, true, false, false, false, item.durationMs * 1_000, 0, 0,
            listOf(AdPlaybackState.NONE), media))
        return FakeMediaSource(timeline, Format.Builder().setSampleMimeType(MimeTypes.AUDIO_RAW)
            .setSampleRate(44_100).setChannelCount(2).setPcmEncoding(C.ENCODING_PCM_16BIT).build())
    }

    @Test fun nextInsertHasSelectedBufferedSamplesBeforeMusicEndsAndPauseDoesNotClearThem() {
        val items = listOf(program("music1", ProgramItemType.MUSIC, 60_000),
            program("station", ProgramItemType.STATION_ID, 8_000),
            program("music2", ProgramItemType.MUSIC, 60_000),
            program("jingle", ProgramItemType.JINGLE, 12_000),
            program("music3", ProgramItemType.MUSIC, 60_000)) + (2..7).flatMap {
                listOf(program("station$it", ProgramItemType.STATION_ID, 8_000),
                    program("following-music-$it", ProgramItemType.MUSIC, 60_000))
            }
        val readiness = PlaybackReadiness()
        assertFalse(readiness.get("station").ready) // URL/objeto não significam áudio preparado.
        val control = RadioLoadControl(playlistPreload = true).apply { currentAudio = readiness::get }
        val player = ExoPlayer.Builder(RuntimeEnvironment.getApplication(),
            RenderersFactory { _, _, _, _, _ -> arrayOf(FakeRenderer(C.TRACK_TYPE_AUDIO)) })
            .setClock(FakeClock(true)).setLoadControl(control).build()
        val logs = mutableListOf<String>()
        var endedCount = 0
        val transitions = mutableListOf<String?>()
        val ends = mutableMapOf<String?, Long>()
        player.addListener(object : Player.Listener {
            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
                control.currentMediaId = mediaItem?.mediaId
                if (reason == Player.MEDIA_ITEM_TRANSITION_REASON_AUTO) transitions += mediaItem?.mediaId
            }
            override fun onPlaybackStateChanged(playbackState: Int) {
                if (playbackState == Player.STATE_ENDED) endedCount++
            }
            override fun onPositionDiscontinuity(oldPosition: Player.PositionInfo, newPosition: Player.PositionInfo, reason: Int) {
                if (reason == Player.DISCONTINUITY_REASON_AUTO_TRANSITION) {
                    ends[oldPosition.mediaItem?.mediaId] = oldPosition.positionMs
                    assertEquals(0L, newPosition.positionMs)
                }
            }
        })
        val envelope = AudioTransitionController(player,
            current = { items.find { it.id == player.currentMediaItem?.mediaId } },
            next = { items.getOrNull(player.currentMediaItemIndex + 1) },
            readiness = { readiness.get(it.id) }, diagnostic = logs::add)
        try {
            player.setPreloadConfiguration(ExoPlayer.PreloadConfiguration(45_000_000))
            player.setMediaSources(items.map { readiness.observe(source(it)) })
            assertEquals("station", player.getMediaItemAt(1).mediaId)
            assertFalse(readiness.get("station").ready) // Timeline ainda não preparou MediaPeriod.
            player.prepare()
            advance(player).untilState(Player.STATE_READY)
            player.play()
            advance(player).untilPosition(0, 1_000)
            player.pause()
            advance(player).untilPendingCommandsAreFullyHandled()
            assertTrue("Estado real: ${readiness.get("station")}", readiness.get("station").ready)
            val actual = readiness.get("station")
            assertTrue(actual.started && actual.prepared && actual.selected)
            assertTrue(actual.bufferedUs == C.TIME_END_OF_SOURCE || actual.bufferedUs >= 1_500_000)
            assertEquals("music1", player.currentMediaItem?.mediaId)
            assertEquals(0, endedCount)
            assertTrue(readiness.get("station").ready)
            // Inspect real selected/buffered samples before each safe boundary. Timer log
            // delivery is asynchronous and is not proof that a MediaPeriod is ready.
            val insertsPreparedBeforeBoundary = mutableSetOf<String>()
            for (index in items.indices) {
                val following = items.getOrNull(index + 1) ?: continue
                if (items[index].type != ProgramItemType.MUSIC) continue
                player.play()
                advance(player).untilPosition(index, items[index].durationMs - 14_000)
                player.pause()
                advance(player).untilPendingCommandsAreFullyHandled()
                assertTrue("Peça ${following.id} deve estar preparada antes do fim: ${readiness.get(following.id)}",
                    readiness.get(following.id).ready)
                insertsPreparedBeforeBoundary += following.id
            }
            player.play()
            advance(player).untilState(Player.STATE_ENDED)
            assertEquals(items.drop(1).map { it.id }, transitions)
            assertEquals(8_000L, ends["station"])
            assertEquals(12_000L, ends["jingle"])
            assertEquals(1, endedCount) // Nenhum STATE_ENDED/prepare entre MUSIC e INSERT.
            assertTrue(logs.any { "Next MediaItem in timeline: true" in it && "Next ready for immediate playback: true" in it })
            for (id in listOf("station") + (2..7).map { "station$it" }) {
                assertEquals(8_000L, ends[id])
                assertTrue("Peça $id deve usar o mesmo preload real", id in insertsPreparedBeforeBoundary)
            }
        } finally { envelope.release(); player.release() }
        assertFalse(readiness.get("station").ready) // Buffer liberado não fica marcado ready.
    }

    @Test fun readinessRequiresRealPreparationTrackSelectionAndEnoughAudio() {
        assertFalse(PlaybackReadiness.Snapshot(started = true).ready)
        assertFalse(PlaybackReadiness.Snapshot(true, true, false, 45_000_000).ready)
        assertFalse(PlaybackReadiness.Snapshot(true, true, true, 100_000).ready)
        assertTrue(PlaybackReadiness.Snapshot(true, true, true, 1_500_000).ready)
        assertTrue(PlaybackReadiness.Snapshot(true, true, true, C.TIME_END_OF_SOURCE).ready)
    }
}
