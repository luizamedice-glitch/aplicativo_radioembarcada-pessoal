package br.com.radioembarcada.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.*
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import br.com.radioembarcada.R
import br.com.radioembarcada.ui.theme.RadioColors

/** Only presentation: no catalogue, timeline, metadata or player access. */
@Composable
fun RadioPlayerScreen(
    radioName: String,
    playing: Boolean,
    playRequested: Boolean,
    controlsEnabled: Boolean,
    onTogglePlayback: () -> Unit,
    modifier: Modifier = Modifier,
    animateWaveform: Boolean = true,
    onVolumeDown: () -> Unit = {},
    onVolumeUp: () -> Unit = {},
) {
    Box(modifier.fillMaxSize().background(RadioColors.BackgroundBlack).premiumBackground().testTag("radio-screen")) {
        BoxWithConstraints(Modifier.fillMaxSize().safeDrawingPadding().padding(horizontal = 24.dp)) {
            val compact = maxHeight < 500.dp
            val spacing = if (compact) 12.dp else 20.dp
            val controlSize = (maxHeight * .19f).coerceIn(80.dp, 120.dp)
            Column(Modifier.widthIn(max = 520.dp).fillMaxSize().align(Alignment.Center),
                horizontalAlignment = Alignment.CenterHorizontally) {
                Spacer(Modifier.weight(.22f))
                AlceLogoHeader(radioName, Modifier.weight(1f).fillMaxWidth())
                Spacer(Modifier.height(spacing))
                LiveBadge(playing)
                Spacer(Modifier.height(spacing))
                RadioTagline()
                Spacer(Modifier.weight(.28f))
                WaveformVisualizer(playing && animateWaveform,
                    Modifier.fillMaxWidth(.88f).height(if (compact) 44.dp else 64.dp))
                Spacer(Modifier.height(spacing))
                Row(Modifier.widthIn(max = 360.dp).fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceEvenly, verticalAlignment = Alignment.CenterVertically) {
                    VolumeButton(false, onVolumeDown)
                    PrimaryPlayPauseButton(playRequested, controlsEnabled, onTogglePlayback, Modifier.size(controlSize))
                    VolumeButton(true, onVolumeUp)
                }
                Spacer(Modifier.weight(.3f))
            }
        }
    }
}

@Composable
fun AlceLogoHeader(radioName: String, modifier: Modifier = Modifier) {
    Box(modifier, contentAlignment = Alignment.Center) {
        Image(painterResource(R.drawable.radio_alce_media), contentDescription = "Logo Alce — $radioName",
            modifier = Modifier.widthIn(max = 390.dp).fillMaxSize().testTag("alce-logo"), contentScale = ContentScale.Fit)
    }
}

