import java.util.Properties
import java.net.URI
import groovy.json.JsonOutput

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// Valores locais nunca são gravados em fontes versionadas; o campo gerado fica em build/.
val localConfiguration = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}
val jamendoClientId = providers.environmentVariable("JAMENDO_CLIENT_ID").orNull
    ?.takeIf { it.isNotBlank() } ?: localConfiguration.getProperty("jamendo.clientId", "")

// Opt-in local preserva os arquivos no computador; o build remoto não empacota music/.
val useLocalMusic = providers.gradleProperty("useLocalMusic").map { it.toBoolean() }.getOrElse(false)
val playbackMode = providers.gradleProperty("playbackMode").getOrElse("STREAM")
require(playbackMode in setOf("STREAM", "LOCAL_FALLBACK")) { "playbackMode aceita STREAM ou LOCAL_FALLBACK" }
require(!useLocalMusic || playbackMode == "LOCAL_FALLBACK") { "Assets musicais exigem playbackMode=LOCAL_FALLBACK" }
val radioStreamUrl = providers.gradleProperty("radioStreamUrl").orNull
    ?: providers.environmentVariable("RADIO_STREAM_URL").orNull
    ?: "http://15.229.83.121:8000/alce.mp3"
val streamUri = URI(radioStreamUrl)
require(streamUri.userInfo == null && streamUri.fragment == null && !streamUri.host.isNullOrBlank() &&
    (streamUri.scheme == "https" || (streamUri.scheme == "http" && streamUri.host == "15.229.83.121" &&
        streamUri.port == 8000 && streamUri.path == "/alce.mp3" && streamUri.query == null))) {
    "Stream deve usar HTTPS ou o endpoint HTTP provisório autorizado" }

val newsIntervalDebugMinutes = providers.gradleProperty("newsIntervalDebugMinutes").map { it.toLong() }.getOrElse(0)
require(newsIntervalDebugMinutes in listOf(0L, 3L, 5L)) { "newsIntervalDebugMinutes aceita 0, 3 ou 5" }

android {
    namespace = "br.com.radioembarcada"
    compileSdk = 35
    defaultConfig {
        applicationId = "br.com.radioembarcada"
        minSdk = 26
        targetSdk = 35
        versionCode = 7
        versionName = "0.6.1"
        buildConfigField("String", "PLAYBACK_MODE", JsonOutput.toJson(playbackMode))
        buildConfigField("String", "RADIO_STREAM_URL", JsonOutput.toJson(radioStreamUrl))
        manifestPlaceholders["radioServiceClass"] = if (playbackMode == "STREAM") ".player.RadioService" else ".player.LocalFallbackRadioService"
        buildConfigField("String", "JAMENDO_CLIENT_ID", JsonOutput.toJson(jamendoClientId))
        buildConfigField("boolean", "USE_LOCAL_MUSIC", useLocalMusic.toString())
        buildConfigField("long", "NEWS_INTERVAL_DEBUG", "0L")
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true; buildConfig = true }
    buildTypes.getByName("debug").buildConfigField("long", "NEWS_INTERVAL_DEBUG", "${newsIntervalDebugMinutes * 60_000}L")
    testOptions { unitTests.isIncludeAndroidResources = true }
    if (!useLocalMusic) sourceSets.getByName("main").assets.setSrcDirs(
        listOf(layout.buildDirectory.dir("generated/remoteAssets")))
    // Permite ler metadados via AssetFileDescriptor e buscar posições sem descompactar MP3.
    androidResources { noCompress += listOf("mp3", "MP3", "Mp3", "mP3") }
}
if (!useLocalMusic) {
    val remoteAssets = tasks.register<Sync>("prepareRemoteAssets") {
        from("src/main/assets")
        exclude("music/**")
        includeEmptyDirs = false
        into(layout.buildDirectory.dir("generated/remoteAssets"))
    }
    tasks.named("preBuild").configure { dependsOn(remoteAssets) }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.04.01"))
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.0")
    implementation("androidx.media3:media3-exoplayer:1.6.1")
    implementation("androidx.media3:media3-session:1.6.1")
    implementation("androidx.media3:media3-datasource:1.6.1")
    implementation("androidx.media3:media3-database:1.6.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("io.coil-kt:coil-compose:2.7.0")
    testImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    testImplementation("androidx.media3:media3-test-utils-robolectric:1.6.1")
    testImplementation("org.robolectric:robolectric:4.14.1")
}
