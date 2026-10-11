package br.com.radioembarcada.player

import android.app.PendingIntent
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import br.com.radioembarcada.BuildConfig
import androidx.core.content.ContextCompat
import androidx.media3.common.C
import androidx.media3.common.ForwardingPlayer
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.LibraryResult
import androidx.media3.session.MediaLibraryService
import androidx.media3.session.MediaSession
import androidx.media3.session.SessionError
import br.com.radioembarcada.RadioApplication
import br.com.radioembarcada.data.music.MusicProviderException
import br.com.radioembarcada.model.ConnectionState
import br.com.radioembarcada.model.ProgramItem
import br.com.radioembarcada.model.ProgramItemType
import br.com.radioembarcada.news.NewsConfiguration
import br.com.radioembarcada.network.NetworkMonitor
import br.com.radioembarcada.programming.ProgrammingConfiguration
import br.com.radioembarcada.ui.MainActivity
import com.google.common.collect.ImmutableList
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import com.google.common.util.concurrent.MoreExecutors
import com.google.common.util.concurrent.SettableFuture
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

@UnstableApi
class LocalFallbackRadioService : MediaLibraryService() {
    private lateinit var engine: ProgramPlayer
    private val player get() = engine.player
    private lateinit var session: MediaLibrarySession
    private lateinit var network: NetworkMonitor
    private lateinit var station: MediaItem
    private val localSource get() = !(application as RadioApplication).musicProvider.requiresNetwork
    private val failedLocalIds = mutableSetOf<String>()
    private val sourceAvailable get() = (application as RadioApplication).musicProvider.isAvailable(network.isConnected)
    private val programming get() = (application as RadioApplication).programming
    private val news get() = (application as RadioApplication).news
    private val handler = Handler(Looper.getMainLooper())
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val playbackIntent = PlaybackIntent()
    private var desiredPlayback: Boolean
        get() = playbackIntent.requested
        set(value) { if (value) playbackIntent.requestPlay() else playbackIntent.pause() }
    private var suppressResumptionFallback = false
    private var recovering = false
    private var message = ""
    private var retryAttempt = 0
    private var retryScheduled = false
    private var catalogBlocked = false
    private var pendingInitial: SettableFuture<List<MediaItem>>? = null
    private var initialJob: Job? = null
    private var refillJob: Job? = null
    private var terminalErrors = 0
    private var hasPlayed = false
    private var newsJob: Job? = null
    private var newsRefreshAt = 0L
    private var newsCheckpointAt = 0L
    private var pendingNewsAfter: String? = null
    private var newsBlock = emptyList<ProgramItem>()
    private var lastProgramType: ProgramItemType? = null
    private var newsReadinessLogged = false
    private val newsGuard = object : Runnable {
        override fun run() {
            maybeNews()
            if (pendingNewsAfter != null && desiredPlayback) handler.postDelayed(this,
                if (player.duration > 0 && player.duration - player.currentPosition < 5_000) 250L else PlaybackConfiguration.STATE_POLL_MS)
        }
    }
    private val retry = Runnable {
        retryScheduled = false
        if (desiredPlayback && sourceAvailable) {
            when {
                player.mediaItemCount == 0 -> resumeWithCatalog()
                player.playerError != null -> {
                    // Conservar sequência e posição; nunca resetar por simples perda/troca de rede.
                    if (terminalErrors >= 3 && player.hasNextMediaItem()) {
                        player.seekToNextMediaItem()
                        terminalErrors = 0
                    }
                    player.prepare()
                    player.play()
                }
                else -> maybeRefill()
            }
        }
        publishState()
    }
    private val poll = object : Runnable {
        override fun run() {
            engine.updatePreload(sourceAvailable)
            maybeRefill()
            maybeNews()
            publishState()
            handler.postDelayed(this, PlaybackConfiguration.STATE_POLL_MS)
        }
    }

