from collections import Counter
from math import comb, isfinite
import re
import time


LEVELS = {'beginner': (9, 9, 10), 'intermediate': (16, 16, 40), 'expert': (30, 16, 99)}


def add_rule(rules, cells, mines):
    if not 0 <= mines <= len(cells):
        raise ValueError('inconsistent visible numbers')
    if cells and rules.setdefault(cells, mines) != mines:
        raise ValueError('conflicting visible numbers')


def read_board(request):
    board = {}
    for entry in request['cells']:
        match = re.fullmatch(r'cell_(\d+)_(\d+)', entry['id'])
        if not match:
            raise ValueError('invalid cell id')
        coordinate = tuple(map(int, match.groups()))
        cls = entry['cls'].split()
        if 'opened' in cls:
            number = next((token[4:] for token in cls if token.startswith('type')), '')
            if number not in tuple('012345678'):
                raise ValueError('invalid clue')
            value = int(number)
        else:
            value = 'F' if 'flag' in cls else '?'
        if coordinate in board:
            raise ValueError('duplicate cell')
        board[coordinate] = value
    width, height, mine_count = LEVELS[request.get('difficulty', 'expert')]
    if set(board) != {(x, y) for x in range(width) for y in range(height)}:
        raise ValueError('wrong board dimensions for difficulty')
    covered = {p for p, value in board.items() if value == '?'}
    remaining = mine_count - sum(value == 'F' for value in board.values())
    if remaining != request['remaining'] or not 0 <= remaining <= len(covered):
        raise ValueError('wrong remaining mine count')
    rules = {}
    for (x, y), number in board.items():
        if type(number) is int:
            neighbors = {(i, j) for i in range(x - 1, x + 2) for j in range(y - 1, y + 2)}
            flagged = sum(board.get(cell) == 'F' for cell in neighbors)
            add_rule(rules, frozenset(neighbors & covered), number - flagged)
    return covered, remaining, rules


def propagate(covered, remaining, rules):
    fixed = {}
    while covered:
        if not 0 <= remaining <= len(covered):
            raise ValueError('remaining mine count is impossible')
        assignments = {}
        for cells, mines in [*rules.items(), (covered, remaining)]:
            if mines in (0, len(cells)):
                value = bool(mines)
                for cell in cells:
                    if assignments.setdefault(cell, value) != value:
                        raise ValueError('contradictory forced values')
        if assignments:
            fixed.update(assignments)
            remaining -= sum(assignments.values())
            covered = covered.difference(assignments)
            reduced = {}
            for cells, mines in rules.items():
                add_rule(reduced, cells.difference(assignments), mines - sum(assignments.get(c, False) for c in cells))
            rules = reduced
            continue
        new = dict(rules)
        clauses = list(rules.items())
        for i, (left, left_mines) in enumerate(clauses):
            for right, right_mines in clauses[i + 1:]:
                intersection = left & right
                if not intersection:
                    continue
                only_left = left - right
                only_right = right - left
                lower = max(0, left_mines - len(only_left), right_mines - len(only_right))
                upper = min(len(intersection), left_mines, right_mines)
                if lower > upper:
                    raise ValueError('inconsistent overlapping constraints')
                if lower == upper:
                    add_rule(new, intersection, lower)
                    add_rule(new, only_left, left_mines - lower)
                    add_rule(new, only_right, right_mines - lower)
        if len(new) == len(rules) or len(new) > 256:
            break
        rules = new
    return covered, remaining, rules, fixed


