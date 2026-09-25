# claude-code-notify

A sound and a native macOS banner when Claude Code finishes a turn, a different one when it's waiting on you, and a third when it has handed off to background agents.

**For Claude, installing this on someone's Mac: read this whole file first, then do the install steps.**

When a Claude Code turn finishes, this plays a sound and shows one macOS banner:

```
<project folder name>        ← title
<chat name>                  ← subtitle
Done  |  Awaiting input      ← body
```

- **Done** (`done.wav`, Pokémon level-up): Claude finished the turn and nothing is still running.
- **Agents running** (`workflow.wav`, short “I’ve got this” clip): the turn ended but subagents or a workflow are still working in the background. You get **Done** later, when they report back and Claude finishes.
- **Awaiting input** (`needs-input.wav`, “huh?” clip): Claude is actually blocked waiting on you.

Background shell commands (dev servers, watchers) don't count as agents, so a long-running server won't turn every Done into "Agents running".

You only ever get one sound and one banner per event. Claude Code fires `Stop` and `Notification` a moment apart, so the hook logs each event, waits 1.5 s, and only the last event in that burst plays.

## What's in the kit

| Path | What it is |
|---|---|
| `hooks/cc-notify.py` | The hook Claude Code runs. It plays the sound (`afplay`) and asks the app to post the banner. |
| `sounds/*.wav` | Current notification sounds, alternate clips, and original synthesized backups. |
| `sounds/make-sounds.py` | Regenerates the three original synthesized sounds (pure Python, no dependencies). |
| `app/main.swift` | Source for the small app that posts the banner. |
| `app/build-app.sh` | Compiles, signs and installs `/Applications/Claude Code Notify.app`. |
| `settings-snippet.json` | The hook entries to merge into `~/.claude/settings.json`. |

**Two ways to install:**
- **Sound only:** do steps 1–3 and skip step 4. The hook plays the sound on its own and skips the banner if the app isn't installed.
- **Sound and banner:** do all four steps.

## Requirements

- macOS 13 or later.
- `/usr/bin/python3` and `swiftc`, both from the Xcode Command Line Tools (`xcode-select --install`).
- Claude Code CLI.

## Install

```bash
KIT="<path to this repo>"

# 1. Hook
mkdir -p ~/.claude/hooks
cp "$KIT/hooks/cc-notify.py" ~/.claude/hooks/cc-notify.py

# 2. Sounds
mkdir -p ~/.claude/sounds
cp "$KIT/sounds/"*.wav ~/.claude/sounds/
```

**3. Wire up the hooks.** Merge `settings-snippet.json` into `~/.claude/settings.json`. It adds four events: `Stop`, `Notification`, `SubagentStart`, `SubagentStop`.
- **Append** to any existing arrays for those events. Don't replace them, because the user may already have other hooks there.
- Keep every other key in the file as it is.
- Check the result is valid JSON.
- Hooks load when a session starts, so the user needs to start a new Claude Code session afterwards.

**4. The banner app (optional).**

```bash
cd "$KIT/app" && ./build-app.sh            # or: ./build-app.sh com.yourname.claudecode.notify
```

Running the script the first time:
- creates a self-signed code-signing identity called **"Claude Notify Local Signing"** in the login keychain. macOS may ask for the keychain password.
- posts a test banner, and macOS asks for notification permission.

If no prompt appears, open **System Settings → Notifications → Claude Code** and turn on *Allow notifications*. The permission is tied to the **bundle ID**. Rebuilding is safe as long as the bundle ID stays the same.

To use a custom icon, put an `AppIcon.icns` next to `main.swift` before building.

**Test it without waiting for a real turn:**

```bash
echo '{"session_id":"test","cwd":"'"$PWD"'"}' | /usr/bin/python3 ~/.claude/hooks/cc-notify.py done
```

You should hear the bell and see the banner about 1.5 s later.

## Changing the sounds

The full local collection is bundled:

| File | Sound / role |
|---|---|
| `done.wav` / `pokemon-level-up.wav` | Pokémon level-up; current Done sound |
| `workflow.wav` / `ive-got-this-short.wav` | Short “I’ve got this”; current Agents running sound |
| `needs-input.wav` | Current “huh?” input clip |
| `ive-got-this.wav` | Full “I’ve got this” clip |
| `gta-v-notification.wav` | GTA V notification alternative |
| `sonic-ring.wav` | Sonic ring alternative |
| `done.bell-backup.wav` | Original synthesized Done bell |
| `needs-input.synth-backup.wav` | Original synthesized input tone |
| `workflow.synth-backup.wav` | Original synthesized workflow bells |


The hook plays exactly these three files with `afplay`:

