# Licensing review for issue #110

**Status:** review only. Dated 2026-10-24 against commit `49b1612` on
`issue-86-studio-ken-burns`.

This note walks the checklist in
[issue #110](https://github.com/Magehawks/orga-drone/issues/110). It does not
change the license, choose a replacement, or treat source-available as the
current product. Every legal and provenance box in that issue stays open.
The root `LICENSE` file remains the MIT License. No copyright headers were
added or rewritten. No new license text is included here.

Source-available distribution is not OSI open source. This repository must
keep saying “open source” and “MIT” until a later change, after the gates
below, actually replaces those terms.

## What is already true

| Fact | Where it shows up |
|------|-------------------|
| The project license is MIT | Root `LICENSE`; `pyproject.toml` `license = { text = "MIT" }`; GitHub license metadata reports MIT |
| Copyright line is collective, not a named owner | `LICENSE`: `Copyright (c) 2026 orga-drone contributors` |
| Contributions are accepted under MIT | `CONTRIBUTING.md` |
| The public repository description calls the project open source | GitHub description: “Local open-source drone video library manager (DJI Avata 2 first)” |
| Docs and the README still say open source / MIT | `README.md` (including the public Windows zip link), `AGENTS.md`, `docs/PRODUCT_VISION.md` |
| There is no CLA and no SPDX identifier in the tree | No `CLA` file. A search for `SPDX` in source and docs found none |
| First-party Python files do not carry copyright headers | A search for `Copyright (c)` / `SPDX-License` under `src/` found none |
| Published Windows zips exist and are public | Git tags `v1.1.0` through `v1.9.0`. GitHub Release `v1.9.0` is not a draft and attaches `orga-drone-windows-x64.zip` |
| New Windows builds are still a draft-then-publish GitHub path | `.github/workflows/windows-release.yml` and ADR 0012. A matching tag opens a **draft** release. The maintainer publishes it after the Mark-of-the-Web smoke test in `packaging/README.md` |
| Manual workflow runs also upload the zip as an Actions artifact for 30 days | `windows-release.yml` (`retention-days: 30`). The repository is public |
| itch.io is a Draft/Restricted test channel, not a paid launch | `packaging/itch/README.md`, ADR 0013, `packaging/itch_channel.py` (refuses `public`) |
| itch.io pricing is unset | `packaging/itch/README.md`: “Leave pricing and public release unset.” |
| The itch.io page draft still says the app is free under MIT | `packaging/itch/PAGE.md` |
| No workflow runs butler | `packaging/itch/README.md` |

Commit authors on this branch are three git identities and two display names,
all using addresses associated with the maintainer account:

- `Magehawks <niwes.schult@gmail.com>` (79 commits)
- `Niwes Schult <niwes.schult@gmail.com>`
- `Niwes Schult <Niwes.Zimmermann@gmx.de>`

Together the two display names account for 116 commits on this branch.
The 46 pull requests returned by GitHub for this repository are authored by
`Magehawks`. That is a provenance clue. It is not a completed rights audit.
Issue #110 says project ownership alone is not enough to relicense, and the
copyright line names “contributors” rather than one person.

Historical MIT grants stay in force for the trees and artifacts already
published under MIT. This review does not delete tags, releases, or the
`LICENSE` file, and it does not treat clone or download counts as evidence
that nobody holds a copy.

## Legal and provenance gates

These are the blockers in the issue. None of them is closed by this document.

### Rights to relicense

Still open.

What the tree shows:

- One MIT `LICENSE`, copyright “orga-drone contributors”.
- No contributor license agreement, no copyright assignment, and no record
  in-repo that every committer agreed to a later relicensing.
- Git history on this branch uses the three identities above. Whether those
  identities are one person, and whether every line in the history is that
  person’s copyright, is a decision for the human (and counsel if needed).
- Vendored and generated files can carry other people’s copyright even when
  `git shortlog` shows one maintainer. See the dependency inventory below.
- Imported snippets are not catalogued.

A future license change needs a written provenance conclusion: who owns the
copyright in the first-party code, which commits or files are excluded, and
why “orga-drone contributors” can or cannot be replaced. This review does
not make that conclusion.

### Third-party dependencies, assets, and binary notices

Still open. The list below is a starting inventory of what is in the tree.
It does not state that binary redistribution under a new Orga Drone license
is allowed. Where the upstream license text is not stored in the repository,
that gap is itself part of the gate.

| Item | What the repo records | Gap that still blocks a new license |
|------|------------------------|-------------------------------------|
| Python dependencies in `pyproject.toml` / `requirements.txt` | fastapi, uvicorn, jinja2, python-multipart, pillow, pillow-heif, python-dotenv, imageio-ffmpeg, pywebview, reverse-geocoder | No notices file. Each license and its binary-redistribution terms are unreviewed here |
| FFmpeg via imageio-ffmpeg | `packaging/orga-drone.spec` bundles it into the Windows onefolder. `packaging/README.md` says end users do not need ffmpeg on PATH | The license of the bundled ffmpeg build is not recorded. GPL vs LGPL and whether the build’s notices ship inside the zip are unverified |
| PyInstaller 6.22.3 | Pinned for the Windows onefolder (`packaging/README.md`, release workflow) | Bootloader / tool license is not recorded in the repo |
| Leaflet 1.9.4 | Vendored under `src/orga_drone/static/vendor/leaflet/`. File header: “(c) 2010-2023 Vladimir Agafonkin, (c) 2010-2011 CloudMade” | No Leaflet license file next to the vendored copy |
| Leaflet.markercluster | Vendored JS/CSS under `src/orga_drone/static/vendor/leaflet.markercluster/` | No license header and no license file in that folder |
| Lucide 0.469.0 | `src/orga_drone/static/vendor/lucide/README.md` says ISC | The ISC text is not in the tree |
| Outfit, Sora, IBM Plex Mono | `src/orga_drone/static/fonts/NOTICE.txt`: SIL Open Font License 1.1, via Fontsource, originally Google Fonts | The OFL text is not in the tree. Reserved font names and attribution duties are not checked here |
| OpenStreetMap tiles | Runtime map tiles; README says they need a network | Not vendored. Attribution and tile-usage terms for a paid build are not reviewed |
| Edge WebView2 | itch.io page draft says current Windows 10/11 usually already have the runtime | Not documented as a redistributed Microsoft component. Confirm the zip does not ship a runtime the app is not allowed to bundle |

Map tiles, fonts, Leaflet, Lucide, and ffmpeg keep their own licenses if the
project license changes. Issue #110 forbids rewriting third-party code to
escape those terms.

### Selected source-available license

Still open.

No license was selected. Aseprite is only the issue’s example of a
source-available commercial model. This review does not copy Aseprite’s
license, adapt it, or draft substitute terms. Whether that text may be used
or adapted is a legal question for the human. If that review is not finished
before a launch, the issue’s own priority applies: do not ship under
unverified restrictive terms. Delay that release, or ship the existing MIT
version and say so.

### Historical MIT versions

Still open as a written policy, even though the artifacts are still there.

Already true, and left unchanged:

- Tags `v1.1.0` through `v1.9.0` are in git.
- GitHub Releases for those tags exist. `v1.9.0` is public and includes
  `orga-drone-windows-x64.zip`.
- The current `LICENSE` on this branch is still MIT, so source at this
  commit is still MIT.

Still undecided:

- A short public statement that those tags and release assets stay MIT, and
  that a later source-available tree does not revoke them.
- Where that statement will live (release notes, README, license FAQ) after
  a real license change.
- Confirmation that no maintainer action will delete or replace historical
  release assets in a way that implies the MIT grant was withdrawn.

## What a later source-available change would have to touch

Do this only after the gates above are closed and a reviewed license text
exists. This pull request does not edit these files.

| Issue checklist item | Surfaces |
|----------------------|----------|
| License and notices | Root `LICENSE`; `pyproject.toml` `license`; any future SPDX identifiers; notices for third parties. First-party copyright headers are absent today, so a later header pass would be new text, not a rewrite of existing headers. Do not invent that text in advance |
| Stop calling the project open source | `README.md`, `AGENTS.md`, `docs/PRODUCT_VISION.md`, `CONTRIBUTING.md`, `.cursor/agents/product-spec-reviewer.md`, `.cursor/agents/product-ux-designer.md`, GitHub repository description, itch.io page, release notes |
| Plain-language FAQ | New doc, clearly subordinate to the legal license. Topics the issue names: viewing source, self-compilation, personal use, modification, sharing, redistribution, commercial use, official builds, upgrade policy |
| Buyer entitlements | itch.io page copy and a bounded update policy. See the proposal below. Not lifetime upgrades, not a support contract |
| GitHub no longer publishes the new official zip | `.github/workflows/windows-release.yml` (draft release **and** the 30-day public artifact), ADR 0012, `README.md` download links, `packaging/README.md` publish steps. CI tests (Ruff, MyPy, pytest) stay. Source stays readable |
| itch.io as the paid Windows channel | `packaging/itch/README.md`, `packaging/itch/PAGE.md`, `packaging/itch_channel.py` (today it refuses a public page), ADR 0013. Versioning, checksums, release notes, and the existing MOTW smoke test still apply. The A→B test record is a separate gate and is not a paid launch |
| Old MIT links stay honest | README and release notes must keep historical zips available as MIT and must not point a new paid build at `releases/latest` if that URL would serve it for free |
| Marketplace, payment, VAT | itch.io project settings. Not in git. The helper leaves pricing unset on purpose |
| Release gate | A checklist the maintainer runs before the first release under the new terms: license text, third-party notices, source still public, paid download path, no accidental public zip |

Acceptance criteria in the issue are not met. In particular, a user cannot
yet be told that public redistribution of new builds is restricted, because
the license is still MIT and the Windows zip is still a public GitHub
download. A clean-machine test of a paid zip is not possible from this
change, because no paid zip is published here.

## Proposed €10 itch.io positioning

Proposal only. It is not applied to `packaging/itch/PAGE.md`, the README,
GitHub releases, or the live itch.io project.

**Current packaging behavior**

- The official convenient Windows file is `orga-drone-windows-x64.zip`
  (PyInstaller onefolder: `orga-drone.exe` plus `_internal`).
- The README links to
  `https://github.com/Magehawks/orga-drone/releases/latest/download/orga-drone-windows-x64.zip`.
- The release workflow can attach that zip to a draft GitHub Release. The
  maintainer publishes the draft after the MOTW smoke test. `v1.9.0` is
  already public.
- `workflow_dispatch` uploads the same zip as an Actions artifact for 30 days.
- itch.io, if used, is documented as another convenience copy of the same MIT
  app. Page visibility must stay Draft or Restricted. `itch_channel.py`
  refuses a public target and does not upload. Pricing is unset. There is no
  in-app updater. ZIP copies do not enroll in itch.io desktop-app updates.
  User data stays in `%APPDATA%\orga-drone`.

**Proposed buyer story, after the legal gates, for a future version only**

- €10, one time, for the official Windows build on itch.io.
- The buyer may keep using the version they purchased.
- Updates are an explicit bounded policy. Do not promise lifetime upgrades
  or support. The bound (which versions, how long) is not chosen in this
  review.
- Source of that future version would stay publicly readable, under the
  reviewed source-available terms, not under a claim of OSI open source.
- Historical MIT tags and their GitHub zips would stay MIT.
- No DRM, online activation, telemetry, or account requirement (out of scope
  in the issue, and already not how the app works).

Suggested page facts to write later, in place of the current “free under the
MIT license” paragraph, once a license file actually changes:

- Price: €10 one-time for this official Windows build.
- What you get: that Windows onefolder build, for ongoing use of the
  purchased version.
- What you do not get: a promise of every future version, or a support
  contract. State the real update bound in the same paragraph.
- Source: link the repository and name the new license. Say that older
  releases through the last MIT tag remain MIT.
- Updates: itch.io desktop-app installs can receive builds the maintainer
  publishes on that channel. A ZIP installed by hand does not. There is no
  update button inside the app.
- Files: library, Studio projects, and settings stay in
  `%APPDATA%\orga-drone`. Footage stays in the folders the user added.

Do not paste that into the live itch.io page while `PAGE.md` and `LICENSE`
still say MIT.

## Decisions still blocked on the human

No license file should change until these are decided:

1. **Ship path if the legal review is not finished.** Delay the first
   release that uses a restrictive license, or consciously ship the next
   version under the existing MIT terms. Do not publish restrictive terms
   that have not been reviewed.
2. **Provenance.** Confirm whether the three git identities are one copyright
   holder, whether any commit contains someone else’s code, and whether the
   “orga-drone contributors” line can be changed. There is no CLA to rely on.
3. **Dependency and binary notices.** Complete the inventory above, including
   the bundled ffmpeg build, PyInstaller, Leaflet, Leaflet.markercluster,
   Lucide, the OFL fonts, Python dependencies, and OSM tile terms. Record
   the notices a Windows zip must ship.
4. **The license text.** Choose a source-available license only after legal
   review. Decide separately whether Aseprite’s license may be used or
   adapted. Do not paste an unreviewed draft into `LICENSE`.
5. **What €10 includes.** One-time purchase of the official Windows build,
   ongoing use of that purchased version, and a written bound on updates.
   Name the bound. Do not promise lifetime upgrades or support.
6. **Where new Windows zips live.** Stop attaching new official zips to
   public GitHub Releases, and decide what happens to the 30-day Actions
   artifact, before itch.io is the paid channel. Keep historical MIT release
   assets available and label them as MIT.
7. **itch.io commerce.** Pricing, VAT, and payment stay platform
   configuration. The in-repo channel must stay Draft or Restricted until
   the existing MOTW smoke test and the A→B test record say otherwise. A
   public paid page is a later step, not this review.
8. **Wording owner.** Who signs the copyright line, who publishes the FAQ,
   and who checks the release gate on the first non-MIT release.

Until those decisions exist, the honest public claim remains: Orga Drone is
MIT, source and the published Windows zips included, and the itch.io path is
an unpublished test channel with pricing unset.
