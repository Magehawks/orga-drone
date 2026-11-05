# Control API v1 (local proof of concept)

Issue #255 adds an optional application API for one running Studio editor.
It has no MCP adapter or AI-provider dependency. All source media stays on disk
unchanged. Only a paused, available video with static color settings is supported.

## Pairing and lifecycle

Start Orga Drone normally on its loopback address. In Studio, select the video,
open **External control**, paste a locally generated 256-bit pairing key, and
choose **Enable external control**. The key must be 64 lowercase hexadecimal
characters. Generate it with Python `secrets.token_hex(32)`, never a password.
The application stores only its SHA-256 digest in process memory, clears the
password input, and never returns the key. Do not put keys in URLs, shell command
arguments, logs, screenshots, or committed files.

Example Windows Python client setup (interactive Python, local clipboard only):

```python
import secrets, subprocess
key = secrets.token_hex(32)
subprocess.run(
    ["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
    input=key, text=True, check=True,
)
```

Paste into Studio and enable; then clear the clipboard. Keep `key` only in the
test client's memory. The API never generates or discloses a pairing credential.
Every launch starts disabled. Disable immediately revokes the credential and
rejects pending commands; committed outcomes remain committed. Closing the editor
expires its lease after three seconds; reopen and explicitly enable again.
A second live editor is rejected and cannot take over the first editor's session.

Original/reuse previews are temporary source previews, not editable Story clips.
While one is open, editor state reports `clip_id: null` and `ready: false`.
Cancelling restores the previous selection if it is still present. Selection
revision also advances for local interactions; it is not a count of clip changes.

Activation requires a configured loopback bind and a loopback peer. Existing Host
and Origin protection is unchanged. A local client must send both a bearer token
and the exact application Origin on writes (scheme, host, and port must match).
Origin is not authentication. Browser bridge endpoints require same-origin writes
and can execute only previously admitted commands for their active editor session.
This is not isolation from a malicious process already controlling the local app.

## Public endpoints

- `GET /api/control/v1/editor-state`: session/project/clip IDs, playhead, playback,
  readiness, busy flag, opaque state token, and supported current properties.
- `GET /api/control/v1/available-controls`: ranges and available imported creative
  LUT IDs/display names. No filesystem paths or media URLs are returned. Also
  includes the shared action catalog and contract version.
- `GET /api/control/v1/actions`: versioned shared action catalog without paths or
  credentials.
- `POST /api/control/v1/commands`: admit an expiring command; it initially queues.
- `GET /api/control/v1/commands/{command_id}`: retrieve its original outcome.

## Shared action contract

`studio_actions.py` is the transport-neutral action boundary. The Studio UI
routes and this Control API use the same image/color validators, merge rules,
and canonical values; the Control API does not own a second editor. The
capability response exposes only implemented actions:

```json
{"contract_version":1,
 "actions":[{"name":"clip.color.properties","version":1,"scope":"clip",
 "target":"video_clip","reversible":true,
 "parameters":{"contrast":{"type":"integer","minimum":-100,"maximum":100}}}]}
```

Additive actions and parameters keep `/api/control/v1`. Removing or renaming a
field, changing units or target meaning, or changing existing validation
requires `/api/control/v2`. The existing `set_clip_properties` command keeps its
v1 payload and meaning.

Strict JSON bodies are limited to 8192 bytes. Unknown fields and command types
are rejected. Integers exclude booleans and fractions. Omitted properties stay
unchanged. Contrast is the slider value; saturation percent minus 100 is the
existing saturation slider. Creative LUT IDs are catalog asset names, e.g.
`0123456789abcdef0123456789abcdef.cube`; null clears only the creative LUT.

Example client helpers (replace the origin with the actual port):

