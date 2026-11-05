from functools import lru_cache
import json

import audit

x0, y0, pitch = 12, 55, 16
gray, white, red, black = (192,192,192), (255,255,255), (255,0,0), (0,0,0)
glyph = {(0,0,255):1, (0,128,0):2, red:3, (0,0,128):4, (128,0,0):5, (0,128,128):6, black:7, (128,128,128):8}
def configure(level):
    global difficulty, width, height, mine_count, client_size, tile_byte_offsets, neighbors
    difficulty = level
    width, height, mine_count = audit.LEVELS[level]
    client_size = (20 + pitch*width, 63 + pitch*height)
    tile_positions = tuple((f"cell_{x}_{y}", x0+x*pitch, y0+y*pitch)
                           for y in range(height) for x in range(width))
    rgb_stride = client_size[0] * 3
    tile_byte_offsets = tuple((cell, top*rgb_stride + (left+3)*3,
                               tuple(row*rgb_stride + (left+2)*3 for row in range(top+2, top+14)))
                              for cell, left, top in tile_positions)
    neighbors = {
        f"cell_{x}_{y}": tuple(f"cell_{i}_{j}"
                              for i in range(max(0, x-1), min(width, x+2))
                              for j in range(max(0, y-1), min(height, y+2)) if (i,j) != (x,y))
        for y in range(height) for x in range(width)
    }


@lru_cache(maxsize=128)
def classify_tile(raised, sprite):
    colors = set(zip(sprite[::3], sprite[1::3], sprite[2::3]))
    if raised:
        return "flag" if red in colors and black in colors else "closed"
    if (red in colors and black in colors) or (black in colors and white in colors):
        return "exploded"
    colors.discard(gray)
    if not colors:
        return "opened type0"
    if len(colors) == 1 and (ink := next(iter(colors))) in glyph:
        return f"opened type{glyph[ink]}"
    raise ValueError(f"Unknown tile colors: {colors}")


def read_board(shot):
    if shot.size != client_size or shot.mode != "RGB":
        raise RuntimeError(f"Expected a {difficulty} RGB board")
    pixels = shot.tobytes()
    return {cell: classify_tile(pixels[border:border+3] == b"\xff\xff\xff",
                                b"".join(pixels[offset:offset+36] for offset in rows))
            for cell, border, rows in tile_byte_offsets}

def exchange(worker, message):
    worker.stdin.write(json.dumps(message) + "\n")
    worker.stdin.flush()
    line = worker.stdout.readline()
    if not line:
        raise RuntimeError(f"Worker stopped responding: {worker.args[1]}")
    reply = json.loads(line)
    if 'error' in reply:
        raise RuntimeError(reply['error'])
    return reply


def plan_chords(board, safe, planned_flags, known_mines):
    if len(safe) < 2:
        return [], safe
    remaining = set(safe)
    candidates = []
    for cell, kind in board.items():
        if not kind.startswith("opened type") or kind.endswith("0"):
            continue
        adjacent = neighbors[cell]
        if sum(n in known_mines or board[n] == "flag" for n in adjacent) != int(kind[-1]):
            continue
        covered = {n for n in adjacent if board[n] == "closed" and n not in known_mines}
        if len(covered) > 1 and covered <= remaining:
            flags_needed = {n for n in adjacent if board[n] == "closed" and n in known_mines}
            candidates.append((cell, covered, flags_needed))
    chords = []

    def gain(candidate):
        _, covered, flags_needed = candidate
        return len(covered & remaining) - 1 - len(flags_needed - planned_flags)

    while candidates:
        best = max(candidates, key=gain)
        if gain(best) <= 0:
            break
        cell, covered, flags_needed = best
        chords.append(cell)
        planned_flags.update(flags_needed)
        remaining.difference_update(covered)
    return chords, [cell for cell in safe if cell in remaining]

def plan_moves(board, proposal, known_mines, strategy):
    mines = proposal["mines"]
    safe = proposal["safe"]
    guess = proposal.get("guess")
    moves = [(cell, "right") for cell in mines] + [(cell, "left") for cell in safe]
    if guess:
        moves.append((guess, "left"))
    if not moves or len({cell for cell, _ in moves}) != len(moves):
        raise RuntimeError(f"Empty or contradictory proposal: {proposal}")
    for cell, _ in moves:
        if board.get(cell) != "closed":
            raise RuntimeError(f"Proposed action on unavailable cell {cell}")
    flags = set(mines) if strategy == "all" else set()
    eligible_mines = set(mines) if strategy == "all" else known_mines
    chords, single = ([], safe) if strategy == "none" else plan_chords(board, safe, flags, eligible_mines)
    planned = ([(cell, "right") for cell in sorted(flags)] + [(cell, "middle") for cell in chords]
               + [(cell, "left") for cell in single])
    if guess:
        planned.append((guess, "left"))

    return planned


def make_request(board, known_mines, round_number):
    logical = {cell: "flag" if cell in known_mines else kind for cell, kind in board.items()}
    return {"round":round_number, "difficulty":difficulty,
            "remaining":mine_count-sum(kind == "flag" for kind in logical.values()),
            "cells":[{"id":cell,"cls":kind} for cell,kind in logical.items()]}
