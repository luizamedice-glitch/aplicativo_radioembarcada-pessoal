package br.com.radioembarcada.player

import android.content.Context
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.ForwardingPlayer
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.MimeTypes
import androidx.media3.common.Timeline
import androidx.media3.exoplayer.source.ForwardingTimeline
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import androidx.media3.exoplayer.upstream.LoadErrorHandlingPolicy

/** No catalogue, queue, transition envelope, audio disk cache or saved live position. */
@UnstableApi
internal object LiveStreamPlayer {
    fun station(context: Context, id: String, name: String): MediaItem = MediaItem.Builder()
        .setMediaId(id).setUri(LiveStreamConfiguration.url).setMimeType(MimeTypes.AUDIO_MPEG)
        .setLiveConfiguration(MediaItem.LiveConfiguration.Builder().setMinPlaybackSpeed(1f).setMaxPlaybackSpeed(1f).build())
        .setMediaMetadata(RadioMediaIdentity(context, name).applyTo(MediaMetadata.Builder())
            .setTitle(name).setDisplayTitle(name).setArtist("AO VIVO")
            .setDescription(context.getString(br.com.radioembarcada.R.string.radio_tagline))
            .setIsBrowsable(false).setIsPlayable(true)
            .setMediaType(MediaMetadata.MEDIA_TYPE_RADIO_STATION).build())
        .build()

    fun create(context: Context): ExoPlayer {
        val http = DefaultHttpDataSource.Factory()
            .setUserAgent("RadioAlce/" + br.com.radioembarcada.BuildConfig.VERSION_NAME)
            .setConnectTimeoutMs(PlaybackConfiguration.CONNECT_TIMEOUT_MS)
            .setReadTimeoutMs(PlaybackConfiguration.READ_TIMEOUT_MS)
        val sources = ProgressiveMediaSource.Factory(http, radioExtractors())
            .setContinueLoadingCheckIntervalBytes(PlaybackConfiguration.LOADING_CHECK_INTERVAL_BYTES)
            .setLoadErrorHandlingPolicy(LiveStreamLoadErrorPolicy())
        return ExoPlayer.Builder(context).setMediaSourceFactory(sources)
            .setLoadControl(DefaultLoadControl.Builder().setBufferDurationsMs(
                LiveStreamConfiguration.MIN_BUFFER_MS, LiveStreamConfiguration.MAX_BUFFER_MS,
                LiveStreamConfiguration.START_BUFFER_MS, LiveStreamConfiguration.REBUFFER_MS)
                .setPrioritizeTimeOverSizeThresholds(true).setBackBuffer(0, false).build())
            .build().apply {
                setAudioAttributes(AudioAttributes.Builder().setUsage(C.USAGE_MEDIA)
                    .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC).build(), true)
                setHandleAudioBecomingNoisy(true)
                setWakeMode(C.WAKE_MODE_NETWORK)
            }
    }
}

/** Brief in-place loader retries, then reconnect from the current Icecast signal. */
@UnstableApi
internal class LiveStreamLoadErrorPolicy : RadioLoadErrorPolicy(finiteRetries = true) {
    override fun getRetryDelayMsFor(loadErrorInfo: LoadErrorHandlingPolicy.LoadErrorInfo): Long =
        if (loadErrorInfo.errorCount >= LiveStreamConfiguration.SOURCE_RETRY_LIMIT) C.TIME_UNSET
        else super.getRetryDelayMsFor(loadErrorInfo)
}

/** Suppress ICY/ID3 presentation even if a decoder later reports track metadata. */
@UnstableApi
internal open class StationSessionPlayer(player: Player, private val identity: MediaMetadata) : ForwardingPlayer(player) {
    private val listeners = mutableMapOf<Player.Listener, Player.Listener>()
    override fun getMediaMetadata(): MediaMetadata = identity
    override fun getPlaylistMetadata(): MediaMetadata = identity
    override fun getDuration(): Long = C.TIME_UNSET
    override fun getContentDuration(): Long = C.TIME_UNSET
    override fun isCurrentMediaItemLive(): Boolean = true
    override fun isCurrentMediaItemSeekable(): Boolean = false
    override fun getAvailableCommands(): Player.Commands = RadioSessionCallback.allowedCommands(super.getAvailableCommands())
    override fun isCommandAvailable(command: Int): Boolean = availableCommands.contains(command)
    override fun getCurrentTimeline(): Timeline {
        val original = super.getCurrentTimeline()
        if (original.isEmpty) return original
        return object : ForwardingTimeline(original) {
            override fun getWindow(index: Int, window: Timeline.Window, defaultPositionProjectionUs: Long): Timeline.Window =
                super.getWindow(index, window, defaultPositionProjectionUs).apply {
                    durationUs = C.TIME_UNSET
                    isSeekable = false
                    isDynamic = true
                    mediaItem = mediaItem.buildUpon().setMediaMetadata(identity).build()
                    liveConfiguration = mediaItem.liveConfiguration
                }
        }
    }
    override fun addListener(listener: Player.Listener) {
        if (listener in listeners) return
        val fixed = object : Player.Listener by listener {
            override fun onMediaMetadataChanged(mediaMetadata: MediaMetadata) { listener.onMediaMetadataChanged(identity) }
            override fun onPlaylistMetadataChanged(mediaMetadata: MediaMetadata) { listener.onPlaylistMetadataChanged(identity) }
            override fun onAvailableCommandsChanged(availableCommands: Player.Commands) {
                listener.onAvailableCommandsChanged(RadioSessionCallback.allowedCommands(availableCommands))
            }
            override fun onTimelineChanged(timeline: Timeline, reason: Int) { listener.onTimelineChanged(currentTimeline, reason) }
            override fun onEvents(player: Player, events: Player.Events) { listener.onEvents(this@StationSessionPlayer, events) }
        }
        listeners[listener] = fixed
        super.addListener(fixed)
    }
    override fun removeListener(listener: Player.Listener) { listeners.remove(listener)?.let { super.removeListener(it) } }
}
