package br.com.radioembarcada.player

import androidx.media3.common.C
import androidx.media3.common.ParserException
import androidx.media3.common.PlaybackException
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSourceException
import androidx.media3.datasource.HttpDataSource
import androidx.media3.exoplayer.upstream.DefaultLoadErrorHandlingPolicy
import androidx.media3.exoplayer.upstream.LoadErrorHandlingPolicy
import java.io.IOException

/** Uma falha de carregamento temporária não deve descartar o áudio já preparado. */
@UnstableApi
open class RadioLoadErrorPolicy(private val finiteRetries: Boolean = false) : DefaultLoadErrorHandlingPolicy() {
    override fun getMinimumLoadableRetryCount(dataType: Int): Int = Int.MAX_VALUE
    override fun getRetryDelayMsFor(loadErrorInfo: LoadErrorHandlingPolicy.LoadErrorInfo): Long {
        val error = loadErrorInfo.exception
        if (finiteRetries && loadErrorInfo.errorCount >= 3) return C.TIME_UNSET
        if (isPermanentLoadError(error)) return C.TIME_UNSET
        return RetryPolicy.delayMillis(loadErrorInfo.errorCount - 1)
    }
}

@UnstableApi
internal fun isPermanentLoadError(error: IOException): Boolean =
    error is ParserException || (error is HttpDataSource.InvalidResponseCodeException &&
        error.responseCode in setOf(400, 401, 403, 404, 410)) ||
    (error is DataSourceException && error.reason in setOf(
        PlaybackException.ERROR_CODE_IO_FILE_NOT_FOUND,
        PlaybackException.ERROR_CODE_IO_NO_PERMISSION,
        PlaybackException.ERROR_CODE_IO_READ_POSITION_OUT_OF_RANGE,
    ))