@Composable
fun LiveBadge(playing: Boolean) {
    val gold = if (playing) RadioColors.AlceGold else RadioColors.AlceGoldSoft
    Row(Modifier.testTag("live-badge").semantics(mergeDescendants = true) {
        stateDescription = if (playing) "Rádio em reprodução" else "Rádio em espera"
    }.border(1.dp, gold, RoundedCornerShape(50)).background(gold.copy(alpha = .06f), RoundedCornerShape(50))
        .padding(horizontal = 17.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(9.dp)) {
        Canvas(Modifier.size(18.dp)) {
            drawCircle(gold, radius = size.width * .1f)
            listOf(.25f, .43f).forEach { radius ->
                val inset = size.width * (.5f - radius)
                drawArc(gold, -50f, 100f, false, Offset(inset, inset),
                    androidx.compose.ui.geometry.Size(size.width - inset * 2, size.height - inset * 2),
                    style = Stroke(1.2.dp.toPx(), cap = StrokeCap.Round))
                drawArc(gold, 130f, 100f, false, Offset(inset, inset),
                    androidx.compose.ui.geometry.Size(size.width - inset * 2, size.height - inset * 2),
                    style = Stroke(1.2.dp.toPx(), cap = StrokeCap.Round))
            }
        }
        Text("AO VIVO", color = RadioColors.TextPrimary, fontSize = 12.sp,
            fontWeight = FontWeight.SemiBold, letterSpacing = 2.sp)
    }
}

@Composable
fun RadioTagline() {
    Text("Sua Rádio em Movimento", color = RadioColors.TextSecondary, fontSize = 17.sp,
        textAlign = androidx.compose.ui.text.style.TextAlign.Center,
        modifier = Modifier.testTag("radio-tagline"))
}

@Composable
fun PrimaryPlayPauseButton(playRequested: Boolean, enabled: Boolean, onClick: () -> Unit,
    modifier: Modifier = Modifier) {
    val label = if (playRequested) "Pausar rádio" else "Reproduzir rádio"
    Box(modifier.testTag("play-pause").drawWithCache {
        val glow = Brush.radialGradient(listOf(RadioColors.AlceGold.copy(alpha = .12f),
            RadioColors.BackgroundBlack.copy(alpha = 0f)), radius = size.minDimension * .7f)
        onDrawBehind { drawCircle(glow, radius = size.minDimension * .7f) }
    }.clip(CircleShape).background(Brush.verticalGradient(listOf(
        RadioColors.AlceGoldSoft.copy(alpha = .18f), RadioColors.BackgroundBlack)))
        .border(1.5.dp, if (enabled) RadioColors.AlceGold else RadioColors.AlceGoldSoft, CircleShape)
        .clickable(enabled = enabled, role = Role.Button, onClickLabel = label, onClick = onClick)
        .semantics { contentDescription = label }, contentAlignment = Alignment.Center) {
        Canvas(Modifier.size(34.dp)) {
            val color = RadioColors.TextPrimary.copy(alpha = if (enabled) 1f else .4f)
            if (playRequested) {
                val width = size.width * .22f
                drawRoundRect(color, Offset(size.width * .18f, size.height * .12f),
                    androidx.compose.ui.geometry.Size(width, size.height * .76f),
                    androidx.compose.ui.geometry.CornerRadius(2.dp.toPx()))
                drawRoundRect(color, Offset(size.width * .60f, size.height * .12f),
                    androidx.compose.ui.geometry.Size(width, size.height * .76f),
                    androidx.compose.ui.geometry.CornerRadius(2.dp.toPx()))
            } else drawPath(Path().apply {
                moveTo(size.width * .28f, size.height * .08f)
                lineTo(size.width * .88f, size.height * .5f)
                lineTo(size.width * .28f, size.height * .92f); close()
            }, color)
        }
    }
}

private fun Modifier.premiumBackground() = drawWithCache {
    val glow = Brush.radialGradient(listOf(RadioColors.AlceGold.copy(alpha = .055f),
        RadioColors.BackgroundBlack.copy(alpha = 0f)),
        center = Offset(size.width * .5f, size.height * .38f), radius = size.width * .9f)
    val curves = List(3) { index ->
        Path().apply {
            val shift = index * size.height * .018f
            moveTo(-size.width * .3f, size.height * .64f + shift)
            cubicTo(size.width * .24f, size.height * .32f + shift,
                size.width * .7f, size.height * .9f + shift, size.width * 1.3f, size.height * .28f + shift)
        }
    }
    onDrawBehind {
        drawRect(glow)
        curves.forEachIndexed { index, path ->
            drawPath(path, RadioColors.AlceGold.copy(alpha = .055f - index * .012f), style = Stroke(1.dp.toPx()))
        }
    }
}


@Composable
fun VolumeButton(increase: Boolean, onClick: () -> Unit) {
    val label = if (increase) "Aumentar volume" else "Diminuir volume"
    Box(Modifier.size(48.dp).clip(CircleShape)
        .background(RadioColors.AlceGoldSoft.copy(alpha = .08f))
        .border(1.dp, RadioColors.AlceGoldSoft.copy(alpha = .65f), CircleShape)
        .clickable(role = Role.Button, onClickLabel = label, onClick = onClick)
        .semantics { contentDescription = label }, contentAlignment = Alignment.Center) {
        Canvas(Modifier.size(24.dp)) {
            val color = RadioColors.AlceGold
            val speaker = Path().apply {
                moveTo(size.width * .10f, size.height * .36f)
                lineTo(size.width * .27f, size.height * .36f)
                lineTo(size.width * .47f, size.height * .18f)
                lineTo(size.width * .47f, size.height * .82f)
                lineTo(size.width * .27f, size.height * .64f)
                lineTo(size.width * .10f, size.height * .64f); close()
            }
            drawPath(speaker, color)
            drawLine(color, Offset(size.width * .63f, size.height * .5f),
                Offset(size.width * .95f, size.height * .5f), 1.5.dp.toPx(), StrokeCap.Round)
            if (increase) drawLine(color, Offset(size.width * .79f, size.height * .34f),
                Offset(size.width * .79f, size.height * .66f), 1.5.dp.toPx(), StrokeCap.Round)
        }
    }
}
