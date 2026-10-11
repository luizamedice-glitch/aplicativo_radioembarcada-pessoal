package br.com.radioembarcada.player

import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.MediaLibraryService.MediaLibrarySession
import androidx.media3.session.MediaSession

/** Restringe os controladores, não o ExoPlayer usado internamente pela programação. */
@UnstableApi
internal open class RadioSessionCallback : MediaLibrarySession.Callback {
    override fun onConnect(session: MediaSession, controller: MediaSession.ControllerInfo):
        MediaSession.ConnectionResult = MediaSession.ConnectionResult.AcceptedResultBuilder(session)
            .setAvailableSessionCommands(MediaSession.ConnectionResult.DEFAULT_SESSION_AND_LIBRARY_COMMANDS)
            // Inclui o media notification controller: no Media3 1.6.1 seus comandos também
            // determinam as ações da sessão Android (System UI, lock screen e Bluetooth).
            .setAvailablePlayerCommands(allowedCommands(MediaSession.ConnectionResult.DEFAULT_PLAYER_COMMANDS))
            .setMediaButtonPreferences(emptyList())
            .build()

    companion object {
        fun allowedCommands(commands: Player.Commands): Player.Commands = commands.buildUpon()
                .removeAll(
                    Player.COMMAND_SEEK_TO_NEXT,
                    Player.COMMAND_SEEK_TO_NEXT_MEDIA_ITEM,
                    Player.COMMAND_SEEK_TO_PREVIOUS,
                    Player.COMMAND_SEEK_TO_PREVIOUS_MEDIA_ITEM,
                    Player.COMMAND_SEEK_IN_CURRENT_MEDIA_ITEM,
                    Player.COMMAND_SEEK_TO_MEDIA_ITEM,
                    Player.COMMAND_SEEK_TO_DEFAULT_POSITION,
                    Player.COMMAND_SEEK_BACK,
                    Player.COMMAND_SEEK_FORWARD,
                    Player.COMMAND_CHANGE_MEDIA_ITEMS,
                    Player.COMMAND_SET_REPEAT_MODE,
                    Player.COMMAND_SET_SHUFFLE_MODE,
                    Player.COMMAND_SET_SPEED_AND_PITCH,
                    Player.COMMAND_STOP,
                ).build()
    }
}
