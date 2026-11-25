# Keep application entry points and Room metadata where required.
-keepattributes *Annotation*
-keep class androidx.room.** { *; }
-dontwarn kotlinx.coroutines.**
# SQLCipher reaches its classes from native code, so their names must survive shrinking.
-keep class net.zetetic.database.** { *; }
-keepclasseswithmembernames class * { native <methods>; }
