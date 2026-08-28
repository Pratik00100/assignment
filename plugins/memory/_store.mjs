// Local, append-only journal for the memory plugin. Plain JSONL under
// output/ (already gitignored — see .gitignore's `output/*`), so nothing here
// is ever committed or leaves the machine. No network, no keys.
import { mkdir, readFile, appendFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';

const MEMORY_DIR = path.join(process.cwd(), 'output', 'memory');
const MEMORY_FILE = path.join(MEMORY_DIR, 'history.jsonl');

/** @param {Array<Record<string,string>>} entries */
export async function appendEntries(entries) {
  await mkdir(MEMORY_DIR, { recursive: true });
  const lines = entries.map((e) => JSON.stringify(e)).join('\n') + '\n';
  await appendFile(MEMORY_FILE, lines, 'utf8');
}

/** @returns {Promise<Array<Record<string,string>>>} */
export async function readEntries() {
  if (!existsSync(MEMORY_FILE)) return [];
  const text = await readFile(MEMORY_FILE, 'utf8');
  const out = [];
  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try { out.push(JSON.parse(trimmed)); } catch { /* skip a corrupt line */ }
  }
  return out;
}

export { MEMORY_DIR, MEMORY_FILE };
