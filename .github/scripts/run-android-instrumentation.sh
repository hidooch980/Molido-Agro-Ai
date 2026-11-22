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

echo "Waiting for Android emulator transport..."
for attempt in $(seq 1 10); do
  if timeout --signal=TERM --kill-after=10s 30s adb wait-for-device; then
    break
  fi
  adb reconnect offline >/dev/null 2>&1 || true
  sleep 3
done

boot_completed=false
for attempt in $(seq 1 180); do
  if [[ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; then
    boot_completed=true
    break
  fi
  adb reconnect offline >/dev/null 2>&1 || true
  sleep 2
done

if [[ "$boot_completed" != "true" ]]; then
  echo "::error::Android did not report sys.boot_completed=1 within 360 seconds."
  exit 1
fi

echo "Android boot flag is set; waiting for core system services..."
services_ready=false
for attempt in $(seq 1 120); do
  activity_status="$(adb shell service check activity 2>/dev/null || true)"
  package_status="$(adb shell service check package 2>/dev/null || true)"
  settings_status="$(adb shell settings get global airplane_mode_on 2>/dev/null || true)"
  if [[ "$activity_status" == *found* && "$package_status" == *found* && -n "$settings_status" ]]; then
    services_ready=true
    break
  fi
  adb reconnect offline >/dev/null 2>&1 || true
  sleep 2
done

if [[ "$services_ready" != "true" ]]; then
  echo "::error::Android booted but activity/package/settings services did not become ready within 240 seconds."
  adb devices -l || true
  adb shell getprop sys.boot_completed || true
  adb shell service list | grep -E 'activity|package|settings' || true
  exit 1
fi

echo "Core Android services are ready; disabling animations."
for setting in window_animation_scale transition_animation_scale animator_duration_scale; do
  success=false
  for attempt in $(seq 1 5); do
    if adb shell settings put global "$setting" 0 >/dev/null 2>&1; then
      success=true
      break
    fi
    adb reconnect offline >/dev/null 2>&1 || true
    sleep 2
  done
  if [[ "$success" != "true" ]]; then
    echo "::error::Could not update Android setting $setting after retries."
    exit 1
  fi
done

echo "Emulator services are ready; starting instrumentation tests."
timeout --signal=TERM --kill-after=30s 45m gradle --no-daemon --console=plain --stacktrace :app:connectedDebugAndroidTest 2>&1 | tee "$DIAG_DIR/molido-instrumentation-gradle.log"
