"""Run the Fast Minesweeper skill against a local Windows game window."""

import argparse
import json
from pathlib import Path
import random
import subprocess
import sys
import time

import audit
import board


def snapshot(game, opened=(), flagged=(), previous=None):
    deadline = time.monotonic() + 0.75
    last = None
    while time.monotonic() < deadline:
        shot = game.capture()
        try:
            cells = board.read_board(shot)
        except ValueError:
            last = None
        else:
            if cells == last and (previous is None or cells != previous):
                if ("exploded" in cells.values()
                        or (all(cells[cell].startswith("opened") for cell in opened)
                            and all(cells[cell] == "flag" for cell in flagged))):
                    return shot, cells
            last = cells
        time.sleep(0.005)
    raise RuntimeError("The game did not reach a stable state after the requested action.")


def click(game, cell, button):
    _, x, y = cell.split("_")
    game.click(board.x0 + int(x)*board.pitch + 7, board.y0 + int(y)*board.pitch + 7, button)


def restart(game):
    game.menu(510)
    deadline = time.monotonic() + 0.75
    while time.monotonic() < deadline:
        shot = game.capture()
        if all(kind == "closed" for kind in board.read_board(shot).values()):
            return
        time.sleep(0.01)
    raise RuntimeError("Could not verify a new covered board.")


def blank_opening(game):
    corners = [(0, 0), (0, board.height-1), (board.width-1, 0), (board.width-1, board.height-1)]
    for _ in range(18):
        restart(game)
        x, y = random.choice(corners)
        cell = f"cell_{x}_{y}"
        started = time.monotonic()
        click(game, cell, "left")
        shot, cells = snapshot(game, opened=[cell])
        if cells[cell] == "opened type0" and all(cells[n] != "closed" for n in board.neighbors[cell]):
            return started, shot, cells
    raise RuntimeError("No blank corner opening after 18 starts.")


def play(game, calculator, strategy, allow_guess):
    started, shot, cells = blank_opening(game)
    known_mines = set()
    clicks = guesses = 0
    for round_number in range(240):
        if "exploded" in cells.values():
            outcome = "loss"
            break
        if "closed" not in cells.values():
            outcome = "win"
            break
        request = board.make_request(cells, known_mines, round_number)
        proposal = board.exchange(calculator, request)
        if proposal.get("round") != round_number:
            raise RuntimeError("The calculator returned a different round.")
        verdict = audit.verdict_for(request, proposal)
        if not verdict["approved"]:
            raise RuntimeError(f"Independent audit rejected the move: {verdict['reason']}")
        guess = proposal["guess"]
        if guess and (not allow_guess or verdict["method"] != "exact"):
            outcome = "needs-guess"
            break
        guesses += bool(guess)
        known_mines.update(proposal["mines"])
        moves = board.plan_moves(cells, proposal, known_mines, strategy)
        if not moves:
            continue
        if board.read_board(game.capture()) != cells:
            raise RuntimeError("The board changed while computing. Resume after the player stops clicking.")
        for cell, button in moves:
            click(game, cell, button)
        clicks += len(moves)
        shot, cells = snapshot(game, opened=[guess] if guess else proposal["safe"],
                               flagged=[cell for cell, button in moves if button == "right"], previous=cells)
    else:
        raise RuntimeError("The round limit was reached.")
    return {"result": outcome, "seconds": round(time.monotonic()-started, 3),
            "clicksAfterOpening": clicks, "guesses": guesses, "rounds": round_number}, shot


