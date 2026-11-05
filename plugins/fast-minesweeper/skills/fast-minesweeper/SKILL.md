---
name: fast-minesweeper
description: Inspect or play a locally running Windows XP Minesweeper window, flag proven mines, open a proven safe tile, or time automated local games. Use for the classic WinMine desktop game.
---

Run `scripts/run.py` with local Windows Python and the exact path of the running XP Minesweeper executable. The target window must be open and restored from the taskbar. Resolve `scripts/` relative to this skill. Node.js is required only for `play`. Python dependencies are in `scripts/requirements.txt`.

Choose the narrowest action requested:

- `inspect --exe <path>` reads the current board without clicking. Report coordinates as column from the left and row from the top, both starting at 1. The result distinguishes proven safe tiles from estimated move risk. When `exact` is true, the reported risks come from enumerating consistent layouts.
- `flag --exe <path>` flags only proven mines. It does not open safe tiles or remove existing flags.
- `step --exe <path>` opens at most one proven safe tile. The player may see more tiles open through the game's normal empty-area expansion.
- `play --exe <path>` starts a new game. Use only when the user wants a fresh game. Optional arguments are `--difficulty beginner|intermediate|expert`, `--strategy all|selective|none`, `--games N`, `--until-win` and `--allow-guess`. Use `--allow-guess` only if the user is comfortable with guesses. Otherwise the run stops when a guess is needed.

Add `--screenshot <absolute-path.png>` when the user wants a screenshot. Report the actual outcome and label the script's elapsed time separately from the whole-second XP display. The plugin plays the local game and uses no account or leaderboard.