def weighted_counts(covered, remaining, rules, deadline):
    frontier = set().union(*rules)
    unvisited = frontier.copy()
    components = []
    while unvisited:
        component = {unvisited.pop()}
        clauses = set()
        while True:
            connected = {cells for cells in rules if cells & component}
            if connected == clauses:
                break
            clauses = connected
            component.update(set().union(*clauses))
        unvisited.difference_update(component)
        indices = {cell: 1 << i for i, cell in enumerate(sorted(component))}
        checks = [(sum(indices[cell] for cell in cells), rules[cells]) for cells in clauses]
        frequency = Counter(cell for cells in clauses for cell in cells)
        priority = [indices[cell] for cell, _ in frequency.most_common()]
        hit = {cell: Counter() for cell in component}
        count = Counter()

        def enumerate_layouts(known, mines):
            if time.monotonic() > deadline:
                raise TimeoutError('audit counting budget exceeded')
            while True:
                previous = known
                for mask, expected in checks:
                    undecided = mask & ~known
                    left = expected - (mask & mines).bit_count()
                    if left < 0 or left > undecided.bit_count():
                        return
                    if left == 0:
                        known |= undecided
                    elif left == undecided.bit_count():
                        known |= undecided
                        mines |= undecided
                if known == previous:
                    break
            n = mines.bit_count()
            if n > remaining:
                return
            branch = next((bit for bit in priority if not bit & known), 0)
            if branch:
                enumerate_layouts(known | branch, mines)
                enumerate_layouts(known | branch, mines | branch)
                return
            count[n] += 1
            for cell, bit in indices.items():
                if bit & mines:
                    hit[cell][n] += 1

        enumerate_layouts(0, 0)
        if not count:
            raise ValueError('no consistent frontier arrangement')
        components.append((count, hit))

    def merge(left, right):
        output = Counter()
        for a, ways_a in left.items():
            for b, ways_b in right.items():
                if a + b <= remaining:
                    output[a + b] += ways_a * ways_b
        return output

    def combined(skip=None):
        output = Counter({0: 1})
        for i, (count, _) in enumerate(components):
            if i != skip:
                output = merge(output, count)
        return output

    interior = covered - frontier
    free = len(interior)

    def choices(n, k):
        return comb(n, k) if 0 <= k <= n else 0

    frontier_counts = combined()
    total = sum(ways * choices(free, remaining - n) for n, ways in frontier_counts.items())
    if not total:
        raise ValueError('no consistent arrangement for remaining mine count')
    hits = {}
    for i, (count, hit) in enumerate(components):
        rest = combined(skip=i)
        weights = {n: sum(ways * choices(free, remaining - n - m) for m, ways in rest.items()) for n in count}
        for cell, histogram in hit.items():
            hits[cell] = sum(ways * weights[n] for n, ways in histogram.items())
    if free:
        value = sum(ways * choices(free - 1, remaining - n - 1) for n, ways in frontier_counts.items())
        hits.update(dict.fromkeys(interior, value))
    return hits, total


def verify(request, proposal):
    covered, remaining, rules = read_board(request)

    def moves(values):
        if not isinstance(values, list):
            raise ValueError('proposed moves are not a list')
        cells = set()
        for value in values:
            match = re.fullmatch(r'cell_(\d+)_(\d+)', value)
            if not match:
                raise ValueError('malformed proposed move')
            cell = tuple(map(int, match.groups()))
            if cell in cells or cell not in covered:
                raise ValueError('duplicate or unavailable proposed cell')
            cells.add(cell)
        return cells

    safe, mines = moves(proposal['safe']), moves(proposal['mines'])
    guess = proposal.get('guess')
    guessed = moves([guess]) if guess is not None else set()
    if safe & mines or not (safe or mines or guessed):
        raise ValueError('overlapping or empty move batch')
    risk = proposal.get('risk')
    if guessed and (type(risk) not in (int, float) or not isfinite(risk) or not 0 < risk < 1 or safe or mines):
        raise ValueError('invalid guess batch')
    if not guessed and risk is not None:
        raise ValueError('risk is supplied without a guess')
    covered, remaining, rules, fixed = propagate(covered, remaining, rules)
    expected = {cell: False for cell in safe} | {cell: True for cell in mines}
    if risk is None and all(fixed.get(cell) == value for cell, value in expected.items()):
        return dict(approved=True, reason='all moves independently proved by clue constraints', method='constraints')
    if risk is not None and fixed:
        raise ValueError('guess proposed despite forced moves')
    try:
        hits, total = weighted_counts(covered, remaining, rules, time.monotonic() + 1.5)
    except TimeoutError:
        if risk is not None:
            return dict(approved=True, reason='legal guess; audit counting budget exceeded', method='legality-only')
        raise
    if risk is None:
        for cell, value in expected.items():
            valid = fixed[cell] == value if cell in fixed else hits[cell] == total * value
            if not valid:
                raise ValueError('proposed certainty is false')
        return dict(approved=True, reason='all moves independently proved by exact counts', method='exact')
    selected = next(iter(guessed))
    probability = hits[selected] / total
    if probability != min(hits.values()) / total or abs(probability - risk) > 1e-7:
        raise ValueError(f'guess disagrees with exact audit: selected={probability:.10f}, best={min(hits.values()) / total:.10f}')
    return dict(approved=True, reason='minimum-risk guess independently counted', method='exact', probability=probability)


def verdict_for(request, proposal):
    try:
        result = verify(request, proposal)
    except (ValueError, TypeError, TimeoutError, KeyError) as error:
        result = dict(approved=False, reason=str(error))
    return dict(result, round=proposal['round'])
