# Hockey Arcade

A real-time, behind-the-boards 3rd-person arcade hockey game built with `pygame`.
Control a skater, shoot, check, and deke your way past an AI team across three periods.

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

## Features

- Behind-the-boards chase camera projecting a top-down simulation into 3rd-person
- AI opponents with positioning, checking, shooting, and goalie saves
- Puck motion trail, hit-impact particle bursts, and camera shake on checks
- A slow-motion freeze/zoom celebration beat on goals, with a deferred faceoff reset
- Procedurally synthesized sound effects and music (no external audio assets)
- Title screen and a full restart loop from game over
