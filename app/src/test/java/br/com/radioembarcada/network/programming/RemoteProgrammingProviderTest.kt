package br.com.radioembarcada.network.programming

import br.com.radioembarcada.model.ProgramItemType
import br.com.radioembarcada.storage.SavedProgrammingConfiguration
import br.com.radioembarcada.storage.FileProgrammingConfiguration
import java.io.IOException
import java.nio.file.Files
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class RemoteProgrammingProviderTest {
    private class Store(var json: String? = null) : SavedProgrammingConfiguration {
        override fun read() = json
        override fun write(json: String) { this.json = json }
    }
    private fun fixture() = checkNotNull(javaClass.getResource("/programming.json")).readText()

    @Test fun sevenStationsAndThreeJinglesAreSavedAndSurviveFailureAndOfflineRestart() = runBlocking {
        val json = checkNotNull(javaClass.getResource("/programming-v4.json")).readText()
        val directory = Files.createTempDirectory("programming-seven").toFile()
        try {
            val store = FileProgrammingConfiguration(directory.resolve("programming.json"))
            var time = 0L
            var fail = false
            val logs = mutableListOf<String>()
            val provider = RemoteProgrammingProvider("alce", store, now = { time }, download = {
                if (fail) throw IOException("private request") else json
            }, diagnostic = logs::add)
            val valid = checkNotNull(provider.load())
            assertEquals(7, valid.stationIds.size)
            assertEquals(3, valid.jingles.size)
            fail = true
            time += RemoteProgrammingConfiguration.REFRESH_INTERVAL_MS
            assertEquals(valid, provider.load())
            val restarted = RemoteProgrammingProvider("alce", store, connected = { false },
                download = { error("Must not download offline") })
            assertEquals(valid, restarted.load())
            assertEquals(json, store.read())
            assertTrue(logs.any { "Station IDs loaded: 7" in it && "Jingles loaded: 3" in it })
            assertTrue(logs.none { "https://" in it || "private request" in it })
        } finally { directory.deleteRecursively() }
    }

    @Test fun newVersionReplacesOldFourStationCacheAndMalformedRefreshCannotDropNewItems() = runBlocking {
        val old = checkNotNull(javaClass.getResource("/programming-v3.json")).readText()
        val current = checkNotNull(javaClass.getResource("/programming-v4.json")).readText()
        val store = Store(old)
        var time = 0L
        var response = current
        val provider = RemoteProgrammingProvider("alce", store, now = { time }, download = { response })
        assertEquals(7, provider.load()?.stationIds?.size)
        assertEquals(current, store.json)
        response = "invalid JSON"
        time += RemoteProgrammingConfiguration.REFRESH_INTERVAL_MS
        assertEquals(4L, provider.load()?.version)
        assertEquals(7, provider.load()?.stationIds?.size)
        assertEquals(current, store.json)
    }

    @Test fun publishedExpansionLoadsAllElevenStationsAndKeepsThreeJingles() {
        val parsed = RemoteProgrammingParser.parse(checkNotNull(javaClass.getResource("/programming-v6.json")).readText())
        assertEquals(6L, parsed.version)
        assertEquals(11, parsed.stationIds.size)
        assertEquals(3, parsed.jingles.size)
        for (id in listOf("vinheta-nova-3", "vinheta-nova-4", "vinheta-nova-5")) {
            assertEquals(ProgramItemType.STATION_ID, parsed.stationIds.single { it.id == "programming:alce:STATION_ID:$id" }.type)
        }
    }

    @Test fun publishedSchemaMapsRulesAndBothKindsOfProgramItem() {
        val parsed = RemoteProgrammingParser.parse(fixture())
        assertEquals("alce", parsed.stationId)
        assertEquals(1L, parsed.version)
        assertEquals(3, parsed.rules.songsBetweenInsertions)
        assertTrue(parsed.rules.alternateStationIdAndJingle)
        assertEquals(ProgramItemType.STATION_ID, parsed.stationIds.single().type)
        assertEquals(ProgramItemType.JINGLE, parsed.jingles.single().type)
        assertEquals("https://example.org/station.mp3", parsed.stationIds.single().audioUrl)
    }

    @Test fun changedIntervalAndMissingPoolsAreReadFromJson() {
        val json = JSONObject(fixture()).apply {
            getJSONObject("rules").put("songsBetweenInsertions", 5).put("alternateStationIdAndJingle", false)
            remove("stationIds"); remove("jingles")
        }
        val parsed = RemoteProgrammingParser.parse(json.toString())
        assertEquals(5, parsed.rules.songsBetweenInsertions)
        assertFalse(parsed.rules.alternateStationIdAndJingle)
        assertTrue(parsed.stationIds.isEmpty() && parsed.jingles.isEmpty())
    }

    @Test fun invalidUrlsAndTypesAreSkippedWithoutDiscardingValidPieces() {
        val json = JSONObject(fixture())
        json.getJSONArray("stationIds").apply {
            put(JSONObject().put("id", "bad").put("title", "Bad").put("type", "STATION_ID"))
            put(JSONObject().put("id", "bad2").put("title", "Bad").put("type", "STATION_ID").put("url", "file:///private"))
            put(JSONObject().put("id", "bad3").put("title", "Bad").put("type", "JINGLE").put("url", "https://example.org/bad"))
            put(getJSONObject(0))
        }
        assertEquals(1, RemoteProgrammingParser.parse(json.toString()).stationIds.size)
    }

    @Test fun invalidRuleCannotReplaceTheLastValidSavedConfiguration() = runBlocking {
        val valid = fixture()
        for (bad in listOf(0, -1, 1.5, "3", null)) {
            val json = JSONObject(valid).apply { getJSONObject("rules").put("songsBetweenInsertions", bad) }
            val saved = Store(valid)
            val provider = RemoteProgrammingProvider("alce", saved, download = { json.toString() })
            assertEquals(3, provider.load()?.rules?.songsBetweenInsertions)
            assertEquals(valid, saved.json)
        }
    }

    @Test fun networkFailureWithoutSavedConfigurationReturnsNullAndSanitizedDiagnostics() = runBlocking {
        val messages = mutableListOf<String>()
        val provider = RemoteProgrammingProvider("alce", Store(), download = { throw IOException("private URL") },
            diagnostic = messages::add)
        assertNull(provider.load())
        assertTrue(messages.any { "continuando somente com músicas" in it })
        assertTrue(messages.none { "private URL" in it })
    }

    @Test fun savedConfigurationSurvivesRestartAndWorksOffline() = runBlocking {
        val directory = Files.createTempDirectory("programming-test").toFile()
        try {
            val file = directory.resolve("programming.json")
            val online = RemoteProgrammingProvider("alce", FileProgrammingConfiguration(file), download = ::fixture)
            assertEquals(1L, online.load()?.version)
            assertFalse(directory.resolve("programming.json.tmp").exists())
            val offline = RemoteProgrammingProvider("alce", FileProgrammingConfiguration(file), connected = { false },
                download = { error("No download offline") })
            assertEquals(online.load(), offline.load())
            val failing = RemoteProgrammingProvider("alce", FileProgrammingConfiguration(file), download = { throw IOException() })
            assertEquals(online.load(), failing.load())
        } finally { directory.deleteRecursively() }
    }

    @Test fun failureIsThrottledAndLaterSuccessUpdatesVersionAndRules() = runBlocking {
        var time = 0L
        var calls = 0
        val provider = RemoteProgrammingProvider("alce", Store(), now = { time }, download = {
            calls++
            if (calls == 1) throw IOException()
            JSONObject(fixture()).put("version", calls).apply {
                getJSONObject("rules").put("songsBetweenInsertions", calls + 2)
            }.toString()
        })
        repeat(10) { assertNull(provider.load()) }
        assertEquals(1, calls)
        time += RemoteProgrammingConfiguration.FAILED_REFRESH_INTERVAL_MS
        assertEquals(4, provider.load()?.rules?.songsBetweenInsertions)
        repeat(10) { assertEquals(2L, provider.load()?.version) }
        assertEquals(2, calls)
        time += RemoteProgrammingConfiguration.REFRESH_INTERVAL_MS
        assertEquals(3L, provider.load()?.version)
    }

    @Test fun wrongStationAndMalformedConfigurationNeverOverwriteValidConfiguration() = runBlocking {
        val valid = fixture()
        for (invalid in listOf("invalid JSON", JSONObject(valid).put("stationId", "other").toString(),
            JSONObject(valid).put("stationIds", "not an array").toString())) {
            val saved = Store(valid)
            assertEquals("alce", RemoteProgrammingProvider("alce", saved, download = { invalid }).load()?.stationId)
            assertEquals(valid, saved.json)
        }
    }

    @Test fun failedDiskWriteDoesNotLoseValidRemoteConfiguration() = runBlocking {
        val saved = object : SavedProgrammingConfiguration {
            override fun read(): String? = null
            override fun write(json: String) { throw IOException() }
        }
        assertEquals(1L, RemoteProgrammingProvider("alce", saved, download = ::fixture).load()?.version)
    }

    @Test(expected = CancellationException::class) fun cancellationIsNotConvertedIntoMusicalFallback() = runBlocking {
        RemoteProgrammingProvider("alce", Store(), download = { throw CancellationException() }).load()
        Unit
    }
}
