# User needs and feedback

Orga Drone listens to concrete pain points. A report on this path is **evidence**.
It is not a feature request by itself, and it is not a promise that the project
will build something.

Product priorities stay in [`ROADMAP.md`](ROADMAP.md). Nothing on that list
changes because a user-need issue was opened or accepted. A roadmap edit is a
separate maintainer decision.

This path does not add a voting site, an account beyond GitHub's own issue
login, a scraper for Reddit or other forums, or a count of requests.

## Direct feedback and external research

Use the **User need** issue form
(`.github/ISSUE_TEMPLATE/user-need.yml`).

| Kind | Meaning |
|------|---------|
| **Direct feedback** | The reporter uses Orga Drone, or tried to, and is describing their own goal. |
| **External research** | The reporter is describing someone else's pain point: a conversation, a public post, or an observation. That person did not file a request. |

External research must not be rewritten as "users want X" or placed on the
public roadmap. It can support a later product issue only after a maintainer
accepts the need and states scope, non-goals, and acceptance criteria.

A proposed product change still uses the **Feature request** form and the
gates in [`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md). A broken behavior still uses
the **Bug report** form.

## How to report

1. Search [open issues](https://github.com/Magehawks/orga-drone/issues?q=is%3Aissue%20label%3Auser-need) for the same problem.
2. Open a **User need** issue.
3. Fill in the user goal, target user, workaround, evidence, platform, and reproducibility.
4. Source is optional. Add a public link or a short note when the problem came from somewhere else. Do not paste private messages.
5. Choose whether maintainers may quote the report.

Opening the issue applies `user-need` and `feedback:needs-triage`.

## Privacy

Do not upload personal media. The form has no file field on purpose.

Leave out:

- photos and videos from real flights
- SRT files and flight logs
- screenshots that show people, homes, or precise locations
- full disk paths, account names, and home coordinates

Describe the case in text. If a maintainer asks for a file later, send a
synthetic or fully redacted sample and say that in the comment.

Security issues stay private. Follow [`SECURITY.md`](../SECURITY.md).

## Status labels

These labels track intake only. They are separate from the `status:*` labels
in [`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md). One issue keeps `user-need` and
exactly one `feedback:*` label.

| Label | When |
|-------|------|
| `user-need` | Every issue opened from the User need form. |
| `feedback:needs-triage` | Waiting for the monthly review. |
| `feedback:accepted` | A maintainer accepted it as a candidate and linked a product issue. Not a roadmap promise. |
| `feedback:declined` | Reviewed, with a short reason, and will not be pursued. |
| `feedback:shipped` | The related change is in a published release, and this issue links the release notes. |

Suggested label colors, if they are missing on the repository:

| Label | Color |
|-------|-------|
| `user-need` | `#1D76DB` |
| `feedback:needs-triage` | `#FBCA04` |
| `feedback:accepted` | `#0E8A16` |
| `feedback:declined` | `#C5DEF5` |
| `feedback:shipped` | `#5319E7` |

## Monthly triage

Once a month, a maintainer reviews every open issue labeled `user-need` and
`feedback:needs-triage`.

For each issue:

1. Close duplicates with a link, and replace the status label with `feedback:declined`.
2. If personal media or precise locations were posted, ask the reporter to remove them before discussing the content. Do not copy that material into other issues.
3. Read the origin field. Keep external research labeled as evidence in the comment. Do not treat it as a request from the person who was quoted.
4. Record **scope and non-goals** on the issue before any accept decision.
5. Choose one outcome:
   - **Needs more information.** Leave `feedback:needs-triage` and ask one question.
   - **Decline.** Comment with the reason, remove `feedback:needs-triage`, add `feedback:declined`.
   - **Accept.** Only a maintainer does this. Remove `feedback:needs-triage`, add `feedback:accepted`, and link a product issue that includes the target user, a link back to this evidence, scope, non-goals, and acceptance criteria. That product issue still follows the normal PM / UX / CTO gates. Do not edit [`ROADMAP.md`](ROADMAP.md) in the same step.

There is no target number of accepts, and no vote tally.

## From an accepted need to release notes

When the product issue ships:

1. Name the user-facing change in the release notes (`releases/<version>/RELEASE_NOTES.md` and the GitHub Release for that version).
2. Comment on the user-need issue with that release URL.
3. Put the same URL in the issue's **Release notes link** field if you edit the body.
4. Respect the reporter's attribution choice. Skip the quote when they opted out.
5. Remove `feedback:accepted` and add `feedback:shipped`.

The product issue should mention the user-need issue so the chain is
user need → product issue → release notes, in both directions.

## What this process does not do

- It does not publish a roadmap item without a maintainer choosing to edit [`ROADMAP.md`](ROADMAP.md).
- It does not turn a forum thread into a feature request.
- It does not collect files, accounts, or votes.
- It does not scrape external sites.
