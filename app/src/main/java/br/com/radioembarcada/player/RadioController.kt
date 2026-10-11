package br.com.radioembarcada.player

import android.content.ComponentName
import android.content.Context
import android.os.Bundle
import androidx.core.content.ContextCompat
import androidx.media3.common.MediaMetadata
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import br.com.radioembarcada.model.ConnectionState
import br.com.radioembarcada.model.NowPlaying
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

@UnstableApi
class RadioController(context: Context) {
    private val mutableState = MutableStateFlow(ConnectionState.PAUSED)
    val state = mutableState.asStateFlow()
    private val mutableRequested = MutableStateFlow(false)
    val playRequested = mutableRequested.asStateFlow()
    private val mutableReady = MutableStateFlow(false)
    val ready = mutableReady.asStateFlow()
    private val mutableConnected = MutableStateFlow(true)
    val connected = mutableConnected.asStateFlow()
    private val mutableMessage = MutableStateFlow("")
    val message = mutableMessage.asStateFlow()
    private val mutableTrack = MutableStateFlow<NowPlaying?>(null)
    val nowPlaying = mutableTrack.asStateFlow()
    private var controller: MediaController? = null
    private val playerListener = object : Player.Listener {
        override fun onMediaMetadataChanged(mediaMetadata: MediaMetadata) { updateTrack(mediaMetadata) }
    }
    private val future = MediaController.Builder(context,
        SessionToken(context, ComponentName(context, PlaybackMode.serviceClass)))
        .setListener(object : MediaController.Listener {
            override fun onExtrasChanged(controller: MediaController, extras: Bundle) {
                update(extras)
            }
            override fun onDisconnected(controller: MediaController) {
                mutableReady.value = false
                mutableRequested.value = false
                mutableState.value = ConnectionState.PAUSED
                mutableMessage.value = "Programação indisponível."
            }
        }).buildAsync()

    init {
        future.addListener({
            try {
                controller = future.get().also {
                    update(it.sessionExtras)
                    updateTrack(it.mediaMetadata)
                    it.addListener(playerListener)
                }
                mutableReady.value = true
            } catch (_: Exception) {
                mutableState.value = ConnectionState.PAUSED
                mutableMessage.value = "Programação indisponível."
            }
        }, ContextCompat.getMainExecutor(context))
    }

    private fun update(extras: Bundle) {
        mutableState.value = ConnectionState.entries.firstOrNull {
            it.name == extras.getString(RadioService.STATE_KEY)
        } ?: ConnectionState.PAUSED
        mutableRequested.value = extras.getBoolean(RadioService.REQUESTED_KEY)
        mutableConnected.value = extras.getBoolean(RadioService.CONNECTED_KEY, true)
        mutableMessage.value = extras.getString(RadioService.MESSAGE_KEY).orEmpty()
    }

    private fun updateTrack(metadata: MediaMetadata) {
        mutableTrack.value = metadata.title?.toString()?.let { title ->
            NowPlaying(title, metadata.artist?.toString().orEmpty(), metadata.artworkUri?.toString(),
                metadata.durationMs, metadata.extras?.getString("license").orEmpty(),
                metadata.extras?.getString("source").orEmpty(), metadata.extras?.getString("sourceUrl").orEmpty(), metadata.artworkData)
        }
    }

    fun toggle() {
        val media = controller ?: return
        if (mutableRequested.value) media.pause() else media.play()
    }

    fun release() {
        controller?.removeListener(playerListener)
        MediaController.releaseFuture(future)
    }
}
