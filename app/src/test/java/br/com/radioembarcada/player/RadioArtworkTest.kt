package br.com.radioembarcada.player

import android.app.Application
import androidx.media3.common.Format
import androidx.media3.common.util.UnstableApi
import androidx.media3.extractor.Extractor
import androidx.media3.extractor.PositionHolder
import androidx.media3.extractor.mp3.Mp3Extractor
import androidx.media3.extractor.metadata.id3.ApicFrame
import androidx.media3.test.utils.FakeExtractorInput
import androidx.media3.test.utils.FakeExtractorOutput
import br.com.radioembarcada.model.ProgramItem
import br.com.radioembarcada.model.ProgramItemType
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@UnstableApi
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class RadioArtworkTest {
    @Test fun extractorSuppressesEmbeddedPictureButPreservesGaplessDelayAndPadding() {
        val original = extract(Mp3Extractor())
        assertTrue((0 until checkNotNull(original.metadata).length()).any { original.metadata?.get(it) is ApicFrame })
        val radio = extract(radioExtractors().createExtractors().filterIsInstance<Mp3Extractor>().single())
        assertNull(radio.metadata)
        assertEquals(512, radio.encoderDelay)
        assertEquals(1024, radio.encoderPadding)
    }
    @Test fun stationArtworkAndTitleReplaceTrackMetadataButInternalDataAndNewsCreditsRemain() {
        val engine = ProgramPlayer(RuntimeEnvironment.getApplication())
        try {
            val music = ProgramItem("m", ProgramItemType.MUSIC, "Title", "https://example.org/m.mp3", 12_000,
                artist = "Artist", artworkUrl = "https://example.org/cover.png", artworkData = byteArrayOf(1, 2))
            val news = music.copy(id = "news", type = ProgramItemType.NEWS_DROP, title = "News",
                artist = "Radioagência Nacional", source = "Radioagência Nacional")
            val intro = music.copy(id = "intro", type = ProgramItemType.NEWS_INTRO)
            val media = engine.register(listOf(music, intro, news))
            val identity = RadioMediaIdentity(RuntimeEnvironment.getApplication())
            media.forEach {
                assertNull(it.mediaMetadata.artworkData)
                assertEquals(identity.artworkUri, it.mediaMetadata.artworkUri)
                assertEquals("Rádio Alce - AO VIVO", it.mediaMetadata.title)
                assertEquals("Rádio Alce - AO VIVO", it.mediaMetadata.displayTitle)
            }
            assertEquals("Title", engine.items.first().title)
            assertNull(media.first().mediaMetadata.artist)
            assertEquals("Artist", engine.items.first().artist)
            assertEquals("Radioagência Nacional", media.last().mediaMetadata.artist)
        } finally { engine.release() }
    }
    @Test fun stationArtworkIsReadableByMedia3WithoutInternet() {
        val context = RuntimeEnvironment.getApplication()
        val source = androidx.media3.datasource.DefaultDataSource.Factory(context).createDataSource()
        try {
            assertTrue(source.open(androidx.media3.datasource.DataSpec(RadioMediaIdentity(context).artworkUri)) > 0)
            val header = ByteArray(8)
            assertEquals(8, source.read(header, 0, 8))
            assertArrayEquals(byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a), header)
        } finally { source.close() }
    }
    private fun extract(extractor: Mp3Extractor): Format {
        val input = FakeExtractorInput.Builder().setData(mp3()).build()
        val output = FakeExtractorOutput()
        extractor.init(output)
        val position = PositionHolder()
        var result = Extractor.RESULT_CONTINUE
        var attempts = 0
        while (result != Extractor.RESULT_END_OF_INPUT && attempts++ < 100) result = extractor.read(input, position)
        extractor.release()
        return checkNotNull(output.trackOutputs.valueAt(0).lastFormat)
    }
    // Tiny synthetic fixture generated in memory, not a licensed music file.
    private fun mp3(): ByteArray {
        fun frame(id: String, data: ByteArray): ByteArray = ByteArrayOutputStream().also { bytes ->
            DataOutputStream(bytes).use { out -> out.writeBytes(id); out.writeInt(data.size); out.writeShort(0); out.write(data) }
        }.toByteArray()
        val picture = byteArrayOf(0) + "image/png".toByteArray() + byteArrayOf(0, 3, 0, 1, 2, 3)
        val comment = byteArrayOf(0) + "engiTunSMPB".toByteArray() + byteArrayOf(0) +
            " 00000000 00000200 00000400 0000000000000000".toByteArray()
        val id3 = frame("APIC", picture) + frame("COMM", comment)
        val size = id3.size
        val header = "ID3".toByteArray() + byteArrayOf(3, 0, 0, ((size shr 21) and 127).toByte(),
            ((size shr 14) and 127).toByte(), ((size shr 7) and 127).toByte(), (size and 127).toByte())
        val audio = ByteArrayOutputStream()
        repeat(10) { audio.write(byteArrayOf(0xff.toByte(), 0xfb.toByte(), 0x90.toByte(), 0xc0.toByte()) + ByteArray(413)) }
        return header + id3 + audio.toByteArray()
    }
}
