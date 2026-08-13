# README documentation review

## Reviewer roles

- Information architecture reviewer: checked whether README content belongs in the project overview or the detailed build guide.
- Consistency reviewer: compared installation status, source-build guidance, links, and current packaging behavior.

## Consensus

The README duplicated the build guide and gave broken legacy installers more prominence than supported native packages. It also linked to stale or nonexistent setup documents. The README should remain a concise product entry point, while `docs/BUILD_INSTRUCTIONS.md` is the authoritative source for development, source builds, packaging, and release operations.

## Prioritized findings

1. The one-line and downloaded source installers were described as working and recommended even though they are temporarily unavailable.
2. The source-install walkthrough duplicated and conflicted with `docs/BUILD_INSTRUCTIONS.md`.
3. Links to root-level `GETTING_STARTED.md` and `BUILD_INSTRUCTIONS.md` were broken. The existing `docs/GETTING_STARTED.md` is also obsolete and describes an earlier PowerPoint and Claude Code workflow.
4. Gateway configuration was duplicated in the README and `docs/gateway-setup.md`.
5. The release link was not clickable, and unsigned alpha package behavior was not stated near the download instructions.

## Resolution

- Made GitHub Releases the primary end-user installation path.
- Marked single-line installers as coming soon without publishing nonfunctional commands.
- Pointed source and development users to `docs/BUILD_INSTRUCTIONS.md`.
- Marked the legacy bootstrap scripts unavailable in the build guide.
- Removed duplicate configuration and enterprise deployment examples from the README.
- Removed links to the obsolete getting-started guide.

## Remaining documentation debt

- `docs/GETTING_STARTED.md` should be rewritten or archived because it no longer describes AI Gator's current desktop workflow.
- `docs/dev_INSTRUCTIONS.md` and `docs/Gator101.md` should be reviewed against the current Electron architecture before they are promoted from the docs directory.
