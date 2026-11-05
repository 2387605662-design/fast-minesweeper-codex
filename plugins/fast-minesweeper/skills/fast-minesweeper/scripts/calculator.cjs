const solve = require('./exact.cjs');
const readline = require('node:readline');

function neighborhood(id) {
    const [, column, row] = id.split('_');
    const x = Number(column), y = Number(row), neighbors = [];
    for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -1; dx <= 1; dx++) {
            if (dx || dy) neighbors.push(`cell_${x + dx}_${y + dy}`);
        }
    }
    return neighbors;
}

function deduce(rules, covered, remaining) {
    const safe = new Set(), mines = new Set();
    const allRules = [...rules, { ids: covered, mines: remaining }];
    let changed = true;
    while (changed) {
        const previousCount = safe.size + mines.size;
        const unresolved = allRules.map(rule => ({
            ids: rule.ids.filter(id => !safe.has(id) && !mines.has(id)),
            mines: rule.mines - rule.ids.filter(id => mines.has(id)).length,
        }));
        function add(ids, count) {
            if (count < 0 || count > ids.length) throw Error('Conflicting visible constraints');
            if (count === 0) ids.forEach(id => safe.add(id));
            else if (count === ids.length) ids.forEach(id => mines.add(id));
        }
        for (const rule of unresolved) add(rule.ids, rule.mines);
        for (const left of unresolved) {
            if (left.ids.length === 0) continue;
            for (const right of unresolved) {
                if (right.ids.length <= left.ids.length || !left.ids.every(id => right.ids.includes(id))) continue;
                const differenceSize = right.ids.length - left.ids.length;
                const differenceCount = right.mines - left.mines;
                if (differenceCount === 0 || differenceCount === differenceSize) {
                    add(right.ids.filter(id => !left.ids.includes(id)), differenceCount);
                }
            }
        }
        if ([...safe].some(id => mines.has(id))) throw Error('Overlapping safe and mine conclusions');
        changed = previousCount !== safe.size + mines.size;
    }
    return { safe: [...safe], mines: [...mines] };
}

function approximate(rules, covered, remaining) {
    const baseline = remaining / covered.length;
    return covered.map(id => {
        const local = rules.filter(rule => rule.ids.includes(id));
        const estimates = local.map(rule => rule.mines / rule.ids.length);
        const p = estimates.length ? estimates.reduce((a, b) => a + b, 0) / estimates.length : baseline;
        return { id, p: Math.max(0.01, Math.min(0.99, p)) };
    }).sort((a, b) => a.p - b.p);
}

function pickGuess(probabilities, cells) {
    const minimum = probabilities[0].p;
    const opened = [...cells.values()].filter(cls => cls.includes('opened')).length;
    if (opened < 5 || Math.abs(minimum - 0.5) <= 1e-12) {
        const tied = probabilities.filter(cell => cell.p - minimum <= 1e-12);
        return tied[Math.floor(Math.random() * tied.length)];
    }
    const p = new Map(probabilities.map(cell => [cell.id, cell.p]));
    let best = [], bestScore = -Infinity;
    for (const cell of probabilities) {
        if (cell.p - minimum > 1e-12) break;
        const neighbors = neighborhood(cell.id).filter(id => cells.has(id));
        const unknown = neighbors.filter(id => p.has(id));
        const chanceOfZero = neighbors.some(id => cells.get(id).includes('flag')) ? 0
            : unknown.reduce((product, id) => product * (1 - p.get(id)), 1);
        const score = chanceOfZero * 10 + unknown.length * 0.05;
        if (score > bestScore + 1e-12) {
            best = [cell];
            bestScore = score;
        } else if (Math.abs(score - bestScore) <= 1e-12) {
            best.push(cell);
        }
    }
    return best[Math.floor(Math.random() * best.length)];
}

function proposal(request) {
    const { round, remaining } = request;
    const cells = new Map(request.cells.map(cell => [cell.id, cell.cls]));
    const covered = [...cells].filter(([, cls]) => !cls.includes('opened') && !cls.includes('flag')).map(([id]) => id);
    const coveredSet = new Set(covered);
    const rules = [];
    for (const [id, cls] of cells) {
        if (!cls.includes('opened')) continue;
        const number = Number(cls.match(/type(\d+)/)[1]);
        const neighbors = neighborhood(id);
        const ids = neighbors.filter(neighbor => coveredSet.has(neighbor));
        const mines = number - neighbors.filter(neighbor => cells.get(neighbor)?.includes('flag')).length;
        if (mines < 0 || mines > ids.length) throw Error(`Invalid clue ${id}`);
        if (ids.length) rules.push({ ids, mines });
    }
    const base = { round, safe: [], mines: [], guess: null, risk: null };
    const deterministic = deduce(rules, covered, remaining);
    if (deterministic.safe.length || deterministic.mines.length || !covered.length) {
        return { ...base, ...deterministic, method: 'constraints' };
    }
    let method = 'exact', probabilities;
    try {
        const exact = solve(covered, rules, remaining);
        if (exact.safe.length || exact.mines.length) {
            return { ...base, safe: exact.safe, mines: exact.mines, method };
        }
        probabilities = exact.probs;
    } catch (error) {
        console.error(`Exact solver unavailable for round ${round}: ${error.message.split('\n')[0]}`);
        method = 'estimated';
        probabilities = approximate(rules, covered, remaining);
    }
    const guess = pickGuess(probabilities, cells);
    return { ...base, guess: guess.id, risk: guess.p, method };
}


const input = readline.createInterface({ input: process.stdin });
input.on('line', line => {
    try {
        console.log(JSON.stringify(proposal(JSON.parse(line))));
    } catch (error) {
        console.log(JSON.stringify({ error: error.message }));
    }
});
