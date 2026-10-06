# Secure store on macOS and Linux — design

**Finding:** `H_Local_OAuth_token_theft_from_filesystem_01` (extends the Windows implementation in
[2026-10-05-oauth-token-storage-design.md](2026-10-05-oauth-token-storage-design.md)).

## Problem

`web/secure_store.py` only has a Windows DPAPI backend. AI Gator ships on Windows, macOS and Linux
(README, `docs/BUILD_INSTRUCTIONS.md`), so on macOS and Linux every token or PAT write raises
`SecureStoreError` and existing plaintext tokens cannot be migrated. That is a regression against the
previous plaintext behaviour and must be fixed before the branch is pushed.

## Approach

Keep the existing blob layer (`~/.gator/secrets/<name>.bin`, migration, shredding, API, callers) and
add a second implementation of `_protect` / `_unprotect` for non-Windows platforms: envelope
encryption. This mirrors Electron's `safeStorage` (Keychain on macOS, libsecret/KWallet on Linux, DPAPI
on Windows, degraded behaviour on Linux when no keyring exists).

- **Windows:** unchanged (DPAPI, current-user scope).
- **macOS / Linux:** blobs are AES-256-GCM encrypted with a random 32-byte master key. The key is stored
  in the OS vault through the `keyring` library (service `AI Gator`, user `secure-store-master-key`,
  base64). One vault entry only, so macOS shows at most one Keychain prompt.
- **Blob format (non-Windows):** `b"\x02" + nonce(12) + ciphertext+tag`; AAD is the existing
  `_ENTROPY` constant. The inner plaintext still starts with `_VERSION` (`\x01`) as today.
- **Backend selection:** `_use_dpapi()` returns `sys.platform == "win32"`; `_protect`/`_unprotect`
  dispatch on it. Tests can force either path.

## Master key lifecycle (`_master_key()`)

Cached in-process behind the existing `_LOCK`.

1. Vault available and holds a key: use it.
2. Vault available, no key: if a fallback key file exists, adopt its key (store in vault, read back,
   then delete the file); otherwise generate a key, store it, **re-read** it and use the re-read value
   (narrows the first-creation race between the server and a skill process; not eliminated).
3. Vault unavailable (`keyring` raises `NoKeyringError`/`KeyringError`, or only the fail backend is
   present):
   - **Linux:** use a key file `~/.gator/secrets/.master.key` (generated if absent), created `0600` and
     written atomically (temp file + link, so it is never partially visible and never overwrites an
     existing key). Protection level becomes `key-file` (reduced). If the vault is
     unavailable, encrypted blobs already exist and no key file exists, no new key is minted:
     `SecureStoreError` is raised and the protection level is `unavailable`, so a transient
     keyring outage cannot orphan existing blobs.
   - **macOS:** raise `SecureStoreError` (a denied or locked Keychain is an explicit user/OS decision;
     no silent downgrade).
4. If the key is lost (vault reset, new profile, deleted file) existing blobs fail GCM verification,
   `get()` returns `None` and the user re-authenticates (same as a DPAPI profile reset). A tampered
   blob behaves the same way.

## Protection level and user notice

`secure_store.protection_level()` returns the string `"os-vault"` (DPAPI, Keychain or Secret Service),
`"key-file"` (Linux fallback) or `"unavailable"` (no usable key source, e.g. macOS Keychain denied or
the Linux outage case in step 3). A small `GET /api/auth/storage` route returns `{"level": ...}`;
Settings shows a notice for `key-file` and `unavailable`. For `key-file`: "Linux keyring not found —
credentials are protected at a reduced level (key stored in a user-only file). Install/unlock
gnome-keyring or KWallet to upgrade." The upgrade happens on the next AI Gator start once a vault
appears (step 2 adoption), because the key is cached per process.

## Dependencies and packaging

- `pyproject.toml`: add `keyring>=25; sys_platform != 'win32'` and `cryptography; sys_platform !=
  'win32'` (cryptography is already locked transitively). Windows packages are unchanged.
  `uv.lock` is regenerated with `uv lock`; `requirements.txt` is updated if it mirrors the project
  dependencies.
- `packaging/aigator-backend.spec`: on non-Windows, add hidden imports for `keyring.backends`
  (entry-point loaded), `copy_metadata("keyring")`, and `secretstorage`/`jeepney` on Linux.
- `keyring` and `cryptography` are imported lazily inside the non-Windows path so the Windows build and
  tests never need them.

## Testing

- Crypto and key lifecycle run on every OS by forcing the non-Windows path and injecting a fake vault
  (seams `_vault_get`, `_vault_set`): round trip, key created once and reused, concurrent first-use
  re-read, tamper -> `None`, lost key -> `None`, key-file fallback on Linux (`0600`, atomic write), Linux outage with existing blobs raises without minting a key,
  adoption of the key file into a newly available vault, macOS vault failure raises, protection level.
- Existing DPAPI tests stay Windows-only; the autouse fake backend in `tests/conftest.py` still
  replaces `_protect`/`_unprotect`, so no other test changes.
- Route test for `GET /api/auth/storage` covering `os-vault`, `key-file` and `unavailable`.
- **Not verifiable here:** real Keychain and Secret Service behaviour. A manual smoke test on one Mac
  and one Linux desktop (save a PAT, restart, confirm it loads; Linux without a keyring shows the
  notice) is a release gate, and the docx states it was not run.

## Documentation updates

Correct the docx statement that AI Gator ships only on Windows; update the OAuth acceptance check,
Known limitations, the tracker row, and `docs/security` notes. Remove "Windows only" from limitations
and add: Linux without a keyring uses a reduced-protection key file; macOS/Linux not tested on real
vaults yet.

## Out of scope

Per-secret vault entries, Microsoft server-side revocation, sandbox backends for macOS/Linux (belongs
to the Code-runner finding), hardware-backed keys, rotating the master key.
