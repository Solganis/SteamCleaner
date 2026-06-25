<h1 align="center">Steam Cleaner</h1>

<p align="center">
  <b>Reclaim disk space from Steam, Epic Games, EA App, GOG Galaxy, and Ubisoft Connect.</b><br>
  Spiritual successor to <a href="https://github.com/Codeusa/SteamCleaner">Codeusa/SteamCleaner</a> (archived, C#/.NET), rewritten from scratch in Python.
</p>

<p align="center">
  <a href="https://github.com/Solganis/SteamCleaner/releases"><img src="https://img.shields.io/github/v/release/Solganis/SteamCleaner" alt="Version"></a>
  <a href="https://github.com/Solganis/SteamCleaner/actions/workflows/ci.yml"><img src="https://github.com/Solganis/SteamCleaner/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/github/Solganis/SteamCleaner"><img src="https://codecov.io/github/Solganis/SteamCleaner/graph/badge.svg?token=HFL1FA47T3" alt="codecov"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.14-blue.svg" alt="Python 3.14"></a>
  <a href="https://github.com/astral-sh/uv"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json" alt="uv"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff"></a>
  <a href="https://github.com/astral-sh/ty"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json" alt="ty"></a>
  <br>
  <img src="https://img.shields.io/badge/i18n-EN%20%7C%20RU%20%7C%20ZH%20%7C%20ES%20%7C%20PT--BR-blue.svg" alt="i18n: EN | RU | ZH | ES | PT-BR">
</p>

<p align="center">
  <img src="assets/demo.gif" alt="SteamCleaner demo" width="720">
</p>

<p align="center">
  Games accumulate gigabytes of junk over time: redistributable installers, shader caches, crash dumps, old logs, unused cross-platform binaries.<br>
  Steam Cleaner finds them and lets you safely remove what you don't need.
</p>

---

<h2 align="center">Quick start</h2>

<p align="center">
  Download the latest build from <a href="https://github.com/Solganis/SteamCleaner/releases">Releases</a>, run it, and press <b>Scan</b>.<br>
  Or run from source:
</p>

<p align="center">
  <code>uv sync</code> &nbsp;then&nbsp; <code>uv run steamcleaner</code>
</p>

<h2 align="center">Features</h2>

<p align="center">
  <b>Cross-platform</b> &middot; Desktop app for Windows, macOS, and Linux with automatic dark/light theme<br>
  <b>Safe by default</b> &middot; Files go to system trash; symlinks and junctions are never followed<br>
  <b>Scans</b> &middot; Steam, Epic Games, EA App (Origin), GOG Galaxy, and Ubisoft Connect, including games installed through Wine, Proton, Bottles, Lutris, and other compatibility layers<br>
  <b>Finds</b> &middot; Redistributable installers, shader/web caches, crash dumps, old logs, bundled installers, and unused cross-platform binaries<br>
  <b>5 languages</b> &middot; English, Russian, Chinese (Simplified), Spanish, Portuguese (Brazil)<br>
  <b>Shortcuts</b> &middot; Keyboard shortcuts for scan, select, clean, and cancel
</p>

<h2 align="center">Safety</h2>

<p align="center">
  <b>Game files</b> &middot; Known game files are never touched (e.g. <code>Steamworks Shared</code>, <code>Heroes of the Storm</code>, <code>Penumbra Overture</code>, <code>Medieval II Total War</code>)<br>
  <b>Symlinks</b> &middot; Symlinks and junction points are never followed or deleted through<br>
  <b>Recoverable</b> &middot; Files go to system trash by default, not permanent deletion<br>
  <b>Transparent</b> &middot; Each detected item shows its exact path, category, and size before removal
</p>

<h2 align="center">What it finds</h2>

<div align="center">
<table>
<tr><th>Category</th><th>Examples</th></tr>
<tr><td>Redistributable installers</td><td>DirectX, Visual C++, .NET, PhysX, OpenAL in <code>_CommonRedist</code>, <code>redist</code>, <code>installer</code></td></tr>
<tr><td>Shader/web cache</td><td>Steam shader cache, Epic/GOG webcache, EA Desktop cache, Ubisoft Connect cache</td></tr>
<tr><td>Crash dumps</td><td><code>.dmp</code>, <code>.mdmp</code> files in game directories and launcher crash folders</td></tr>
<tr><td>Old logs</td><td>Log files over 1 MB in game directories and launcher logs</td></tr>
<tr><td>Cross-platform binaries</td><td>Ren'Py <code>lib/darwin-*</code>, <code>lib/linux-*</code> on Windows (and vice versa)</td></tr>
<tr><td>Bundled installers</td><td>Setup/installer executables inside game folders</td></tr>
</table>
</div>

<h2 align="center">Keyboard shortcuts</h2>

<div align="center">
<table>
<tr><td><kbd>F5</kbd></td><td>Start / stop scan (<kbd>⌘R</kbd> on macOS)</td></tr>
<tr><td><kbd>Ctrl+A</kbd></td><td>Select / deselect all</td></tr>
<tr><td><kbd>Delete</kbd></td><td>Clean selected items (<kbd>⌘⌫</kbd> on macOS)</td></tr>
<tr><td><kbd>Esc</kbd></td><td>Cancel scan, deselect, or clear search</td></tr>
<tr><td><kbd>Ctrl+Q</kbd></td><td>Quit application</td></tr>
</table>
</div>

<p align="center">
  <sub>On macOS, use <kbd>⌘</kbd> in place of <kbd>Ctrl</kbd>.</sub>
</p>

---
