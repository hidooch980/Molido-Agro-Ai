# Keep application entry points and Room metadata where required.
-keepattributes *Annotation*
-keep class androidx.room.** { *; }
-dontwarn kotlinx.coroutines.**
