// Evaluates every save in the three Saves folders and fails if a kind disagrees with the game's own counter.
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { parseSave, SaveError } from '../docs/js/ess.js';
import { evaluate, counters, EDITION_NAMES } from '../docs/js/collect.js';

const GAMES = join(homedir(), 'Documents', 'My Games');
const DIRS = process.argv.length > 2 ? process.argv.slice(2) : ['Skyrim', 'Skyrim Special Edition', 'Skyrim VR'].map(d => join(GAMES, d, 'Saves'));
const data = JSON.parse(readFileSync(new URL('../docs/data/collectibles.json', import.meta.url), 'utf8'));
const KINDS = ['mask', 'stone', 'artifact', 'claw', 'blackbook', 'shout', 'paragon', 'jiub', 'kagrumez', 'jar', 'trophy'];

let saves = 0, skipped = 0;
for (const dir of DIRS.filter(existsSync)) {
  for (const f of readdirSync(dir).filter(f => f.endsWith('.ess'))) {
    const t0 = performance.now();
    const s = parseSave(new Uint8Array(readFileSync(join(dir, f))));
    let r;
    try {
      r = await evaluate(s, data);
    } catch (e) {
      if (!(e instanceof SaveError)) throw e;
      skipped++;
      continue;
    }
    const game = counters(s, data);
    const n = (k, st = 'found') => r.items.filter(i => i.kind === k && r.state.get(i.id) === st).length;
    const line = KINDS.filter(k => r.items.some(i => i.kind === k)).map(k => `${k} ${n(k)}${n(k, 'failed') ? `(-${n(k, 'failed')})` : ''}`);
    const bad = [];
    if (game.stone != null && game.stone !== n('stone')) bad.push(`stones ${n('stone')} vs ${game.stone}`);
    if (game.wordsLearned != null && r.wordsKnown < game.wordsLearned) bad.push(`words ${r.wordsKnown} vs ${game.wordsLearned}`);
    const art = game.artifacts ? ` OW ${game.artifacts.count}/${game.artifacts.max}` : '';
    console.log(`${s.header.edition} ${f.slice(0, 30).padEnd(30)} L${String(s.header.level).padEnd(3)} ${line.join(' ')} words ${r.wordsKnown}${art} ${Math.round(performance.now() - t0)}ms${bad.length ? `  MISMATCH ${bad.join(', ')}` : ''}`);
    if (bad.length) process.exitCode = 1;
    saves++;
  }
}
console.log(`${saves} saves checked, ${skipped} skipped${process.exitCode ? ', with mismatches' : ', all match the game counters'}`);
