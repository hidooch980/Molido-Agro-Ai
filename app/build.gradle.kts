plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.google.devtools.ksp")
}

val signingStoreFile = System.getenv("ANDROID_KEYSTORE_PATH")
val signingStorePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
val signingKeyAlias = System.getenv("ANDROID_KEY_ALIAS")
val hasReleaseSigning = listOf(signingStoreFile, signingStorePassword, signingKeyAlias).all { !it.isNullOrBlank() }

val versionProperties = java.util.Properties().apply {
    rootProject.file("version.properties").inputStream().use { load(it) }
}
val baseVersionName = versionProperties.getProperty("VERSION_NAME", "0.1.0")
val baseVersionCode = versionProperties.getProperty("VERSION_CODE", "1").toInt()
val requestedVersionName = System.getenv("ANDROID_VERSION_NAME")?.trim()
    ?.takeIf { it.isNotEmpty() }
    ?.removePrefix("v")
val ciRunNumber = System.getenv("GITHUB_RUN_NUMBER")
val resolvedVersionName = requestedVersionName
    ?: if (!ciRunNumber.isNullOrBlank()) "$baseVersionName-dev.$ciRunNumber" else baseVersionName
val resolvedVersionCode = System.getenv("ANDROID_VERSION_CODE")?.toIntOrNull() ?: baseVersionCode

val validateReleaseSigning = tasks.register("validateReleaseSigning") {
    group = "verification"
    description = "Require the configured PKCS12 key before packaging a release APK."
    doLast {
        check(hasReleaseSigning) {
            "A single PKCS12 release signing key is required for every release APK."
        }
        check(file(signingStoreFile!!).isFile) {
            "The configured PKCS12 release signing keystore does not exist."
        }
    }
}

tasks.configureEach {
    if (name == "validateSigningRelease") {
        dependsOn(validateReleaseSigning)
    }
}

android {
    namespace = "com.molido.agroai"
    compileSdk = 35

    defaultConfig {
        buildConfigField("String", "SYNC_BASE_URL", "\"${providers.gradleProperty("SYNC_BASE_URL").orElse("").get()}\"")
        applicationId = "com.molido.agroai"
        minSdk = 26
        targetSdk = 35
        versionCode = resolvedVersionCode
        versionName = resolvedVersionName
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = file(signingStoreFile!!)
                storeType = "PKCS12"
                storePassword = signingStorePassword
                keyAlias = signingKeyAlias
                keyPassword = signingStorePassword
                enableV1Signing = true
                enableV2Signing = true
                enableV3Signing = true
            }
        }
    }

    buildTypes {
        release {
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions { jvmTarget = "17" }


    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        resources { excludes += "/META-INF/{AL2.0,LGPL2.1}" }
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.02.00"))
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.room:room-runtime:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")
    ksp("androidx.room:room-compiler:2.6.1")
    implementation("androidx.datastore:datastore-preferences:1.1.2")
    implementation("androidx.work:work-runtime-ktx:2.10.0")
    implementation("androidx.camera:camera-camera2:1.4.1")
    implementation("androidx.camera:camera-lifecycle:1.4.1")
    implementation("androidx.camera:camera-view:1.4.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.1")

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test:core:1.6.1")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation(platform("androidx.compose:compose-bom:2025.02.00"))
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
