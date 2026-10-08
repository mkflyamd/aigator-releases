# Endpoint Security Requirements for AI Gator

AI Gator is local-first: tokens, logs and skills live under `~/.gator` on the user's device. The device is therefore the security boundary, and AI Gator must run only on AMD-managed endpoints that meet the AMD endpoint baseline.

## Requirements

| Requirement | Owner and source |
|---|---|
| Up-to-date EDR installed and active | AMD IT, AMD-IS-STD-014 Endpoint Security Standard |
| Full-disk encryption enabled | AMD IT, AMD-IS-STD-014 |
| OS security updates applied | AMD IT, AMD-IS-STD-012 Vulnerability and Patch Management Standard |
| Run only on AMD-managed devices, never on personal devices | AMD-IS-STD-030 Use of Personal Devices to Access AMD Data and Resources Standard |

AI Gator adds no new kind of endpoint. It runs on the same managed Windows, macOS and Linux devices that these standards already cover, so no separate enrolment is needed.

## For users

- Install AI Gator only on your AMD-issued device.
- Keep your device's EDR, disk encryption and OS updates on; do not turn them off to run AI Gator.
- Do not copy `~/.gator` to another device or back it up to personal storage. Tokens in `~/.gator/secrets` are encrypted for your user profile and do not move between devices.
- If a device is lost or compromised, report it to AMD IT, then use Settings, Clear tokens, on any working device and revoke your sessions in the connected services.

## For IT

- Distribute AI Gator through AMD's managed software channels. AI Gator signs in through AMD SSO, so a personal device that is not on the AMD network cannot be used with it. The release installers are public GitHub Releases, so the installer file itself is not access controlled, and the app does not check device posture; that stays with AMD device management and SSO.
- What the app protects on a compliant device: tokens are encrypted at rest (DPAPI on Windows; a Keychain or Secret Service key on macOS and Linux), skills and code run in an OS sandbox, and OTA updates are checksum- and signature-verified. See `threatmodel-remediation.md`.
- Residual risk: a compromised endpoint running as the user is a compromise of that user's connected SaaS access. Endpoint controls are the mitigation, which is why the table above applies.
