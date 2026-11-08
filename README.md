# Mutant Hockey League

A real-time, behind-the-boards 3rd-person arcade hockey game built with `pygame`,
mutant-monster edition. Control a horned, spiked, clawed skater, shoot, check, and
deke your way past an AI team across three periods. No refs. No mercy.

## Running it

```
pip install -r requirements.txt
python hockey_arcade.py
```

## Controls

| Key | Action |
|---|---|
| WASD / Arrow keys | Skate |
| Shift | Sprint |
| Space | Shoot |
| E or F | Deke |
| C | Check |
| Ctrl | Strafe (face the puck while moving freely) |
| Enter | Start match (from title screen) |
| R | Play again (from game-over screen) |
| Esc | Quit |
| Touch / mouse | On-screen joystick (move) + SHOOT/DEKE/CHECK/SPR buttons also work |

## Building a standalone executable

To produce a double-click-able `.exe` with no Python install required (for sharing or uploading to itch.io):

```
pip install -r requirements.txt pyinstaller
pyinstaller --onefile --windowed --name HockeyArcade hockey_arcade.py
```

The executable lands in `dist/HockeyArcade.exe`.

## Playing in a browser / on a phone

The game also runs in any modern browser (including mobile) via [pygbag](https://github.com/pygame-web/pygbag),
which compiles it to WebAssembly. On-screen touch controls (joystick + buttons) kick in automatically for touch input.

```
pip install pygbag
python -m pygbag .
```

This starts a local dev server (default `http://localhost:8000`) you can open on your phone
if it's on the same network as your computer. Pass `--build` instead to produce a static
`build/web/` folder you can host anywhere (GitHub Pages, itch.io, etc.), or `--archive` to
produce a `build/web.zip` ready to upload to itch.io directly.

## Features

- Behind-the-boards chase camera projecting a top-down simulation into 3rd-person
- AI opponents with positioning, checking, shooting, and goalie saves
- Puck motion trail, hit-impact particle bursts, and camera shake on checks
- A slow-motion freeze/zoom celebration beat on goals, with a deferred faceoff reset
- Procedurally synthesized sound effects and music (no external audio assets)
- Title screen and a full restart loop from game over
- On-screen touch controls for mobile/touchscreen play, alongside keyboard and mouse
- Mutant-monster skater design: horned skulls, spiked jerseys, clawed stick hands
