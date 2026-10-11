package br.com.radioembarcada.player

import android.app.PendingIntent
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.session.LibraryResult
import androidx.media3.session.MediaLibraryService
import androidx.media3.session.MediaSession
import androidx.media3.session.SessionError
import br.com.radioembarcada.BuildConfig
import br.com.radioembarcada.RadioApplication
import br.com.radioembarcada.model.ConnectionState
import br.com.radioembarcada.network.NetworkMonitor
import br.com.radioembarcada.ui.MainActivity
import com.google.common.collect.ImmutableList
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture

/** Receives the central station only. Local programming is a separate, opt-in build/service. */
@UnstableApi
class RadioService : MediaLibraryService() {
    private lateinit var player: ExoPlayer
    private lateinit var session: MediaLibrarySession
    private lateinit var network: NetworkMonitor
    private lateinit var playback: LiveStreamPlayback
    private lateinit var station: MediaItem
    private val handler = Handler(Looper.getMainLooper())

    override fun onCreate() {
        super.onCreate()
        check(PlaybackMode.active == PlaybackMode.STREAM)
        val tenant = (application as RadioApplication).tenants.activeTenant
        station = LiveStreamPlayer.station(this, tenant.clientId, tenant.radioName)
        player = LiveStreamPlayer.create(this)
        network = NetworkMonitor(this, handler) { playback.networkChanged() }
        playback = LiveStreamPlayback(player, station, { network.isConnected }, ::publishState,
            { if (BuildConfig.DEBUG) Log.d("RadioDiagnostics", it) })
        val exposedPlayer = object : StationSessionPlayer(player, station.mediaMetadata) {
            override fun play() { playback.play() }
            override fun setPlayWhenReady(playWhenReady: Boolean) {
                if (playWhenReady) playback.play() else playback.pause()
            }
            override fun pause() { playback.pause() }
            override fun stop() { playback.pause() }
        }
        session = MediaLibrarySession.Builder(this, exposedPlayer, LibraryCallback())
            .setSessionActivity(PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)).build()
        addSession(session)
        network.start()
        publishState()
    }

    private fun publishState() {
        if (!::session.isInitialized || !::playback.isInitialized) return
        val state = ConnectionState.resolve(playback.requested, network.isConnected, player.isPlaying,
            player.playbackSuppressionReason != Player.PLAYBACK_SUPPRESSION_REASON_NONE,
            playback.recovering || player.playerError != null)
        session.setSessionExtras(Bundle().apply {
            putString(STATE_KEY, state.name)
            putBoolean(REQUESTED_KEY, playback.requested)
            putBoolean(CONNECTED_KEY, network.isConnected)
            putString(MESSAGE_KEY, "") // Technical details only in DEBUG logs.
        })
    }

    override fun onUpdateNotification(session: MediaSession, startInForegroundRequired: Boolean) {
        super.onUpdateNotification(session, startInForegroundRequired)
        if (BuildConfig.DEBUG) Log.d("RadioDiagnostics",
            "Live service: foregroundRequired=$startInForegroundRequired; " +
                "state=${player.playbackState}; requested=${playback.requested}; " +
                "playing=${player.isPlaying}; loading=${player.isLoading}; " +
                "bufferedMs=${player.totalBufferedDuration}")
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaLibrarySession = session
    override fun onTaskRemoved(rootIntent: Intent?) { if (!playback.requested) stopSelf() }
    override fun onDestroy() {
        network.stop()
        playback.release()
        handler.removeCallbacksAndMessages(null)
        session.release()
        player.release()
        super.onDestroy()
    }

    private inner class LibraryCallback : RadioSessionCallback() {
        override fun onGetLibraryRoot(session: MediaLibrarySession, browser: MediaSession.ControllerInfo,
            params: LibraryParams?): ListenableFuture<LibraryResult<MediaItem>> =
            Futures.immediateFuture(LibraryResult.ofItem(root(), params))
        override fun onGetChildren(session: MediaLibrarySession, browser: MediaSession.ControllerInfo,
            parentId: String, page: Int, pageSize: Int, params: LibraryParams?):
            ListenableFuture<LibraryResult<ImmutableList<MediaItem>>> = Futures.immediateFuture(
                if (parentId != ROOT_ID) LibraryResult.ofError(SessionError.ERROR_BAD_VALUE)
                else LibraryResult.ofItemList(if (page == 0) listOf(station) else emptyList(), params))
        override fun onGetItem(session: MediaLibrarySession, browser: MediaSession.ControllerInfo,
            mediaId: String): ListenableFuture<LibraryResult<MediaItem>> = Futures.immediateFuture(
                when (mediaId) {
                    ROOT_ID -> LibraryResult.ofItem(root(), null)
                    station.mediaId -> LibraryResult.ofItem(station, null)
                    else -> LibraryResult.ofError(SessionError.ERROR_BAD_VALUE)
                })
        override fun onPlaybackResumption(session: MediaSession, controller: MediaSession.ControllerInfo):
            ListenableFuture<MediaSession.MediaItemsWithStartPosition> = currentSignal()
        override fun onSetMediaItems(session: MediaSession, controller: MediaSession.ControllerInfo,
            mediaItems: List<MediaItem>, startIndex: Int, startPositionMs: Long):
            ListenableFuture<MediaSession.MediaItemsWithStartPosition> =
            if (mediaItems.size == 1 && mediaItems[0].mediaId == station.mediaId) currentSignal()
            else Futures.immediateFailedFuture(IllegalArgumentException("Estação desconhecida"))
        override fun onAddMediaItems(session: MediaSession, controller: MediaSession.ControllerInfo,
            mediaItems: List<MediaItem>): ListenableFuture<List<MediaItem>> =
            Futures.immediateFailedFuture(UnsupportedOperationException("Estação ao vivo"))
        private fun currentSignal(): ListenableFuture<MediaSession.MediaItemsWithStartPosition> =
            Futures.immediateFuture(MediaSession.MediaItemsWithStartPosition(listOf(station), 0, C.TIME_UNSET))
    }

    private fun root(): MediaItem = MediaItem.Builder().setMediaId(ROOT_ID)
        .setMediaMetadata(MediaMetadata.Builder().setTitle("Rádio Alce")
            .setIsBrowsable(true).setIsPlayable(false)
            .setMediaType(MediaMetadata.MEDIA_TYPE_FOLDER_RADIO_STATIONS).build()).build()

    companion object {
        const val STATE_KEY = "connectionState"
        const val REQUESTED_KEY = "playRequested"
        const val CONNECTED_KEY = "connected"
        const val MESSAGE_KEY = "message"
        private const val ROOT_ID = "radio_root"
    }
}