def inspect(game, action):
    shot, cells = snapshot(game)
    if "exploded" in cells.values() or "closed" not in cells.values():
        return {"result": "finished"}, shot
    # Treat existing flags as covered when proving a move on a human's board.
    visible = {cell: "closed" if kind == "flag" else kind for cell, kind in cells.items()}
    request = board.make_request(visible, set(), 0)
    covered, remaining, rules, fixed = audit.propagate(*audit.read_board(request))
    try:
        hits, total = audit.weighted_counts(covered, remaining, rules, time.monotonic()+2)
    except TimeoutError:
        hits, total = {}, None
    safe = {pos for pos, mine in fixed.items() if not mine} | {pos for pos, count in hits.items() if count == 0}
    mines = {pos for pos, mine in fixed.items() if mine} | {pos for pos, count in hits.items() if count == total}
    result = {"result": "inspected", "exact": total is not None, "safe": [], "mines": [], "flaggedSafe": []}
    for x, y in sorted(safe | mines):
        cell = f"cell_{x}_{y}"
        point = {"column": x+1, "row": y+1}
        if cells[cell] == "closed":
            result["safe" if (x, y) in safe else "mines"].append(point)
        elif cells[cell] == "flag" and (x, y) in safe:
            result["flaggedSafe"].append(point)
    if total and not result["safe"]:
        ranked = sorted((count, x, y) for (x, y), count in hits.items()
                        if cells[f"cell_{x}_{y}"] == "closed" and 0 < count < total)
        result["lowestRisk"] = [{"column": x+1, "row": y+1, "mineProbability": count/total}
                                for count, x, y in ranked[:5]]
    points = result["mines"] if action == "flag" else result["safe"][:1] if action == "step" else []
    if points:
        targets = [f"cell_{point['column']-1}_{point['row']-1}" for point in points]
        if board.read_board(game.capture()) != cells:
            raise RuntimeError("The board changed while computing.")
        for cell in targets:
            click(game, cell, "right" if action == "flag" else "left")
        shot, after = snapshot(game, flagged=targets if action == "flag" else [],
                               opened=targets if action == "step" else [], previous=cells)
        if "exploded" in after.values():
            raise RuntimeError("The board ended while applying the action.")
        result["actedOn"] = points
    return result, shot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "flag", "step", "play"))
    parser.add_argument("--exe", type=Path, required=True, help="Path of the running XP Minesweeper executable")
    parser.add_argument("--difficulty", choices=audit.LEVELS, help="Select a standard difficulty when starting a new game")
    parser.add_argument("--strategy", choices=("all", "selective", "none"), default="all")
    parser.add_argument("--games", type=int, default=1, help="Number of games to start, or attempt limit with --until-win")
    parser.add_argument("--until-win", action="store_true")
    parser.add_argument("--allow-guess", action="store_true")
    parser.add_argument("--screenshot", type=Path, help="Write the final game client image to a PNG file")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("A local Windows desktop is required.")
    if args.games < 1 or (args.action != "play" and (args.difficulty or args.games != 1 or args.until_win or args.allow_guess)):
        parser.error("Game count, difficulty and guess options apply only to play.")
    from window import GameWindow

    game = GameWindow(args.exe)
    level = args.difficulty or next((name for name, (w, h, _) in audit.LEVELS.items()
                                     if game.size() == (20+16*w, 63+16*h)), None)
    if level is None:
        raise RuntimeError("The current board is not a supported standard difficulty.")
    board.configure(level)
    if args.difficulty:
        game.menu({"beginner": 521, "intermediate": 522, "expert": 523}[level])
        for _ in range(30):
            if game.size() == board.client_size:
                break
            time.sleep(0.015)
        else:
            raise RuntimeError("Could not verify the requested difficulty.")
    if args.action == "play":
        calculator_path = Path(__file__).with_name("calculator.cjs")
        with subprocess.Popen(["node", str(calculator_path)], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, encoding="utf-8") as calculator:
            games = []
            for _ in range(args.games):
                result, shot = play(game, calculator, args.strategy, args.allow_guess)
                games.append(result)
                if result["result"] == "needs-guess" or (args.until_win and result["result"] == "win"):
                    break
        result = {"games": games}
    else:
        result, shot = inspect(game, args.action)
    if args.screenshot:
        shot.save(args.screenshot, format="PNG")
        result["screenshot"] = str(args.screenshot.resolve())
    print(json.dumps({"difficulty": level, **result}))


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        sys.exit(str(error))
