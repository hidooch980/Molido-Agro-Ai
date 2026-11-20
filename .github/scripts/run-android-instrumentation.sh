#!/usr/bin/env bash
set -Eeuo pipefail

DIAG_DIR="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
mkdir -p "$DIAG_DIR"

capture_emulator_diagnostics() {
  local status=$?
  set +e
  adb devices -l > "$DIAG_DIR/molido-adb-devices.txt" 2>&1
  timeout 20s adb logcat -d -v threadtime > "$DIAG_DIR/molido-emulator-logcat.txt" 2>&1
  timeout 20s adb shell dumpsys activity processes > "$DIAG_DIR/molido-emulator-processes.txt" 2>&1
  return "$status"
}
trap capture_emulator_diagnostics EXIT

echo "Waiting for the Android emulator transport..."
timeout --signal=TERM --kill-after=10s 180s adb wait-for-device

boot_completed=false
for attempt in $(seq 1 120); do
  if [[ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; then
    boot_completed=true
    break
  fi
  sleep 2
done

if [[ "$boot_completed" != "true" ]]; then
  echo "::error::Emulator transport connected but Android did not finish booting within 240 seconds."
  exit 1
fi

adb shell settings put global window_animation_scale 0
adb shell settings put global transition_animation_scale 0
adb shell settings put global animator_duration_scale 0

echo "Emulator boot completed; starting instrumentation tests."
timeout --signal=TERM --kill-after=30s 45m gradle --no-daemon --console=plain --stacktrace :app:connectedDebugAndroidTest 2>&1 | tee "$DIAG_DIR/molido-instrumentation-gradle.log"
