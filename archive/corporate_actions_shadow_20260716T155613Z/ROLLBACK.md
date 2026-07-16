# Isolated rollback transaction

1. `launchctl bootout gui/501/com.atlas.corporate-actions-shadow` (ignore absent unit).
2. Remove only `~/Library/LaunchAgents/com.atlas.corporate-actions-shadow.plist`.
3. Atomically rename `/Users/yasser/scripts/corporate_actions_shadow_observer` into the timestamped deployment backup.
4. Preserve the append-only shadow DB as audit evidence, or archive it only with explicit approval.
5. Verify `atlas.db` and production source hashes equal deployment preimages and that Perme V1.2 is unchanged.

No production preimage restoration is ordinarily needed because this release adds a separate directory/unit/DB and changes no existing production file.
