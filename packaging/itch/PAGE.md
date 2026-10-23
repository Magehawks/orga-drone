# itch.io page draft

Do not set this project to Public. Keep it Draft or Restricted until
`packaging/itch/AB_TEST_RECORD.md` records a passing A→B test and the Windows
Mark-of-the-Web smoke test has passed. Do not paste the maintainer notes above
the line into the page.

---

Orga Drone is a local-first library for drone photos and videos, with flight
metadata and a simple Studio memory editor. The app runs on your PC. It does
not upload your footage.

**Source code.** The application is free under the MIT license on GitHub:
https://github.com/Magehawks/orga-drone
You can clone the repository and run it with Python. This page does not
change that license.

**This page.** This page is an optional Windows x64 convenience build of that
same application (a folder with `orga-drone.exe` and `_internal`). It is not
a different product, and it does not include your videos or your database.

**Updates.**

- If you install with the **itch.io desktop app** on the Windows channel, that
  app can download later builds for you.
- If you **download the ZIP** from this page, from GitHub Releases, or from
  anywhere else, the itch.io app will not update that copy. Download and
  unzip the newer zip yourself when you want it.
- There is no update button inside Orga Drone.

**Your files.** The library index, Studio projects, and settings stay in
`%APPDATA%\orga-drone`. Your photos and videos stay in the folders you added.
Installing or updating the app does not modify those files. Uninstalling the
app from itch.io does not delete that AppData folder.

The Windows build needs the Edge WebView2 Runtime, which current Windows 10
and 11 installs usually already have.
