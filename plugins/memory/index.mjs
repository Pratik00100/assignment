// @ts-check
// ── Reference seed ── This bundled plugin is a stable, reviewed example. To
// extend it, publish career-ops-plugin-<id> with "supersedesBundled": true and
// your version takes precedence once installed (see docs/PLUGINS.md). Bundled
// seeds take only security/compat fixes — feature work happens in the successor repo.
//
// Memory plugin — the local-only, no-keys counterpart to a hosted "AI memory"
// integration. `export` archives a snapshot of your tracker to an append-only
// JSONL journal under output/memory/ (gitignored, never leaves your machine);
// `search` recalls archived rows by company/role and resolves each hit's
// original job URL from its report's `**URL:**` header, so a past evaluation
// can be re-surfaced into the pipeline the same way any other search result is.
//
//   node plugins.mjs run memory export
//   node plugins.mjs run memory search "acme"

import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { appendEntries, readEntries } from './_store.mjs';

function cell(row, key) {
  return String(row?.[key] ?? '').trim();
}

/** Extract the reports/<file>.md path from a tracker "report" cell like `[042](reports/042-acme-2026-01-01.md)`. */
function reportPathFromCell(reportCell) {
  const m = String(reportCell || '').match(/\(([^)]+)\)/);
  return m ? m[1].replace(/^\.\.\//, '') : null;
}

/** Resolve a report's `**URL:**` header, guarding against escaping reports/. */
async function resolveReportUrl(reportCell) {
  const rel = reportPathFromCell(reportCell);
  if (!rel) return null;
  const reportsDir = path.resolve(process.cwd(), 'reports');
  const abs = path.resolve(process.cwd(), rel);
  if (abs !== reportsDir && !abs.startsWith(reportsDir + path.sep)) return null;
  try {
    const text = await readFile(abs, 'utf8');
    const m = text.match(/\*\*URL:\*\*\s*(\S+)/);
    return m ? m[1] : null;
  } catch {
    return null;
  }
}

export default {
  /**
   * export: archive each tracker row to the local journal (append-only).
   * Receives a frozen read-only snapshot of the tracker — never a file handle.
   * @param {{ applications: Array<Record<string,string>> }} snapshot
   * @param {any} ctx
   */
  async export(snapshot, ctx) {
    const rows = Array.isArray(snapshot?.applications) ? snapshot.applications : [];
    const entries = rows
      .filter((r) => cell(r, 'company') && cell(r, 'role'))
      .map((r) => ({
        archivedAt: new Date().toISOString(),
        company: cell(r, 'company'),
        role: cell(r, 'role'),
        status: cell(r, 'status'),
        score: cell(r, 'score'),
        report: cell(r, 'report'),
        notes: cell(r, 'notes'),
      }));
    if (entries.length === 0) return { pushed: 0 };
    if (ctx?.dryRun) {
      entries.forEach((e) => ctx.log(`would archive: ${e.company} — ${e.role}`));
      return { pushed: entries.length };
    }
    await appendEntries(entries);
    return { pushed: entries.length };
  },

  /**
   * search: recall archived rows matching a query by company/role/notes, and
   * return the ones whose report still resolves an original job URL as Job[].
   * @param {string} query
   * @param {any} ctx
   */
  async search(query, ctx) {
    const q = String(query || '').trim().toLowerCase();
    if (!q) return [];
    const entries = await readEntries();

    // Keep only the newest archived entry per company+role (re-running export
    // appends, it doesn't overwrite).
    const latest = new Map();
    for (const e of entries) latest.set(`${e.company.toLowerCase()}::${e.role.toLowerCase()}`, e);

    const hits = [...latest.values()].filter(
      (e) => e.company.toLowerCase().includes(q) || e.role.toLowerCase().includes(q) || e.notes.toLowerCase().includes(q)
    );

    const jobs = [];
    for (const e of hits) {
      const url = await resolveReportUrl(e.report);
      if (url) jobs.push({ title: e.role, url, company: e.company, location: '' });
      else ctx?.log?.(`memory: no resolvable URL for ${e.company} — ${e.role}, skipping`);
    }
    return jobs;
  },
};
