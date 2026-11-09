# Studio

**Question:** How do I turn clips into a short Story?

1. Open **Studio** and pick or create a project.
2. Add photos/videos from Browse or the Studio media list.
3. Drag clips to reorder. On videos, drag the left/right edges to trim.
4. Use Fit / zoom / **10 s** / **1 s** on the timeline to find a cut. Compact tracks is optional.
5. Add transitions, music, image adjustments, masks, and title cards as needed.
6. Preview with Play. Export when you are happy (see [Export](export.md)).

**Useful habits**

In **Image**, pause on a selected photo or video and hold **Hold to compare**
with the mouse, Space or Enter. Before removes creative color adjustments and
the creative LUT, retaining a configured technical D-Log M conversion. Release
to restore the current grade. This changes only the preview, never the project,
Undo history, source media or export. Comparison is unavailable during playback,
while edits are unsaved, or inside a blend between two copies of the same loop.

- **Undo / Redo** work for this session only. Restart opens the last saved Story.
- Cut videos keep an **Original** entry so you can add another scene later.
- Soundtrack can start later on the timeline (drag the music bed). Up to 8 local songs.
- Preview approximates color and some effects; timing should match the MP4.
  The image inspector has **Standard** and **Expert** views. Both use the same
  clip settings, so switching views never changes the picture.
- JPG/PNG photos with a `.cube` color file keep a cached graded still during
  playback and pause, including both photo layers of a crossfade. Preparing a
  new still is asynchronous; the status chip reports pending or failed previews.
- A `.cube` color file can be used during video playback. When a video combines a LUT
  with HSL or color wheels, the app may prepare a short playback proxy and show
  a rendered still until it is ready. Export always applies the saved settings.

**Not a pro editor**

Orga Drone is a memory editor. It does not replace a full video NLE.

## Speed ramps

Select a video on the Story timeline, open **Clip → Speed ramp**, choose a
preset and click **Apply ramp**. The four presets are Slow → Fast → Slow,
Fast → Slow → Fast, Smooth Acceleration and Smooth Deceleration.

The selected clip shows a compact curve on the Effect lane. Drag a point up or
down to change speed, or drag an internal point sideways to move the change.
The inspector's Point, Time in clip and Speed fields provide keyboard access.
Use Add point or Remove point for 2–5 points, at 0.25×–4×. Endpoint speeds can
change; endpoint times stay fixed. Escape cancels an unfinished pointer drag.
A preset needs at least 0.1 seconds of source; a shorter clip is left unchanged.

The curve eases between speeds. The clip length and following clips change with
it. One completed gesture is one Undo step; the saved curve returns when you
reopen the project. Source files stay untouched. Trims and cuts keep points
anchored to the original source: points outside a newly trimmed range still
define its curve. Apply a preset again to fit a new curve to that visible range.

Applying a ramp explicitly replaces existing slow motion. Choosing 0.25× or
0.5× removes the ramp and uses that constant speed instead. Remove ramp returns
the picture to 1×. Source audio is muted throughout a ramped clip, including
parts passing through 1×; its stored placement remains available after removing
the ramp. Project music follows Story time. Repeats and soundtrack loops reuse
the ramp on each pass; a partial final pass stops at the corresponding source
frame. The timeline curve shows that one pass, even when the section repeats.
Existing transitions and animated color remain available. Stories without a
ramp keep the existing 1×, 0.5× and 0.25× timing. There is no separate
timelapse control.

Export uses source frames before its final 30 fps conversion. Slow motion holds
frames and faster motion drops frames as required by the speed; no optical flow
or invented intermediate frames are provided. Preview uses the browser decoder,
so very demanding 4K playback can drop frames. This does not lower export quality.
Existing color-preview approximation limits still apply.
