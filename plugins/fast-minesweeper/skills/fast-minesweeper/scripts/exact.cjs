"use strict";

function binomial(size, count) {
    if (count < 0 || count > size) return 0n;
    let ways = 1n;
    for (let n = 1; n <= count; n++) {
        ways = ways * BigInt(size - n + 1) / BigInt(n);
    }
    return ways;
}

function tally(group, remaining, deadline) {
    const index = new Map(group.cells.map((cell, i) => [cell, i]));
    const rules = group.rules.map(rule => ({
        cells: rule.cells.map(cell => index.get(cell)),
        mines: rule.mines
    }));
    const distribution = Array(index.size + 1).fill(0n);
    const hits = group.cells.map(() => Array(index.size + 1).fill(0n));
    let nodes = 0;

    function search(values) {
        nodes++;
        if (nodes > 2_000_000 || ((nodes & 1023) === 0 && Date.now() > deadline)) {
            throw Error("Enumeration budget exceeded");
        }
        let changed;
        do {
            changed = false;
            for (const rule of rules) {
                const open = rule.cells.filter(i => values[i] === -1);
                const left = rule.mines - rule.cells.filter(i => values[i] === 1).length;
                if (left < 0 || left > open.length) return;
                if (open.length && (left === 0 || left === open.length)) {
                    for (const i of open) values[i] = left === 0 ? 0 : 1;
                    changed = true;
                }
            }
        } while (changed);

        const mines = values.filter(value => value === 1).length;
        if (mines > remaining) return;
        let branch = -1;
        let best = -1;
        for (let i = 0; i < values.length; i++) {
            if (values[i] !== -1) continue;
            let score = 0;
            for (const rule of rules) {
                if (rule.cells.includes(i)) {
                    const open = rule.cells.filter(cell => values[cell] === -1).length;
                    score += 1 / Math.max(1, open - 1);
                }
            }
            if (score > best) {
                branch = i;
                best = score;
            }
        }
        if (branch === -1) {
            distribution[mines]++;
            for (let i = 0; i < values.length; i++) if (values[i] === 1) hits[i][mines]++;
            return;
        }
        for (const value of [0, 1]) {
            const next = values.slice();
            next[branch] = value;
            search(next);
        }
    }

    search(Array(index.size).fill(-1));
    return { cells: group.cells, distribution, hits };
}

// Weight each disconnected frontier by the other frontiers and the mine total.
module.exports = function solve(covered, rules, remaining) {
    const frontier = new Set(rules.flatMap(rule => rule.ids));
    const interior = covered.filter(cell => !frontier.has(cell));
    const unseen = new Set(frontier);
    const components = [];
    const deadline = Date.now() + 4000;

    while (unseen.size) {
        const cells = [unseen.values().next().value];
        unseen.delete(cells[0]);
        const linked = new Set();
        for (const cell of cells) {
            for (const rule of rules) {
                if (linked.has(rule) || !rule.ids.includes(cell)) continue;
                linked.add(rule);
                for (const neighbor of rule.ids) if (unseen.delete(neighbor)) cells.push(neighbor);
            }
        }
        components.push(tally({
            cells,
            rules: [...linked].map(rule => ({ cells: rule.ids, mines: rule.mines }))
        }, remaining, deadline));
    }

    function combine(left, right) {
        const counts = Array(Math.min(remaining + 1, left.length + right.length - 1)).fill(0n);
        for (let i = 0; i < left.length; i++) {
            for (let j = 0; j < right.length && i + j < counts.length; j++) {
                counts[i + j] += left[i] * right[j];
            }
        }
        return counts;
    }

    const distributions = components.map(component => component.distribution);
    const free = Array.from({ length: interior.length + 1 }, (_, n) => binomial(interior.length, n));
    const total = distributions.reduce(combine, free)[remaining] || 0n;
    if (!total) throw Error("No consistent board");
    const counts = new Map();

    for (const [i, component] of components.entries()) {
        const others = distributions.filter((_, n) => n !== i).reduce(combine, free);
        for (const [j, cell] of component.cells.entries()) {
            counts.set(cell, component.hits[j].reduce(
                (sum, ways, mines) => sum + ways * (others[remaining - mines] || 0n), 0n));
        }
    }
    if (interior.length) {
        const fixedMine = Array.from({ length: interior.length + 1 },
            (_, n) => binomial(interior.length - 1, n - 1));
        const ways = distributions.reduce(combine, fixedMine)[remaining] || 0n;
        for (const cell of interior) counts.set(cell, ways);
    }
    return {
        safe: covered.filter(cell => counts.get(cell) === 0n),
        mines: covered.filter(cell => counts.get(cell) === total),
        probs: covered.map(id => ({ id, p: Number(counts.get(id)) / Number(total) })).sort((a, b) => a.p - b.p)
    };
};
