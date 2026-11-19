# Physical Android device acceptance checklist

Emulator instrumentation is necessary but does not certify a physical handset. Before release, install the unsigned debug build on a supported Android 8+ device and execute the following with a disposable test account and non-production records.

1. Verify app launch, Persian RTL layout, navigation, keyboard/IME resizing and scrolling.
2. Create, edit and delete one greenhouse, crop cycle, activity, inventory item and financial entry. Confirm each local record remains correct after force-stop and reboot.
3. With Wi-Fi/mobile data disabled, create and edit records. Confirm they remain queued and no data is lost.
4. Re-enable connectivity to the configured HTTPS endpoint. Confirm WorkManager drains the queue, server versions advance, and a second device receives the updates.
5. Change the same record independently on two devices while offline. Confirm a conflict is shown and each resolution path (server/local) produces the expected final value on both devices.
6. Sign out and confirm the locally bound account's data is not displayed to another account. Do not attempt account switching without a reviewed export/reset procedure.
7. Verify certificate/TLS behavior, process death during upload, retries, reboot scheduling, battery optimization and low-storage behavior.
8. Verify database backup/restore and key-loss recovery before enabling sensitive production data. Current local Room database is not encrypted as a whole; use only test data until that gap is closed.
9. Record handset model, Android version, app version, test date, test account identifier (non-secret), test outcomes and screenshots in the release evidence.

## Release signing upgrade test

Use only the final approved release keystore. Install a signed baseline APK, then install a higher-version APK signed with the same certificate. Confirm Android accepts the in-place update and that existing local data remains intact. A debug/unsigned APK cannot validate this upgrade path.
