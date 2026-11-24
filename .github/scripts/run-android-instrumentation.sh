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
  if [[ "$status" -ne 0 ]]; then
    # Publish the failure reason as a workflow annotation: annotations stay readable
    # without an authenticated artifact download, so a red run explains itself.
    local log="$DIAG_DIR/molido-instrumentation-gradle.log"
    local excerpt="exit=$status; no instrumentation log was written"
    if [[ -s "$log" ]]; then
      excerpt="$(grep -aE 'FAILED|AssertionError|Exception|Error:|failed|crash|No connected devices|INSTALL_FAILED' "$log" | tail -n 12)"
      if [[ -z "$excerpt" ]]; then
        excerpt="$(tail -n 12 "$log")"
      fi
      excerpt="exit=$status; ${excerpt}"
    fi
    excerpt="${excerpt//$'\n'/ | }"
    echo "::error title=Android instrumentation failed::${excerpt:0:3000}"
  fi
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
# The runner already disables animations before this script starts. Writing the
# settings again is a best-effort guard: on a slow software-emulated device the
# settings provider can briefly refuse writes, and that must not abort the run
# before a single test executes.
for setting in window_animation_scale transition_animation_scale animator_duration_scale; do
  success=false
  for attempt in $(seq 1 20); do
    if adb shell settings put global "$setting" 0 >/dev/null 2>&1; then
      success=true
      break
    fi
    adb reconnect offline >/dev/null 2>&1 || true
    sleep 3
  done
  if [[ "$success" != "true" ]]; then
    echo "::warning::Could not set $setting to 0; continuing because these tests do not depend on animations."
  fi
done

echo "Emulator services are ready; verifying that adb shell answers within five seconds."
# ddmlib reads ro.build.version.sdk with a five second budget. When the freshly booted
# software-emulated device is still busy, that read times out, AGP treats the API level as 0
# and the install fails with "Cannot install split APKs with API level < 21", so gate on
# several consecutive fast answers instead of starting Gradle on a device that still stalls.
responsive=false
fast_reads=0
for attempt in $(seq 1 90); do
  sdk="$(timeout --signal=TERM --kill-after=5s 5s adb shell getprop ro.build.version.sdk 2>/dev/null | tr -d '\r' || true)"
  if [[ "$sdk" =~ ^[0-9]+$ ]]; then
    fast_reads=$((fast_reads + 1))
    if [[ "$fast_reads" -ge 5 ]]; then
      responsive=true
      break
    fi
  else
    fast_reads=0
    adb reconnect offline >/dev/null 2>&1 || true
  fi
  sleep 2
done

if [[ "$responsive" != "true" ]]; then
  echo "::error::Emulator did not answer 'adb shell getprop' within five seconds; installing the test APK would misread the API level."
  adb devices -l || true
  exit 1
fi
echo "Device answered five consecutive property reads within five seconds (API $sdk)."

echo "Emulator services are ready; starting instrumentation tests."
LOG="$DIAG_DIR/molido-instrumentation-gradle.log"
# A software-emulated (TCG) device occasionally kills the instrumentation process itself.
# Such a crash is retried once so the job reports the test suite, not the hypervisor; a real
# assertion failure fails both attempts and still fails the job.
status=1
for attempt in 1 2; do
  if [[ "$attempt" -gt 1 ]]; then
    echo "::warning::Instrumentation attempt $((attempt - 1)) failed; retrying once on the same emulator."
    mv "$LOG" "$DIAG_DIR/molido-instrumentation-gradle.attempt$((attempt - 1)).log"
  fi
  set +e
  timeout --signal=TERM --kill-after=30s 25m gradle --no-daemon --console=plain --stacktrace :app:connectedDebugAndroidTest 2>&1 | tee "$LOG"
  status=${PIPESTATUS[0]}
  set -e
  if [[ "$status" -eq 0 ]]; then
    break
  fi
done
exit "$status"