```python
import json, time, uuid, urllib.request
origin = "http://127.0.0.1:8765"
def api(path, payload=None):
    headers = {"Authorization": "Bearer " + key, "Origin": origin,
               "Content-Type": "application/json"}
    request = urllib.request.Request(origin + "/api/control/v1/" + path,
        data=None if payload is None else json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)

state = api("editor-state")
controls = api("available-controls")
lut_id = controls["creative_luts"][0]["id"]  # Import a LUT manually first.
command = {
    "command_id": uuid.uuid4().hex,
    "type": "set_clip_properties",
    "session_id": state["session_id"],
    "project_id": state["project_id"],
    "clip_id": state["clip_id"],
    "expected_state_token": state["state_token"],
    "expires_at": time.time() + 10,
    "properties": {"contrast": 15, "saturation_percent": 120,
                   "creative_lut_id": lut_id, "creative_lut_strength_percent": 100},
}
admitted = api("commands", command)
outcome = api("commands/" + command["command_id"])
```

Example editor state:

```json
{"session_id":"opaque-editor-id","project_id":1,"clip_id":2,
 "selection_revision":3,"playhead_s":1.5,"playing":false,"busy":false,
 "ready":true,"state_token":"opaque-64-character-token",
 "properties":{"contrast":0,"saturation_percent":100,
 "creative_lut_id":null,"creative_lut_strength_percent":100}}
```

Example committed command (canonical image/color objects are also included):

```json
{"command_id":"client-generated-id","status":"ui_applied","persisted":true,
 "ui_applied":true,"preview_status":"refresh_requested","no_op":false,
 "clip_id":2,"can_undo":true,"can_redo":false,
 "canonical":{"properties":{"contrast":15,"saturation_percent":120,
 "creative_lut_id":"0123456789abcdef0123456789abcdef.cube",
 "creative_lut_strength_percent":100}}}
```

Poll until `ui_applied` or a terminal rejection; do not blindly submit a new ID
after a timeout. Repeating the same ID and exact payload returns the original
outcome. Reusing an ID with another payload returns `COMMAND_ID_CONFLICT`.
Storage is bounded at 1024 IDs per process; at capacity new IDs are refused until
restart, rather than evicting IDs and permitting replay. Expiry is Unix seconds,
strictly in the future and at most 30 seconds away; execution uses a monotonic
deadline too. Read a new state token for each new command.
IDs and selection revisions are bounded to JavaScript's safe integer range;
playhead values are finite and bounded. Invalid numeric or excessively nested
JSON input returns a stable 400 error.

For guarded Undo, send a new command with `type: undo_last_change`, fresh state
token, same session/project/clip fields and expiry, and `undo_command_id` naming
the original successful external edit; omit `properties`. It restores
the latest existing Story history snapshot only if the external edit is still the
latest operation and the original project, clip, and command all match. Selecting
clip B and sending an Undo for an edit to clip A returns `UNDO_CONFLICT` without
changing settings or history. The result includes the actual `project_id`,
`clip_id`, and `undone_command_id`; the bridge checks the selected target before
updating datasets, inspector and preview. Ordinary Studio Redo reloads canonical
project settings and restores the external edit. Verify both
before restart: existing history is intentionally process-local.

```python
state = api("editor-state")
undo = {"command_id": uuid.uuid4().hex, "type": "undo_last_change",
        "undo_command_id": command["command_id"],
        "session_id": state["session_id"], "project_id": command["project_id"],
        "clip_id": command["clip_id"], "expected_state_token": state["state_token"],
        "expires_at": time.time() + 10}
api("commands", undo)
```

## Outcomes and errors

`queued` has not written anything. `persisted: true` is a committed operation
(or successful no-op), independent of acknowledgement. The execute response reports
`persisted`; reads report `persisted_ui_unconfirmed` until the bridge acknowledges
canonical application. `ui_applied` confirms inspector/dataset application.
`preview_status: refresh_requested` means existing preview callbacks were called;
it does not certify a rendered frame or improve existing color fidelity.
Loss of UI acknowledgement does not turn a committed edit into a failed save.
Unconfirmed changes can resynchronize without reexecution while still current;
later manual edits suppress stale canonical replay. Reopen Studio to reload
canonical settings if synchronization cannot be confirmed.

