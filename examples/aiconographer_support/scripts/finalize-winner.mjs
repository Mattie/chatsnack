#!/usr/bin/env node

/**
 * Copy one validated Aiconographer candidate to stable slug-based canonical
 * filenames while preserving the complete candidate run.
 */

import crypto from 'node:crypto';
import { constants } from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const HELP = `
Usage:
  node finalize-winner.mjs --run <run-directory> --candidate <c1..c6> --slug <article-slug>

The command refuses to overwrite canonical files or an existing selection.json.
`;

/** Parse simple `--name value` arguments. */
function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === '--help') {
      parsed.help = true;
      continue;
    }
    if (!token.startsWith('--')) throw new Error(`Unexpected argument: ${token}`);
    const value = argv[index + 1];
    if (value === undefined || value.startsWith('--')) {
      throw new Error(`Missing value for ${token}`);
    }
    parsed[token.slice(2)] = value;
    index += 1;
  }
  return parsed;
}

/** Return a required trimmed argument. */
function required(args, name) {
  const value = args[name]?.trim();
  if (!value) throw new Error(`--${name} is required.`);
  return value;
}

/** Return a lowercase SHA-256 checksum for a file. */
async function fileSha256(filePath) {
  const data = await fs.readFile(filePath);
  return crypto.createHash('sha256').update(data).digest('hex');
}

/** Copy a file only when the destination does not already exist. */
async function copyExclusive(source, destination, copiedDestinations) {
  await fs.copyFile(source, destination, constants.COPYFILE_EXCL);
  copiedDestinations.push(destination);
  return {
    path: destination,
    bytes: (await fs.stat(destination)).size,
    sha256: await fileSha256(destination),
  };
}

/** Verify every copy can start before creating any canonical file. */
async function preflightCopy(source, destination) {
  const sourceStat = await fs.stat(source);
  if (!sourceStat.isFile()) throw new Error(`Canonical source is not a file: ${source}`);
  try {
    await fs.access(destination);
    throw new Error(`Canonical destination already exists: ${destination}`);
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
}

/** Finalize the selected candidate and write auditable selection metadata. */
async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    process.stdout.write(HELP);
    return;
  }

  const runRoot = path.resolve(required(args, 'run'));
  const candidate = required(args, 'candidate').toLowerCase();
  const slug = required(args, 'slug').toLowerCase();
  if (!/^c[1-6]$/.test(candidate)) {
    throw new Error('--candidate must be c1, c2, c3, c4, c5, or c6.');
  }
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) {
    throw new Error('--slug must contain lowercase letters, digits, and single hyphens.');
  }

  const validationPath = path.join(runRoot, 'validation.json');
  const validation = JSON.parse(await fs.readFile(validationPath, 'utf8'));
  if (!validation.candidates?.[candidate]) {
    throw new Error(`${candidate} is missing from validation.json.`);
  }

  const selectionPath = path.join(runRoot, 'selection.json');
  try {
    await fs.access(selectionPath);
    throw new Error(`Selection already exists: ${selectionPath}`);
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }

  const svgSource = path.join(runRoot, 'svg', `${candidate}.svg`);
  const svgDestination = path.join(runRoot, `${slug}.svg`);
  const previewSizes = validation.previewSizes ?? Object.keys(validation.candidates[candidate].previews);
  const previewCopies = previewSizes.map((size) => ({
    size: String(size),
    source: path.join(runRoot, 'previews', String(size), `${candidate}.png`),
    destination: path.join(runRoot, `${slug}-${size}.png`),
  }));
  const copies = [
    { source: svgSource, destination: svgDestination },
    ...previewCopies,
  ];
  await Promise.all(copies.map(({ source, destination }) => preflightCopy(source, destination)));

  const copiedDestinations = [];
  let canonical;
  try {
    canonical = {
      svg: await copyExclusive(svgSource, svgDestination, copiedDestinations),
      previews: {},
    };
    for (const { size, source, destination } of previewCopies) {
      canonical.previews[size] = await copyExclusive(
        source,
        destination,
        copiedDestinations,
      );
    }

    const selection = {
      candidate,
      slug,
      canonical,
      candidateValidation: validation.candidates[candidate],
    };
    await fs.writeFile(selectionPath, `${JSON.stringify(selection, null, 2)}\n`, {
      encoding: 'utf8',
      flag: 'wx',
    });
  } catch (error) {
    await Promise.allSettled(copiedDestinations.map((destination) => fs.unlink(destination)));
    throw error;
  }

  process.stdout.write(
    `${JSON.stringify({ ok: true, candidate, slug, selectionPath, canonical }, null, 2)}\n`,
  );
}

main().catch((error) => {
  process.stderr.write(`aiconographer: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