    override fun onCreate() {
        super.onCreate()
        val tenant = (application as RadioApplication).tenants.activeTenant
        station = MediaItem.Builder().setMediaId(tenant.clientId)
            .setMediaMetadata(RadioMediaIdentity(this, tenant.radioName).applyTo(MediaMetadata.Builder()).setArtist(tenant.companyName)
                .setIsBrowsable(false).setIsPlayable(true)
                .setMediaType(MediaMetadata.MEDIA_TYPE_RADIO_STATION).build()).build()
        programming.startSession()
        engine = ProgramPlayer(this, localSource, stationName = tenant.radioName) { if (BuildConfig.DEBUG) Log.d("RadioDiagnostics", it) }
        val sessionPlayer = object : ForwardingPlayer(player) {
            override fun play() {
                // Media3 1.6 também chama play após falha/cancelamento de onPlaybackResumption.
                if (suppressResumptionFallback) suppressResumptionFallback = false else startPlayback()
            }
            override fun setPlayWhenReady(playWhenReady: Boolean) {
                if (playWhenReady) startPlayback() else pausePlayback()
            }
            override fun pause() { pausePlayback() }
            override fun stop() { pausePlayback(); player.stop() }
        }
        session = MediaLibrarySession.Builder(this, sessionPlayer, LibraryCallback())
            .setSessionActivity(PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)).build()
        network = NetworkMonitor(this, handler) {
            engine.updatePreload(sourceAvailable)
            if (desiredPlayback && sourceAvailable && (player.playerError != null ||
                    player.mediaItemCount == 0 || player.playbackState == Player.STATE_ENDED)) scheduleRecovery()
            publishState()
        }
        player.addListener(object : Player.Listener {
            override fun onEvents(player: Player, events: Player.Events) {
                // O envelope muda ganho a cada 20 ms: não retransmitir estado da UI nesse ritmo.
                if (events.size() == 1 && events.contains(Player.EVENT_VOLUME_CHANGED)) return
                if (!localSource) {
                    news.tick(SystemClock.elapsedRealtime(), player.isPlaying)
                    if (player.isPlaying) engine.items.getOrNull(player.currentMediaItemIndex)?.let(news::onPlaying)
                }
                if (player.isPlaying) {
                    engine.items.getOrNull(player.currentMediaItemIndex)?.let(programming::onPlaying)
                    hasPlayed = true
                    recovering = false
                    terminalErrors = 0
                    message = ""
                } else if (hasPlayed && player.playbackState == Player.STATE_BUFFERING) {
                    recovering = true
                }
                publishState()
            }
            override fun onPlayWhenReadyChanged(playWhenReady: Boolean, reason: Int) {
                // O ExoPlayer trata foco/noisy internamente. Uma pausa deve cancelar intenção/retries.
                if (!playWhenReady) {
                    if (!localSource) { news.tick(SystemClock.elapsedRealtime(), false); news.persist() }
                    desiredPlayback = false
                    cancelRecovery()
                    engine.updatePreload(sourceAvailable)
                }
            }
            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
                // Executar após o lote de eventos do player, sem reentrância na mudança de timeline.
                handler.post {
                    val type = engine.items.getOrNull(player.currentMediaItemIndex)?.type
                    if (!localSource) {
                        if (type == ProgramItemType.NEWS_INTRO) {
                            programming.newsEntered(); pendingNewsAfter = null
                            logNewsReadiness()
                        }
                        if (lastProgramType == ProgramItemType.NEWS_DROP && type == ProgramItemType.MUSIC) {
                            news.finished(); newsBlock = emptyList(); newsRefreshAt = 0
                        }
                        lastProgramType = type
                    }
                    engine.trimPlayed(); engine.updatePreload(sourceAvailable); maybeRefill()
                    if (BuildConfig.DEBUG) Log.d("RadioDiagnostics", "Provider=${(application as RadioApplication).musicProvider.javaClass.simpleName}; atual=${player.currentMediaItem?.mediaId}; próximo ProgramItem=${engine.items.getOrNull(player.currentMediaItemIndex + 1)?.let { "${it.type}:${it.id}" }}")
                }
            }
            override fun onPlayerError(error: PlaybackException) {
                if (BuildConfig.DEBUG) Log.e("RadioDiagnostics",
                    "Playback failed: code=${error.errorCodeName}; item=${player.currentMediaItem?.mediaId}; " +
                        "causes=${generateSequence<Throwable>(error) { it.cause }.take(6).joinToString(" -> ") { it.javaClass.simpleName }}")
                // Uma recuperação/skip da faixa atual não pode disparar a reserva editorial antes da hora.
                if (pendingNewsAfter == player.currentMediaItem?.mediaId) cancelPendingNews()
                if (engine.items.getOrNull(player.currentMediaItemIndex)?.type in setOf(ProgramItemType.NEWS_INTRO, ProgramItemType.NEWS_DROP)) {
                    news.cancel(); programming.newsEntered(); pendingNewsAfter = null; newsBlock = emptyList()
                    handler.post {
                        if (!desiredPlayback) return@post
                        val music = engine.items.indexOfFirstAfter(player.currentMediaItemIndex) { it.type == ProgramItemType.MUSIC }
                        if (music >= 0) {
                            player.seekTo(music, 0); player.prepare(); player.play()
                        } else { engine.clearEndedQueue(); resumeWithCatalog() }
                    }
                    return
                }
                if (localSource) {
                    if (BuildConfig.DEBUG) Log.w("RadioDiagnostics", "Faixa ignorada: ${player.currentMediaItem?.mediaId}; erro=${error.errorCodeName}")
                    player.currentMediaItem?.mediaId?.let { failedLocalIds.add(it) }
                    handler.post {
                        if (!desiredPlayback) return@post
                        if (player.hasNextMediaItem()) {
                            player.seekToNextMediaItem(); player.prepare(); player.play()
                        } else {
                            engine.clearEndedQueue()
                            resumeWithCatalog()
                        }
                    }
                    return
                }
                terminalErrors++
                recovering = true
                message = "Não foi possível tocar esta faixa. Tentando recuperar a programação."
                scheduleRecovery()
            }
        })
        network.start()
        handler.post(poll)
        publishState()
    }

    private fun startPlayback() {
        desiredPlayback = true
        catalogBlocked = false
        if (player.mediaItemCount == 0) resumeWithCatalog()
        else if (player.playbackState == Player.STATE_ENDED) maybeRefill()
        else {
            if (player.playbackState == Player.STATE_IDLE) player.prepare()
            player.play()
        }
        publishState()
        handler.removeCallbacks(newsGuard)
        if (pendingNewsAfter != null) handler.post(newsGuard)
    }

    private fun pausePlayback() {
        desiredPlayback = false
        pendingInitial?.cancel(false)
        pendingInitial = null
        initialJob?.cancel()
        refillJob?.cancel()
        cancelRecovery()
        player.pause()
        engine.updatePreload(sourceAvailable)
        publishState()
    }

    private fun initialQueue(): ListenableFuture<List<MediaItem>> {
        if (engine.mediaItems.isNotEmpty()) return Futures.immediateFuture(engine.mediaItems)
        pendingInitial?.let { return it }
        val future = SettableFuture.create<List<MediaItem>>()
        pendingInitial = future
        message = ""
        initialJob = scope.launch {
            try {
                val batch = programming.nextBatch(excludedIds = failedLocalIds, prefer = { !sourceAvailable && engine.isCached(it) })
                if (batch.isEmpty()) throw MusicProviderException("Programação indisponível.", false)
                if (!future.isCancelled) {
                    message = ""
                    future.set(engine.register(batch))
                }
            } catch (_: CancellationException) {
                future.cancel(false)
            } catch (error: MusicProviderException) {
                message = error.userMessage
                catalogBlocked = !error.retryable
                recovering = error.retryable
                if (!error.retryable) desiredPlayback = false
                future.setException(error)
                if (error.retryable) scheduleRecovery()
            } finally {
                if (pendingInitial === future) pendingInitial = null
                publishState()
            }
        }
        publishState()
        return future
    }

    private fun resumeWithCatalog() {
        if (catalogBlocked || pendingInitial != null) return
        val generation = playbackIntent.generation
        val future = initialQueue()
        future.addListener({
            if (desiredPlayback && playbackIntent.isCurrent(generation) && !future.isCancelled) {
                try {
                    val media = future.get()
                    if (player.mediaItemCount == 0) player.setMediaItems(media)
                    player.prepare()
                    player.play()
                } catch (_: Exception) { /* É a mensagem sanitizada já publicada pelo carregamento. */ }
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun maybeRefill() {
        if (pendingNewsAfter != null || !desiredPlayback || (!sourceAvailable && !(application as RadioApplication).musicProvider.supportsSavedCatalog) || catalogBlocked || retryScheduled ||
            refillJob?.isActive == true || player.mediaItemCount == 0 ||
            player.mediaItemCount - player.currentMediaItemIndex - 1 > ProgrammingConfiguration.REFILL_REMAINING) return
        refillJob = scope.launch {
            try {
                val ended = player.playbackState == Player.STATE_ENDED
                val queued = if (ended) emptySet() else engine.items.map { it.id }.toSet()
                val batch = programming.nextBatch(engine.items.lastOrNull(), queued, failedLocalIds, prefer = { !sourceAvailable && engine.isCached(it) })
                if (batch.isEmpty()) {
                    if (ended) {
                        message = "Programação indisponível."
                        desiredPlayback = false
                    }
                    return@launch
                }
                if (ended) engine.clearEndedQueue()
                engine.append(batch)
                message = ""
                if (ended && desiredPlayback) {
                    player.prepare()
                    player.play()
                }
                engine.updatePreload(sourceAvailable)
            } catch (_: CancellationException) {
                // Pause preserva a fila/buffer atuais, mas encerra a consulta em andamento.
            } catch (error: MusicProviderException) {
                message = error.userMessage
                catalogBlocked = !error.retryable
                if (error.retryable) scheduleRecovery()
            } finally {
                publishState()
            }
        }
    }

    /** Planejar somente o futuro; o evento de fim não faz rede nem cria o bloco. */
    private fun maybeNews() {
        if (localSource || !::engine.isInitialized || !::network.isInitialized) return
        val now = SystemClock.elapsedRealtime()
        news.tick(now, player.isPlaying)
        if (!desiredPlayback) return
        if (sourceAvailable && now >= newsRefreshAt && newsJob?.isActive != true && !news.hasReservation) {
            newsRefreshAt = now + NewsConfiguration.REFRESH_INTERVAL_MS
            newsJob = scope.launch {
                val available = news.prefetch()
                newsRefreshAt = SystemClock.elapsedRealtime() + if (available) NewsConfiguration.REFRESH_INTERVAL_MS else NewsConfiguration.RETRY_INTERVAL_MS
            }
        }
        if (now >= newsCheckpointAt) {
            news.persist(); newsCheckpointAt = now + 30_000
        }
        val current = engine.items.getOrNull(player.currentMediaItemIndex) ?: return
        val remaining = if (player.duration > 0 && player.duration != C.TIME_UNSET) player.duration - player.currentPosition else return
        if (pendingNewsAfter == current.id) {
            if (remaining <= 15_000 && !newsReadinessLogged) { logNewsReadiness(); newsReadinessLogged = true }
            if (remaining <= NewsConfiguration.PRELOAD_GUARD_MS &&
                (newsBlock.any { !engine.ready(it) } || !news.reservationStillEligible())) {
                // Falta áudio real preparado: restaurar a inserção normal ANTES do fim, sem intro sozinha.
                cancelPendingNews()
            }
            return
        }
        if (news.hasReservation || refillJob?.isActive == true || current.type in setOf(ProgramItemType.NEWS_INTRO, ProgramItemType.NEWS_DROP) ||
            remaining <= NewsConfiguration.PRELOAD_GUARD_MS) return
        val tail = engine.items.drop(player.currentMediaItemIndex + 1)
        if (tail.none { it.type == ProgramItemType.MUSIC }) return
        val block = news.reserve(remaining) ?: return
        val planned = programming.insertNews(tail, block)
        pendingNewsAfter = current.id; newsBlock = block; newsReadinessLogged = false
        engine.replaceUpcoming(planned)
        if (BuildConfig.DEBUG) Log.d("RadioDiagnostics", "News block reserved at safe boundary after=${current.id}; items already in timeline; no seek/stop/prepare")
        handler.removeCallbacks(newsGuard); handler.post(newsGuard)
    }

    private fun logNewsReadiness() {
        if (!BuildConfig.DEBUG) return
        val music = engine.items.drop(player.currentMediaItemIndex + 1).firstOrNull { it.type == ProgramItemType.MUSIC }
        Log.d("RadioDiagnostics", "NEWS BLOCK: Intro ready: ${newsBlock.getOrNull(0)?.let(engine::ready) == true}; " +
            "News ready: ${newsBlock.getOrNull(1)?.let(engine::ready) == true}; Next music ready: ${music?.let(engine::ready) == true}; readiness=MediaPeriod/tracks/buffer")
    }

    private fun cancelPendingNews() {
        if (pendingNewsAfter == null) return
        engine.replaceUpcoming(programming.cancelPendingNews())
        pendingNewsAfter = null; newsBlock = emptyList(); news.cancel()
    }

    private fun scheduleRecovery() {
        if (!desiredPlayback || retryScheduled || catalogBlocked) return
        recovering = true
        if (sourceAvailable) {
            retryScheduled = true
            handler.postDelayed(retry, RetryPolicy.delayMillis(retryAttempt))
            retryAttempt = (retryAttempt + 1).coerceAtMost(5)
        }
        publishState()
    }

    private fun cancelRecovery() {
        handler.removeCallbacks(retry)
        retryScheduled = false
        retryAttempt = 0
        recovering = false
    }

    private fun publishState() {
        if (!::session.isInitialized || !::network.isInitialized) return
        val state = ConnectionState.resolve(desiredPlayback, sourceAvailable, player.isPlaying,
            player.playbackSuppressionReason != Player.PLAYBACK_SUPPRESSION_REASON_NONE,
            recovering || player.playerError != null,
            loadingCatalog = pendingInitial != null && message.isBlank(),
            catalogUnavailable = player.mediaItemCount == 0 && message == "Programação indisponível.")
        session.setSessionExtras(Bundle().apply {
            putString(STATE_KEY, state.name)
            putBoolean(REQUESTED_KEY, desiredPlayback)
            putBoolean(CONNECTED_KEY, sourceAvailable)
            putString(MESSAGE_KEY, message)
            putLong("bufferedDurationMs", player.totalBufferedDuration)
        })
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaLibrarySession = session
    override fun onTaskRemoved(rootIntent: Intent?) { if (!desiredPlayback) stopSelf() }
    override fun onDestroy() {
        if (!localSource) { news.tick(SystemClock.elapsedRealtime(), false); news.abandonTimeline(); news.persist() }
        network.stop()
        handler.removeCallbacksAndMessages(null)
        pendingInitial?.cancel(false)
        scope.cancel()
        session.release()
        engine.release()
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
                    else -> engine.mediaItems.find { it.mediaId == mediaId }?.let { LibraryResult.ofItem(it, null) }
                        ?: LibraryResult.ofError(SessionError.ERROR_BAD_VALUE)
                })
        override fun onPlaybackResumption(session: MediaSession, controller: MediaSession.ControllerInfo):
            ListenableFuture<MediaSession.MediaItemsWithStartPosition> {
            desiredPlayback = true
            catalogBlocked = false
            val future = stationContents()
            // Registrado antes do callback interno do Media3; marcar o fallback no mesmo thread.
            future.addListener({
                try { future.get() } catch (_: Exception) { suppressResumptionFallback = true }
            }, MoreExecutors.directExecutor())
            return future
        }
        override fun onSetMediaItems(session: MediaSession, controller: MediaSession.ControllerInfo,
            mediaItems: List<MediaItem>, startIndex: Int, startPositionMs: Long):
            ListenableFuture<MediaSession.MediaItemsWithStartPosition> {
            if (mediaItems.size != 1 || mediaItems[0].mediaId != station.mediaId) {
                return Futures.immediateFailedFuture(IllegalArgumentException("Estação desconhecida"))
            }
            return stationContents()
        }
        override fun onAddMediaItems(session: MediaSession, controller: MediaSession.ControllerInfo,
            mediaItems: List<MediaItem>): ListenableFuture<List<MediaItem>> =
            Futures.immediateFailedFuture(UnsupportedOperationException("A programação é automática"))
        private fun stationContents(): ListenableFuture<MediaSession.MediaItemsWithStartPosition> {
            val generation = playbackIntent.generation
            return Futures.transform(initialQueue(), { media ->
                if (!playbackIntent.isCurrent(generation)) throw CancellationException("Pedido de reprodução substituído")
                MediaSession.MediaItemsWithStartPosition(checkNotNull(media),
                    player.currentMediaItemIndex.coerceAtLeast(0), player.currentPosition.coerceAtLeast(0))
            }, ContextCompat.getMainExecutor(this@LocalFallbackRadioService))
        }
    }

    private fun root(): MediaItem = MediaItem.Builder().setMediaId(ROOT_ID)
        .setMediaMetadata(MediaMetadata.Builder().setTitle("Rádio Embarcada")
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

private inline fun <T> List<T>.indexOfFirstAfter(index: Int, predicate: (T) -> Boolean): Int =
    (index + 1 until size).firstOrNull { predicate(this[it]) } ?: -1
