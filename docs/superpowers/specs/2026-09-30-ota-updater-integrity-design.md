# OTA Updater Integrity Design

**Finding:** `H_OTA_updater_supply_chain_compromise_due__02` (High)
**Tracker:** [threatmodel-remediation.md](../../security/threatmodel-remediation.md)
**Status:** Design approved by team; pending written-spec sign-off before implementation plan.

## Problem

`web/updater.py` implements AI Gator's OTA update flow: a background loop
(`run_update_check_loop`, wired in from `web/app.py` at startup) polls a GitHub-Pages-hosted
`latest.json` manifest, and on user confirmation downloads and silently launches an installer
(`launch_installer`, gated via `web/routes/updater.py`). Today there is **no integrity check of
any kind** between "file downloaded over HTTPS" and "file executed as SYSTEM-adjacent installer
with `/SILENT`":

- No checksum verification of the downloaded binary against a known-good value.
- No pinning of the manifest's `url` field — a compromised or MITM'd `latest.json` could point
  anywhere.
- No code-signing verification — a dropped-in unsigned or wrongly-signed binary would run exactly
  the same as a legitimate one.

This matches the report's attack path: compromise the `latest.json` manifest or the
download path → attacker-controlled binary silently executed with the privileges of the
AI Gator installer.

**Remediation steps required by the report:** verify integrity (checksum) of downloaded update
packages before install; pin update source URLs; prefer signed packages where feasible.
**Acceptance criteria:** update artifacts are checksum-verified before execution; update source is
restricted to an explicit allow-list; unsigned or tampered packages are rejected and not executed.

## Key discovery: code signing is not a procurement gap

AI Gator already has a working self-signed code-signing pipeline:

- `build/build.bat` signs both `AIGator.exe` and `dist/AIGatorInstaller.exe` with
  `signtool.exe`, using a project-owned `.pfx` (`AIGator_CodeSign.pfx`) and a fixed thumbprint
  `SIGN_THUMBPRINT=B09F5EF43A1D7BF0F97C4883D723BA1AF67A7F42`.
- `build/installer.iss` ships the matching public `.cer` and auto-imports it into
  `Cert:\CurrentUser\TrustedPublisher` at install time, with no admin rights required.

This means every AI Gator install already trusts the exact signing certificate used to sign
future updates. Authenticode signature verification + thumbprint pinning is achievable at **zero
new cost and zero new dependencies** — it only requires reading the thumbprint that already
exists in `build/build.bat` and checking it at download time.

## Design

### 1. Manifest schema + URL/asset pinning

`latest.json` (built by `build/release.bat` step 7, served from GitHub Pages) gains a `sha256`
field alongside the existing `version`/`url`/`notes`:

```json
{
  "version": "1.2.3",
  "url": "https://github.com/mkflyamd/aigator-releases/releases/download/v1.2.3/AIGatorInstaller.exe",
  "sha256": "<64 hex chars>",
  "notes": "See release page for details"
}
```

`build/release.bat` computes this with `certutil -hashfile dist\AIGatorInstaller.exe SHA256`
right after the installer is built and signed, and writes it into the `latest.json` it pushes to
`gh-pages`.

In `web/updater.py`, `check_for_update()` validates the manifest **before** ever setting state to
`"available"`:

- `url` must parse as `https://github.com/mkflyamd/aigator-releases/releases/download/v<version>/AIGatorInstaller.exe`
  (host, path prefix, and asset filename all pinned — no redirects to arbitrary hosts/assets).
- `sha256` must be present and match `^[0-9a-f]{64}$`.

Any manifest that fails either check is treated as "no update available" (same as a network
failure today) and logged with a specific reason. This keeps the existing silent-failure UX for
transient manifest issues while refusing to act on a malformed/tampered manifest.

### 2. Download-time verification pipeline

`download_update()` keeps its existing HTTPS streaming behavior, then adds two checks before
flipping state to `"ready"`:

1. **Checksum:** compute SHA-256 of the fully-downloaded file; compare to `manifest.sha256`.
   Mismatch → fail closed.
2. **Authenticode signature:** run `Get-AuthenticodeSignature <path>` via a PowerShell
   subprocess (using `proc_utils.no_window_kwargs()` to avoid a console flash, consistent with
   other subprocess call sites in this codebase). Require:
   - `Status == Valid`, **and**
   - `SignerCertificate.Thumbprint == EXPECTED_SIGNING_THUMBPRINT`

   `EXPECTED_SIGNING_THUMBPRINT` is a new module constant in `web/updater.py`, set to
   `B09F5EF43A1D7BF0F97C4883D723BA1AF67A7F42` with a comment cross-referencing
   `build/build.bat`'s `SIGN_THUMBPRINT` so the two stay in sync if the signing cert is ever
   rotated.

`Get-AuthenticodeSignature` is chosen over `signtool verify` (not guaranteed present on end-user
machines — it's a Windows SDK tool, not a base OS component) and over raw `WinVerifyTrust`
via ctypes or manual PE/PKCS7 parsing (both reinvent crypto handling and are easy to get subtly
wrong). `Get-AuthenticodeSignature` ships with every supported version of Windows PowerShell.

### 3. Fail-closed behavior + logging

Any failure in the above (bad manifest, checksum mismatch, invalid signature, wrong signer)
results in the same pattern:

- Delete the downloaded file immediately (`tmp_path.unlink(missing_ok=True)`), matching the
  existing cleanup-on-exception behavior already in `download_update()`.
- Set `_state.state = "error"` with a specific, non-sensitive reason string — one of
  `"untrusted source URL"`, `"checksum mismatch"`, `"invalid signature"`, `"untrusted signer"` —
  so the UI can show something meaningful without leaking internals.
- Log the same reason (plus version/URL, never file contents) to `aigator.log`.

`launch_installer()` is unchanged: it already refuses to run anything unless
`_state.state == "ready"` and the file exists, and with the above checks now gating entry into
`"ready"`, this remains the single source of truth for "safe to execute."

### 4. Testing plan

Extend `tests/test_updater.py` following its existing `AsyncMock`/`patch.object` patterns:

- Manifest missing/malformed `sha256` → `check_for_update()` returns `None`, state stays
  `"idle"`/unchanged (treated like a network failure).
- Manifest `url` outside the pinned host/path/asset → same as above.
- Downloaded file with mismatched checksum → `download_update()` ends in `"error"`, temp file
  removed.
- Mocked `Get-AuthenticodeSignature` subprocess output:
  - `Status=Valid` + wrong thumbprint → `"error"`, temp file removed.
  - `Status != Valid` → `"error"`, temp file removed.
  - `Status=Valid` + correct thumbprint + correct checksum → `"ready"`.
- `launch_installer()` still refuses to run when state isn't `"ready"` (existing test, unchanged).

### Residual risk

`EXPECTED_SIGNING_THUMBPRINT` is a hardcoded constant mirrored from `build/build.bat`. If the
signing certificate is ever rotated (expiry, compromise, etc.), both locations must be updated
together, and **existing installations will reject updates signed with a new thumbprint until
they themselves are updated to a version that knows the new thumbprint** — a bootstrapping
problem inherent to any pinning scheme. This is an accepted trade-off: it is the same mechanism
that makes supply-chain compromise of the update channel meaningfully harder. Any future
certificate rotation needs a one-time manual coordination step (documented here so it isn't
forgotten), not a code change to this design.

## Out of scope

- Procuring a CA-issued (non-self-signed) code-signing certificate — not required, since the
  existing self-signed cert is already trusted by every installed copy of AI Gator via
  `build/installer.iss`.
- Changes to `web/routes/updater.py` — it already gates correctly on `_state.state` and needs no
  changes for this fix.
- Delta/incremental update mechanisms — out of scope, unrelated to integrity verification.