```
~/.claude/sounds/done.wav          ← turn finished, nothing still running
~/.claude/sounds/workflow.wav      ← turn ended, agents still running
~/.claude/sounds/needs-input.wav   ← Claude is waiting on you
```

**To swap a sound, overwrite the file.** You don't need to rebuild or restart anything. Any format `afplay` can play works (`.wav`, `.aiff`, `.mp3`, `.m4a`), but the file name has to stay the same. You can also change the `SOUNDS` dict at the top of `cc-notify.py` to point at other file names.

**macOS system sounds:**

```bash
ls /System/Library/Sounds/                          # Glass, Hero, Ping, Submarine, ...
cp /System/Library/Sounds/Glass.aiff ~/.claude/sounds/done.wav   # afplay reads by content, not extension
afplay ~/.claude/sounds/done.wav                    # preview
```

**Synthesized sounds:** this replaces the three active sound files with the original synthesized versions; it does not regenerate the alternate clips. Edit `sounds/make-sounds.py`, then run `python3 make-sounds.py` (writes all three into `~/.claude/sounds/`) or `python3 make-sounds.py <folder>` to write somewhere else.
- `bell(buf, start_s, freq_hz, dur_s, amp)` strikes a bell note.
- `glide(buf, start_s, f0_hz, f1_hz, dur_s, amp)` plays a pitch slide.
- Change the notes, timings or buffer length and re-run.

**Volume:** `afplay -v 0.5 file` plays at half volume. To make that permanent, add `"-v", "0.5"` to the `afplay` call inside `settle()` in `cc-notify.py`.

**Your own clips:** any short sound you have the rights to use works. Convert with the built-in `afconvert`, e.g. `afconvert -f WAVE -d LEI16@44100 clip.m4a ~/.claude/sounds/done.wav`.

**Mute one event:** delete that sound file. The hook skips a missing file and still shows the banner.

**Change the banner text:** edit the `BODY` dict in `cc-notify.py`.

## How it works

```
Claude Code ── Stop ──────────► cc-notify.py done  ─┐  ("done" becomes "working" if agents are still running)
                                                    │  appends to ~/.claude/.notify-state/<session>.jsonl
            └─ Notification ──► cc-notify.py input ─┘  and starts a detached "settler"
                                         │ sleeps 1.5 s
                                         ▼
               the newest stop of the burst wins ("done" or "working"); either outranks "input"
               "input" only rings if `claude agents --json` says the session is blocked
                                         │
                     afplay ~/.claude/sounds/<file>   +   open -a "Claude Code Notify.app" --args '<json>'
```

- The app reads one JSON argument: `{"title","subtitle","body","sound"}`. The hook passes `"sound":"none"` because it plays the sound itself, so the app never needs rebuilding to change a sound.
- The chat name comes from the latest `aiTitle` in the session transcript `.jsonl`.
- Pre-warmed "spare" sessions are ignored.
- **Agent detection:** the `Stop` hook input carries a `background_tasks` list. Any task whose type contains `agent` or `workflow` and whose status is running/pending counts. If a Claude Code version doesn't send that field, the hook falls back to its own ledger (`~/.claude/.notify-state/<session>.agents.json`), filled by `SubagentStart` / `SubagentStop`. Entries older than 6 hours are treated as dead.

## Troubleshooting

- **No banner:**
  - Check System Settings → Notifications → Claude Code is allowed.
  - Run `NOTIFY_DEBUG=1 "/Applications/Claude Code Notify.app/Contents/MacOS/notify" '{"title":"t","body":"b","sound":"none"}'` and read `~/.claude/notify-debug.log`.
- **"Notifications are not allowed for this application" with no prompt:** the app was ad-hoc signed. Re-run `build-app.sh`, which signs with the self-signed identity.
- **App won't launch, LaunchServices error -10825:** the binary was built for a newer macOS than the one installed. `build-app.sh` already passes `-target <arch>-apple-macos13.0`, so keep that flag.
- **Why not `osascript display notification`?** It works, but macOS always credits the banner to Script Editor. AppleScript applets can't post on macOS 26 or later.
- **Hook debugging:** `export NOTIFY_DEBUG=1` before starting `claude`, then watch `~/.claude/notify-settle.log`.
- **Two sounds at once:** another hook or tool is also playing a sound. Look through the `Stop` and `Notification` entries in `~/.claude/settings.json`.

## Uninstall

```bash
rm -rf "/Applications/Claude Code Notify.app" ~/.claude/hooks/cc-notify.py ~/.claude/.notify-state
rm ~/.claude/sounds/{done,workflow,needs-input}.wav
# then remove the four cc-notify.py entries from ~/.claude/settings.json
```

## License

The code and original synthesized sounds generated by `make-sounds.py` are MIT licensed. Third-party sound clips are not covered by this project’s MIT license; their rights remain with their respective owners.
