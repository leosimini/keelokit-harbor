# Releasing Harbor

Harbor releases like Keelokit ([its document](https://github.com/leosimini/keelokit/blob/main/docs/releasing.md)),
without the directory and template parts.

| Ref | What it is |
|---|---|
| `main` | Where work lands, always green. Also Harbor's marketplace (`claude plugin marketplace add leosimini/keelokit-harbor`) |
| `release` | The last released commit of `main` |
| `vX.Y.Z` tags | One per release, made by the Release workflow on every push to `release` |
| GitHub Releases | One per tag, made by the same workflow; notes are the version's CHANGELOG entry; `harbor-plugin.zip` attached |

## While working

- Merge into `main` as usual; CI (unit tests and manifests) must be green.
- Add every change a user would notice to `CHANGELOG.md` under `## Unreleased` (`## Unreleased — <title>`
  if the release has a theme). Changes to Harbor's own tooling don't go in.
- Don't touch `version` in `plugin.json`, and don't push to `release` or create tags.

## Cutting a release

1. Check that CI is green on the tip of `main`.
2. Pick the version: patch for fixes and wording, minor for new commands, hooks or rules.
3. Run `scripts/release.sh X.Y.Z` on an up-to-date `main`. It renames `## Unreleased` to
   `## X.Y.Z — <today>`, sets `version`, runs the tests, `claude plugin validate --strict` and
   `scripts/package.sh`, commits `release: X.Y.Z`, and pushes `main` and then `release`.
4. Check that the **Release** workflow created `vX.Y.Z` and its GitHub Release with
   **harbor-plugin.zip** attached. It fails if the CHANGELOG has no entry for the version, if
   `release` isn't a commit of `main`, if the tag is already on another commit, or if the zip doesn't
   pass `scripts/package.sh`'s checks. To attach the zip to a release that lacks it: Actions →
   Release → *Run workflow* with the tag.

A released version isn't reused: fix it in `main` and release the next patch.

## The first release

0.1.0 was cut by hand. It was already the version in `plugin.json`, and `scripts/release.sh` needs a
higher one, so the CHANGELOG entry was written as `## 0.1.0 — 2026-11-07` directly, and `release` was
pushed from the `main` commit that added the release files. Later releases use `scripts/release.sh`.