Errors from the control routes use `{"error":{"code":"STALE_STATE"}}`.
Important codes: `CONTROL_DISABLED`, `INVALID_CREDENTIAL`, `LOOPBACK_REQUIRED`,
`INVALID_JSON`, `INVALID_PAYLOAD`, `PAYLOAD_TOO_LARGE`, `INVALID_PROPERTIES`,
`UNKNOWN_COMMAND`, `LUT_UNAVAILABLE`, `MEDIA_UNAVAILABLE`, `UNSUPPORTED_CLIP`,
`ANIMATED_SETTINGS_UNSUPPORTED`, `EDITOR_BUSY`, `EDITOR_NOT_READY`,
`EDITOR_DISCONNECTED`, `EDITOR_SESSION_CONFLICT`, `STALE_SELECTION`, `STALE_STATE`,
`COMMAND_EXPIRED`, `COMMAND_ID_CONFLICT`, `COMMAND_CAPACITY_REACHED`,
`UNDO_CONFLICT`, and `DATABASE_ERROR`. Existing Host/Origin middleware retains its
existing 403 `detail` responses. Manual Studio mutation requests conservatively
invalidate tokens and guarded Undo even when an allowed request fails or is a no-op.
Requests rejected by Host/Origin checks cannot change the revision. An unsuccessful
manual save keeps control busy until Studio is reopened, with an explicit recovery
message; a later successful request cannot prove that every failed local edit was
reconciled. Disabled control does not flush manual editing's save schedulers.

## Automated Windows/WebView2 smoke

An opt-in test uses a hidden Edge/WebView2 window, generated videos and a test LUT
in a temporary library. Run from PowerShell with the normal Python dependencies
and WebView2 runtime installed:

```powershell
$env:ORGA_DRONE_CONTROL_WEBVIEW_E2E = '1'
python -m pytest tests/test_control_webview.py -q
Remove-Item Env:ORGA_DRONE_CONTROL_WEBVIEW_E2E
```

This smoke was executed successfully on Windows with WebView2. It verifies the
real bridge's four-property edit and acknowledgement, correct inspector values,
preview DOM mutation, two-clip Undo rejection, valid Undo, ordinary Redo reload,
disable, a subsequent manual save, and unchanged synthetic source hashes.
Pairing uses the private enable endpoint with the running editor's session, so
the random key never enters evaluated JavaScript or renderer logs. It does not
certify password-entry usability, rendered color fidelity, or the human product
test. The default Python suite skips this opt-in desktop test.

## Windows / WebView2 manual verification (not automated)

1. Start with synthetic media in a configured library root and an imported test
   LUT. Record the source hash. Open Studio in WebView2 and select a paused video.
2. Confirm the API is disabled. Generate the key locally, paste it in the Studio
   disclosure, enable, and read editor state/controls with the client above.
3. Send the four-property example. Poll its outcome. Verify contrast +15,
   saturation slider +20, chosen creative LUT and strength 100 in the inspector.
   Watch the pause preview refresh; do not equate refresh_requested with visual QA.
4. Call the edited clip A. Select another video B and obtain a fresh state token.
   Submit Undo naming B but A's command ID: expect `UNDO_CONFLICT`, no setting or
   history change, and no inspector/preview refresh for the wrong clip. Select A,
   read a fresh token and submit Undo with A's original project/clip/command IDs.
   Verify A's original inspector values and refreshed preview; B stays unchanged.
   Use ordinary Redo and verify A's four values and preview return after reload.
   Make a manual edit; external Undo must conflict.
5. Submit while playing, dragging a slider, waiting for saves, or after changing
   selection A→B→A. Verify rejection with no unintended target or partial save.
6. Open a second Studio window. Confirm session conflict. Close it. Disconnect
   the first window after persistence but before acknowledgement; check that the
   committed result is unconfirmed, then reload canonical values.
7. Restart. Verify persisted settings and empty process-local Undo; old credentials
   fail. Generate a new key and enable again. Disable with playback running;
   verify pending commands/credentials are revoked and manual editing still works.
8. Compare source hashes. Verify no source or existing export was modified.

These steps require human product testing. TestClient/Node and the opt-in WebView2
smoke do not establish rendered color fidelity or replace this human check.

## Remaining adapter work

The separate `orga-drone-mcp` repository still needs its MCP tools, client-side
pairing-key handling, exact Origin/bearer transport, state/readiness checks,
idempotent command polling and honest outcome translation. It must expose only
these supported operations and must never return credentials in tool responses.
