package br.com.radioembarcada.player

import android.app.Application
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.drawable.AdaptiveIconDrawable
import br.com.radioembarcada.R
import java.io.File
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class RadioIdentityTest {
    @Test @Config(sdk = [28]) @GraphicsMode(GraphicsMode.Mode.LEGACY)
    fun olderAndroidLoadsTheAdaptiveIconWithoutThemedIconSupport() {
        val context = RuntimeEnvironment.getApplication()
        assertTrue(context.getDrawable(R.mipmap.ic_launcher) is AdaptiveIconDrawable)
        assertEquals("Rádio Alce", context.packageManager.getApplicationLabel(context.applicationInfo).toString())
    }
    @Test fun nativeMediaArtworkIsSquareAndSeparateFromLauncherArtwork() {
        val resources = RuntimeEnvironment.getApplication().resources
        val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeResource(resources, R.drawable.radio_alce_media, options)
        assertEquals(1254, options.outWidth)
        assertEquals(1254, options.outHeight)
        BitmapFactory.decodeResource(resources, R.drawable.radio_alce_brand, options)
        assertEquals(1280, options.outWidth)
        assertEquals(1170, options.outHeight)
    }
    @Test fun screenLogoHasTransparentBackgroundAndUsesMostOfItsCanvas() {
        val resources = RuntimeEnvironment.getApplication().resources
        val logo = BitmapFactory.decodeResource(resources, R.drawable.radio_alce_logo)
        assertTrue(logo.hasAlpha())
        listOf(0 to 0, logo.width - 1 to 0, 0 to logo.height - 1).forEach { (x, y) ->
            assertEquals(0, Color.alpha(logo.getPixel(x, y)))
        }
        // The logo is tightly framed for the app, unlike the system artwork.
        var occupiedRows = 0
        for (y in 0 until logo.height) {
            if ((0 until logo.width).any { x -> Color.alpha(logo.getPixel(x, y)) > 128 }) occupiedRows++
        }
        assertTrue(occupiedRows > logo.height * .8f)
    }
    @Test fun nativeArtworkKeepsWholeLogoInsideHorizontalThreeToOneCrop() {
        val art = BitmapFactory.decodeResource(RuntimeEnvironment.getApplication().resources, R.drawable.radio_alce_media)
        val cropHeight = art.width / 3
        val top = (art.height - cropHeight) / 2
        var visiblePixels = 0
        for (y in 0 until art.height) for (x in 0 until art.width) {
            val pixel = art.getPixel(x, y)
            if (maxOf(Color.red(pixel), Color.green(pixel), Color.blue(pixel)) > 40) {
                visiblePixels++
                assertTrue("Visible logo cropped at ($x,$y)", y >= top && y < top + cropHeight)
            }
        }
        assertTrue("Artwork must contain a visible logo", visiblePixels > 10_000)
        val preview = Bitmap.createBitmap(art, 0, top, art.width, cropHeight)
        File("build/reports/ui/native-artwork-3-to-1.png").also { file ->
            file.parentFile?.mkdirs()
            file.outputStream().use { preview.compress(Bitmap.CompressFormat.PNG, 100, it) }
        }
    }
    @Test fun launcherUsesRadioAlceLabelAndOfficialLogoAdaptiveIcon() {
        val context = RuntimeEnvironment.getApplication()
        assertEquals("Rádio Alce", context.getString(R.string.app_name))
        val drawable = checkNotNull(context.getDrawable(R.mipmap.ic_launcher))
        assertTrue(drawable is AdaptiveIconDrawable)
        val icon = Bitmap.createBitmap(192, 192, Bitmap.Config.ARGB_8888)
        drawable.setBounds(0, 0, 192, 192)
        drawable.draw(Canvas(icon))
        File("build/reports/ui/launcher-icon.png").also { file ->
            file.parentFile?.mkdirs()
            file.outputStream().use { icon.compress(Bitmap.CompressFormat.PNG, 100, it) }
        }
        assertNotEquals(icon.getPixel(96, 96), icon.getPixel(20, 96))
    }
}
