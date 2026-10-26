# ADR 0024: Licensing model for paid Windows builds

- **Status:** Proposed. This record is not a license change. Merging it does
  not adopt a new license, does not replace `LICENSE`, and does not change
  GitHub license metadata.
- **Date:** 2026-10-26
- **Deciders:** None yet. Issue
  [#145](https://github.com/Magehawks/orga-drone/issues/145) requires the
  maintainer to confirm the model before any license file changes. This
  document is not legal advice and does not clear a license.

Related: issue #145, the earlier checklist review in
[`docs/LICENSING_REVIEW_110.md`](../LICENSING_REVIEW_110.md) (issue #110,
dated 2026-10-24). That review stays as a historical note. Facts below were
re-checked against `origin/main` at `4bdfe8b` (tag `v2.0.0`).

## Context

The maintainer wants an Aseprite-inspired arrangement: the source stays
publicly viewable, and official Windows builds are sold on itch.io. Issue
#145 asks for that choice to be written down, with the rights and dependency
consequences, **before** `LICENSE` is edited.

Two different goals are easy to mix up:

1. Charge money for an official Windows build.
2. Stop other people from redistributing the source or that build.

MIT already allows (1). Only a different, later license could even attempt
(2), and only for code that is not already published under MIT.

## What is already true

| Fact | Evidence |
|------|----------|
| The project license is the MIT License | Root `LICENSE`; `pyproject.toml` `license = { text = "MIT" }`; GitHub license metadata `MIT` |
| Copyright line is collective | `LICENSE`: `Copyright (c) 2026 orga-drone contributors`. `pyproject.toml` uses the same author name |
| Contributions are accepted under MIT | `CONTRIBUTING.md` |
| There is no CLA, DCO, or copyright assignment | No `CLA` file. No `Signed-off-by` trailers in history |
| First-party sources have no copyright headers | No `Copyright (c)` under `src/` outside the need to treat vendored files separately (Leaflet’s header is third-party) |
| Published git tags `v1.1.0` through `v2.0.0` point at trees that include this MIT `LICENSE` | Remote tags. `v2.0.0` is `4bdfe8b`, which is current `main` |
| GitHub Release `v2.0.0` is public and not a draft | Release has **no** uploaded zip asset |
| GitHub Release `v1.9.0` is public and attaches `orga-drone-windows-x64.zip` | `gh release view v1.9.0` |
| itch.io is still a Draft/Restricted test channel | `packaging/itch/README.md`, ADR 0013. `packaging/itch/PAGE.md` says the app is free under MIT |
| README still calls the source MIT and the app open source | `README.md` license section and project-status paragraph |
| GitHub About no longer uses the old “open-source drone video library manager” sentence | See “GitHub About” below. The license field is still MIT |

Already released commits, tags, and release assets stay MIT. Nothing in this
proposal revokes those grants, retags them, or rewrites `v2.0.0`.

## Contributor and copyright finding

Checked on `origin/main` (192 commits):

| Identity | Role | Count |
|----------|------|------:|
| `Magehawks <niwes.schult@gmail.com>` | author | 124 |
| `Niwes Schult <niwes.schult@gmail.com>` | author | 37 |
| `Niwes Schult <Niwes.Zimmermann@gmx.de>` | author | 31 |
| `Magehawks <niwes.schult@gmail.com>` | committer | 124 |
| `GitHub <noreply@github.com>` | committer | 68 |

GitHub’s contributor list for this repository contains only `Magehawks`.
All 70 pull requests returned by GitHub are authored by `Magehawks`. No other
human author appears in `git shortlog` on `origin/main`.

149 commit messages contain `Co-authored-by: Cursor <cursoragent@cursor.com>`.
That is tool attribution on the maintainer’s commits. It is not a second
GitHub contributor, and it is not a recorded copyright assignment. Whether
tool-assisted output affects copyright in a given country is an open question
for the maintainer and counsel, not a finding that an outside person holds
copyright.

This is **not** a completed rights conclusion:

- The `LICENSE` copyright line names “orga-drone contributors”, not one
  person. There is no document in the repo that assigns that copyright to
  `Magehawks` or Niwes Schult.
- The two display names and two email addresses look like one person. Only
  that person can confirm they are the same copyright holder.
- Vendored files and dependencies are other people’s copyright even when
  `git shortlog` shows one maintainer. See below.
- No audit was done for pasted snippets that lack their own commits.

Because that confirmation is missing, and because no replacement license has
been chosen, this PR does not replace `LICENSE`.

## Third-party constraints that matter

A new Orga Drone license would not relicense these works. Several of them
also limit what a **restrictive** license can say about the Windows zip.
Permissive notices are still required when redistributing binaries. This
inventory is not a notice file and does not copy upstream license text.

| Item | What was checked | Why it matters |
|------|------------------|----------------|
| FFmpeg binary bundled via imageio-ffmpeg 0.6.0 | The Python package is BSD-2-Clause. The exe in a local 2.0.0 onefolder is `ffmpeg version 7.1-essentials_build-www.gyan.dev` with `--enable-gpl --enable-version3` and GPL-licensed libraries including libx264 and libx265. The repo does not ship FFmpeg’s license text or a source offer | The binary is a GPL build. A later Orga Drone license cannot add “no redistribution” terms on top of that GPL program. Whether invoking FFmpeg as a separate process makes the whole app a GPL derivative is **not decided here** |
| `reverse-geocoder` 1.5.1 | Imported from `src/orga_drone/geocode/__init__.py`. Upstream `LICENSE` is the GNU Lesser General Public License 2.1 | LGPL-2.1 duties (notices, and the user’s ability to replace the library) apply to this imported dependency. A restrictive application license has to stay compatible with those duties, or this dependency has to be removed before such terms are used |
| PyInstaller 6.22.3 | PyPI describes it as GPLv2-or-later with an exception that allows building and distributing non-free programs, including commercial ones | Selling a build is within the stated exception. The exception text is not recorded in this repo. The exception does not relax the FFmpeg or `reverse-geocoder` duties |
| imageio-ffmpeg, FastAPI, Pillow, pythonnet, pywebview, Jinja2, Uvicorn | Package metadata: BSD-2-Clause, MIT, MIT-CMU, MIT, BSD-3-Clause, BSD, BSD-3-Clause respectively | Permissive. Binary redistribution still needs their notices. Not a reason to block a paid MIT build |
| `pillow-heif` | PyPI lists the Python package as BSD-3-Clause. The native libheif build inside the Windows zip was not inspected | Do not assume the native library is BSD. Check it before relying on a restrictive app license |
| Leaflet 1.9.4 | Vendored at `src/orga_drone/static/vendor/leaflet/`. Header: “(c) 2010-2023 Vladimir Agafonkin, (c) 2010-2011 CloudMade”. Upstream `v1.9.4` `LICENSE` begins “BSD 2-Clause License”. That text is not in this repo | Keep the copyright and add the BSD text to a notices file before a paid zip is presented as fully noticed |
| Leaflet.markercluster | Vendored JS/CSS have no license header and no license file. Upstream publishes `MIT-LICENCE.txt`. The vendored revision is not identified in the tree | Same notices gap. Do not treat the file as first-party |
| Lucide 0.469.0 | `src/orga_drone/static/vendor/lucide/README.md` says ISC. The ISC text is not in the tree | Permissive, notice still missing |
| Outfit, Sora, IBM Plex Mono | `src/orga_drone/static/fonts/NOTICE.txt`: SIL Open Font License 1.1, via Fontsource | OFL applies to the fonts. The OFL text is not in the tree. Reserved font names were not checked |
| OpenStreetMap tiles | Fetched at runtime, not vendored | Tile-usage policy and attribution are operational duties for a paid app. They are separate from the Orga Drone copyright |
| Edge WebView2 | Page draft says current Windows 10/11 usually already have the runtime | Not documented as a redistributed Microsoft component |

There is no root `NOTICE` file.

## Comparison

### A. Keep MIT, and charge for official Windows builds

MIT already grants the right to use, copy, modify, publish, distribute,
sublicense, and sell the software, provided the copyright and permission
notice are kept.

Practical consequences:

- Official itch.io builds can be paid. The price is a distribution choice,
  not a new license.
- Anyone else may also build, give away, or sell the same source, including
  a fork of tag `v2.0.0` and a copy of the `v1.9.0` zip.
- GitHub can stay public. Forks, pull requests, and the current
  `CONTRIBUTING.md` sentence remain coherent.
- Calling the project open source remains accurate.
- The maintainer can still ask people to buy the official build for support
  or convenience. The license cannot make that the only lawful copy.
- GPL FFmpeg and LGPL `reverse-geocoder` still need compliant notices. MIT
  does not remove those duties, but MIT does not add a conflicting
  “no redistribution” rule.
- Historical releases stay MIT, which is the same grant they already have.

This matches “source stays publicly viewable” and “official Windows builds
are sold”. It does not match “other people may not redistribute”.

### B. Source-available terms that restrict redistribution

“Source-available” here means the git repository stays public to read, while
a future license limits copying, forking, selling, or sharing the code and/or
the official binaries. That is not Open Source as defined by the Open Source
Initiative, and the README would have to stop saying open source **if and
only if** `LICENSE` actually changes.

Practical consequences:

- Tags `v1.1.0` through `v2.0.0`, including the current `main` commit, would
  remain MIT. Anyone could keep redistributing those trees and the `v1.9.0`
  zip. A new license would cover only later commits. It cannot make the app
  that exists today exclusive.
- Forks of the MIT history would remain lawful. Forks of later commits would
  depend on the future text. GitHub’s fork button would still exist; the
  license, not the button, would be what a court looks at.
- New outside contributions cannot be accepted under today’s MIT
  `CONTRIBUTING.md` sentence and then placed under a restrictive license.
  A CLA or an equivalent inbound grant would be needed **before** those
  contributions are merged.
- The Aseprite end-user license is Aseprite’s own text. This proposal does
  not copy it, adapt it, or treat it as available for Orga Drone. Copying it
  into `LICENSE` would be a copyright problem of its own, and it would still
  have to be checked against the GPL FFmpeg binary and the LGPL geocoder.
- A restrictive license on the Windows zip conflicts, at least for the FFmpeg
  executable, with GPL redistribution rights. Shipping that exe inside a
  “do not redistribute” product is an unresolved legal conflict, not a
  packaging detail.
- Community expectation changes: fewer forks and drive-by fixes are a likely
  result, which is the point of the restriction and also the cost.

## Rights required, and what is still open

Replacing `LICENSE` for future versions needs, at minimum:

1. The copyright holder’s authority over every first-party line that would be
   covered. Project admin rights on GitHub are not that authority. The
   finding above is evidence to review, not that authority on its own.
2. A named license that already exists and that the owner is allowed to
   apply, or a text written for this project by counsel. An invented
   “Aseprite-like” license in this repo would not meet that bar.
3. A dependency story that does not put GPL or LGPL code under extra
   restrictions those licenses forbid.
4. A written statement that `v1.1.0` through `v2.0.0` stay MIT.

Open questions the maintainer must close before any `LICENSE` replacement:

1. Which model is wanted: paid official builds under MIT, or a later
   restrictive license whose text is still unchosen?
2. Are `Magehawks`, both `Niwes Schult` addresses, and “orga-drone
   contributors” one copyright holder, with no other human author?
3. Does the maintainer want counsel to look at the Cursor co-author trailers?
4. Which published license, if any, may be used? Aseprite’s text is not
   cleared for copying.
5. How will the GPL FFmpeg essentials build and LGPL-2.1 `reverse-geocoder`
   be shipped if redistribution of the app is restricted? Replace them, or
   keep terms that those licenses allow?
6. Will the first itch.io sale happen under MIT while those questions are
   open, or will the sale wait? Issue #145 forbids publishing a restrictive
   license that has not been reviewed.
7. Trademark in the name “Orga Drone” was not searched. A name is not a
   substitute for a copyright license.
8. Where the permanent public MIT statement will live after a real change
   (release notes and README). This proposal is the statement for now.

## Recommendation for future versions

This is a product recommendation, not a cleared license and not legal advice.

Until the questions above are closed, keep the MIT `LICENSE` and, if the
maintainer wants to charge, sell the official Windows build on itch.io
**under MIT**. Say in public that the source and the existing releases may
also be copied. That is the only model that matches the code already
published at `v2.0.0`.

If, after `v2.0.0`, the maintainer still wants redistribution limits on
**new** work:

- Do not copy the Aseprite license into this repository.
- Do not treat a custom draft as legally safe.
- Get a lawyer to name an existing license the owner may use, or to write
  the text.
- Apply it only to commits after tag `v2.0.0`. Leave `v1.1.0` through
  `v2.0.0` and their assets MIT. Do not move the `v2.0.0` tag.
- Put a CLA in place before merging anyone else’s code under the new terms.
- Resolve the GPL FFmpeg build and LGPL `reverse-geocoder` first. A
  restrictive license that the Windows zip cannot satisfy should not ship.
- Add a third-party notices file. Do not relicense Leaflet, markercluster,
  Lucide, the fonts, or FFmpeg.
- Stop calling the project open source only in the commit that changes
  `LICENSE`.
- Keep GitHub license metadata on MIT until that commit exists.

## Decision

No license change is made.

`LICENSE` stays the MIT License. `pyproject.toml` stays `MIT`. GitHub license
metadata must stay MIT. Published versions `v1.1.0` through `v2.0.0` stay
MIT, including the source at tag `v2.0.0` and the `v1.9.0` Windows zip.

The maintainer can adopt a model later by a separate pull request that
changes `LICENSE` only after the open questions are answered and a real
license text is chosen. This ADR does not authorize that pull request.

## Alternatives considered

1. Replace `LICENSE` now with a source-available text modeled on Aseprite.
   Rejected. The text is not ours to copy, contributor authority is not
   closed, and the bundled GPL FFmpeg build was not reconciled with a
   no-redistribution term.
2. Invent a short custom license and mark it as the project license.
   Rejected. Issue #145 forbids presenting an invented license as legally
   safe.
3. Keep MIT, document that paid itch.io builds are allowed, and leave
   exclusivity out of the license. This is the recommended path for the
   software that is already published. It is not adopted as a pricing
   decision; itch.io pricing stays unset until the maintainer says otherwise.
4. Change README, About, and `CONTRIBUTING.md` so they no longer say MIT or
   open source. Rejected for the effective text. The license is still MIT.
   Only a clearly marked draft note is added so readers can see that a change
   is proposed and not in force.

## Consequences

- Positive: the rights gap is written down before a sale or a relicensing.
  Historical MIT grants stay intact.
- Negative: official builds of the current code cannot be made exclusive.
  Anyone may redistribute `v2.0.0`.
- Follow-up, only after the maintainer decides: notices file, itch.io page
  wording, and a later license PR if a reviewed text exists. No Studio or
  export code belongs in that work.

## GitHub About

Not changed by this PR. Repository settings are outside the diff, and the
license field must keep reporting MIT.

Current description (already factual, and no longer the sentence quoted in
issue #110):

> Local-first drone media library with flight metadata, telemetry, map exploration and a built-in video studio. Windows desktop app.

Proposed description, if the maintainer wants wording aligned with the
product sentence. Do not apply it as part of a license switch, and do not
add “open source” or a new license name:

> Local-first drone media library with flight metadata, telemetry, map exploration, and a Studio memory editor. Windows desktop app.

License metadata to leave unchanged: **MIT License**.

## Draft notes elsewhere

`README.md` and `CONTRIBUTING.md` carry a short **DRAFT — not in effect**
paragraph pointing here. Those paragraphs are not a license. The MIT
`LICENSE` file governs.
