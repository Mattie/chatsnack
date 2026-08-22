#!/usr/bin/env node

/**
 * Compile a high-resolution 3-by-2 icon sheet into normalized tiles, transparent
 * two-fill SVGs, UI-size previews, contact sheets, and an anonymous review pack.
 */

import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import process from 'node:process';

const INKS = [
  { hex: '#2C2C2B', rgb: [44, 44, 43] },
  { hex: '#F45138', rgb: [244, 81, 56] },
];
const WHITE = { hex: '#FFFFFF', rgb: [255, 255, 255] };
const TRACE_PALETTE = [WHITE, ...INKS];
const REVIEW_ALIASES = ['ash', 'birch', 'cedar', 'dune', 'ember', 'flint'];

const VECTOR_SETTINGS = {
  preset: 'poster',
  clustering: 'color-cluster',
  hierarchical: 'cutout',
  mode: 'spline',
  // Suppress isolated palette flecks without removing intentional small marks.
  filterSpeckle: 4,
  colorPrecision: 8,
  layerDifference: 0,
  cornerThreshold: 60,
  lengthThreshold: 4,
  maxIterations: 20,
  spliceThreshold: 45,
  simplify: 1.25,
  pathPrecision: 3,
  palette: ['#ffffff', '#2c2c2b', '#f45138'],
  maxColors: 3,
  optimize: 1,
};

const HELP = `
Usage:
  node process-sheet.mjs --input <sheet> --output <empty-dir> --deps-root <dir> [options]

Required:
  --input         Candidate sheet image.
  --output        New or empty output directory.
  --deps-root     Directory containing node_modules from scripts/package-lock.json.

Options:
  --article       Plain-text article file copied into the anonymous review pack.
  --columns       Sheet columns. Default: 3.
  --rows          Sheet rows. Default: 2.
  --sizes         Comma-separated preview widths. Default: 192,48.
  --review-seed   Stable anonymous-review shuffle seed. Default: source checksum.
  --help          Show this help.
`;

/** Parse simple `--name value` command-line arguments. */
function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === '--help') {
      parsed.help = true;
      continue;
    }
    if (!token.startsWith('--')) {
      throw new Error(`Unexpected argument: ${token}`);
    }
    const value = argv[index + 1];
    if (value === undefined || value.startsWith('--')) {
      throw new Error(`Missing value for ${token}`);
    }
    parsed[token.slice(2)] = value;
    index += 1;
  }
  return parsed;
}

/** Resolve a required path argument and fail with a concise message when absent. */
function requiredPath(args, name) {
  const value = args[name];
  if (!value) throw new Error(`--${name} is required.`);
  return path.resolve(value);
}

/** Parse and validate a positive integer argument. */
function positiveInteger(value, fallback, label) {
  const parsed = value === undefined ? fallback : Number.parseInt(value, 10);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${label} must be a positive integer.`);
  }
  return parsed;
}

/** Refuse to mix a new run with any pre-existing files. */
async function prepareEmptyDirectory(directory) {
  try {
    const entries = await fs.readdir(directory);
    if (entries.length > 0) {
      throw new Error(`Output directory is not empty: ${directory}`);
    }
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
  await fs.mkdir(directory, { recursive: true });
}

/** Return a lowercase SHA-256 checksum for a buffer. */
function sha256(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

/** Load pinned image dependencies from a caller-owned temporary directory. */
function loadDependencies(depsRoot) {
  const packagePath = path.join(depsRoot, 'package.json');
  const requireFromDeps = createRequire(packagePath);
  return {
    sharp: requireFromDeps('sharp'),
    vtracer: requireFromDeps('@visioncortex/vtracer'),
    Resvg: requireFromDeps('@resvg/resvg-js').Resvg,
  };
}

/** Read an installed package version without relying on its export map. */
async function packageVersion(depsRoot, packageParts) {
  const packagePath = path.join(depsRoot, 'node_modules', ...packageParts, 'package.json');
  return JSON.parse(await fs.readFile(packagePath, 'utf8')).version;
}

/** Map every RGB pixel in a tile to the nearest approved palette entry. */
async function normalizeTile(sharp, sourcePath, region) {
  const { data, info } = await sharp(sourcePath)
    .extract(region)
    .flatten({ background: WHITE.hex })
    .removeAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });

  const output = Buffer.alloc(data.length);
  const counts = Object.fromEntries(TRACE_PALETTE.map(({ hex }) => [hex, 0]));

  for (let offset = 0; offset < data.length; offset += 3) {
    const red = data[offset];
    const green = data[offset + 1];
    const blue = data[offset + 2];
    let bestIndex = 0;
    let bestDistance = Number.POSITIVE_INFINITY;

    for (let index = 0; index < TRACE_PALETTE.length; index += 1) {
      const [targetRed, targetGreen, targetBlue] = TRACE_PALETTE[index].rgb;
      const distance =
        (red - targetRed) ** 2 +
        (green - targetGreen) ** 2 +
        (blue - targetBlue) ** 2;
      if (distance < bestDistance) {
        bestDistance = distance;
        bestIndex = index;
      }
    }

    const selected = TRACE_PALETTE[bestIndex];
    output[offset] = selected.rgb[0];
    output[offset + 1] = selected.rgb[1];
    output[offset + 2] = selected.rgb[2];
    counts[selected.hex] += 1;
  }

  const png = await sharp(output, {
    raw: { width: info.width, height: info.height, channels: 3 },
  })
    .png()
    .toBuffer();

  return { png, counts, width: info.width, height: info.height };
}

/** Remove white tracing paths and make the SVG explicitly scalable. */
function cleanSvg(sourceSvg, width, height) {
  let svg = sourceSvg.replace(
    /<path\b[^>]*(?:\/>|>[\s\S]*?<\/path>)/gi,
    (element) => {
      const whiteHex = /\bfill\s*=\s*["']#(?:fff|ffffff)["']/i.test(element);
      const whiteRgb = /\bfill\s*=\s*["']rgb\(\s*255\s*,\s*255\s*,\s*255\s*\)["']/i.test(element);
      return whiteHex || whiteRgb ? '' : element;
    },
  );

  svg = svg
    .replace(/fill=["']#2c2c2b["']/gi, 'fill="#2C2C2B"')
    .replace(/fill=["']#f45138["']/gi, 'fill="#F45138"');

  svg = svg.replace(/<svg\b[^>]*>/i, (openingTag) => {
    if (/\bviewBox\s*=/.test(openingTag)) return openingTag;
    return openingTag.replace(/>$/, ` viewBox="0 0 ${width} ${height}">`);
  });
  return svg;
}

/** Enforce the canonical vector-only, two-fill SVG contract. */
function validateSvg(svg, width, height) {
  const fills = [...svg.matchAll(/\bfill=["'](#[0-9A-Fa-f]{6})["']/g)]
    .map((match) => match[1].toUpperCase());
  const uniqueFills = [...new Set(fills)].sort();
  const expectedFills = INKS.map(({ hex }) => hex).sort();
  const forbidden = [
    ['embedded raster image', /<image\b/i],
    ['background rectangle', /<rect\b/i],
    ['stroke', /\bstroke\s*=/i],
    ['filter', /<(?:filter)\b/i],
    ['gradient', /<(?:linearGradient|radialGradient)\b/i],
    ['mask', /<mask\b/i],
    ['text', /<text\b/i],
    ['white fill', /\bfill\s*=\s*["']#(?:fff|ffffff)["']/i],
  ];

  if (JSON.stringify(uniqueFills) !== JSON.stringify(expectedFills)) {
    throw new Error(`SVG fills ${uniqueFills.join(',')} do not match the two approved inks.`);
  }
  if (!new RegExp(`viewBox=["']0 0 ${width} ${height}["']`).test(svg)) {
    throw new Error('SVG is missing the expected full-canvas viewBox.');
  }
  for (const [label, pattern] of forbidden) {
    if (pattern.test(svg)) throw new Error(`SVG contains forbidden ${label}.`);
  }
  const pathCount = (svg.match(/<path\b/gi) ?? []).length;
  if (pathCount === 0) throw new Error('SVG contains no paths.');
  return { fills: uniqueFills, pathCount };
}

/** Render one SVG at an exact square size with transparent antialiased edges. */
function renderSvg(Resvg, svg, size) {
  const renderer = new Resvg(svg, {
    fitTo: { mode: 'width', value: size },
    background: 'rgba(0, 0, 0, 0)',
  });
  return renderer.render().asPng();
}

/** Accept exact inks and the edge blends produced where one approved ink overlaps another. */
function isApprovedOpaqueColor(red, green, blue) {
  const pixel = [red, green, blue];
  const start = INKS[0].rgb;
  const end = INKS[1].rgb;
  let axis = 0;
  for (let index = 1; index < 3; index += 1) {
    if (Math.abs(end[index] - start[index]) > Math.abs(end[axis] - start[axis])) axis = index;
  }
  const span = end[axis] - start[axis];
  const blend = span === 0 ? 0 : (pixel[axis] - start[axis]) / span;
  if (blend < 0 || blend > 1) return false;
  return pixel.every((channel, index) => {
    const expected = start[index] + blend * (end[index] - start[index]);
    return Math.abs(channel - expected) <= 1;
  });
}

/** Validate dimensions, alpha coverage, and opaque RGB provenance. */
async function validatePreview(sharp, png, size) {
  const { data, info } = await sharp(png)
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  if (info.width !== size || info.height !== size) {
    throw new Error(`Preview is ${info.width}x${info.height}; expected ${size}x${size}.`);
  }

  const opaqueColors = new Set();
  let transparent = 0;
  let partial = 0;
  let opaque = 0;
  let invalidOpaque = 0;

  for (let offset = 0; offset < data.length; offset += 4) {
    const alpha = data[offset + 3];
    if (alpha === 0) {
      transparent += 1;
      continue;
    }
    if (alpha < 255) {
      partial += 1;
      continue;
    }
    opaque += 1;
    const color = [data[offset], data[offset + 1], data[offset + 2]]
      .map((channel) => channel.toString(16).padStart(2, '0'))
      .join('')
      .toUpperCase();
    opaqueColors.add(color);
    if (!isApprovedOpaqueColor(data[offset], data[offset + 1], data[offset + 2])) {
      invalidOpaque += 1;
    }
  }

  if (transparent === 0 || partial === 0 || opaque === 0) {
    throw new Error('Preview must contain transparent, partially transparent, and opaque pixels.');
  }
  if (invalidOpaque > 0) {
    throw new Error(`Preview contains ${invalidOpaque} fully opaque pixels outside the approved inks.`);
  }
  return {
    dimensions: [info.width, info.height],
    transparent,
    partial,
    opaque,
    opaqueColors: [...opaqueColors].sort(),
    sha256: sha256(png),
  };
}

/** Build a contact sheet without changing the individual SVG-derived previews. */
async function createContactSheet(sharp, previewPaths, size, columns, background, destination) {
  const gap = Math.max(4, Math.round(size / 8));
  const rows = Math.ceil(previewPaths.length / columns);
  const width = columns * size + (columns - 1) * gap;
  const height = rows * size + (rows - 1) * gap;
  const composite = previewPaths.map((input, index) => ({
    input,
    left: (index % columns) * (size + gap),
    top: Math.floor(index / columns) * (size + gap),
  }));
  await sharp({
    create: { width, height, channels: 4, background },
  })
    .composite(composite)
    .png()
    .toFile(destination);
}

/** Return a stable shuffled copy using a seed-derived xorshift generator. */
function seededShuffle(values, seed) {
  const output = [...values];
  let state = crypto.createHash('sha256').update(seed).digest().readUInt32LE(0) || 1;
  const random = () => {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    return (state >>> 0) / 0x1_0000_0000;
  };
  for (let index = output.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(random() * (index + 1));
    [output[index], output[swapIndex]] = [output[swapIndex], output[index]];
  }
  return output;
}

/** Write stable, readable JSON evidence. */
async function writeJson(destination, value) {
  await fs.writeFile(destination, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

/** Execute the complete sheet compilation pipeline. */
async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    process.stdout.write(HELP);
    return;
  }

  const inputPath = requiredPath(args, 'input');
  const outputRoot = requiredPath(args, 'output');
  const depsRoot = requiredPath(args, 'deps-root');
  const articlePath = args.article ? path.resolve(args.article) : null;
  const columns = positiveInteger(args.columns, 3, '--columns');
  const rows = positiveInteger(args.rows, 2, '--rows');
  const sizes = (args.sizes ?? '192,48').split(',').map((value) =>
    positiveInteger(value.trim(), null, '--sizes'),
  );

  if (columns * rows !== REVIEW_ALIASES.length) {
    throw new Error(`This skill requires exactly ${REVIEW_ALIASES.length} candidates.`);
  }
  if (new Set(sizes).size !== sizes.length) {
    throw new Error('--sizes contains duplicates.');
  }

  await fs.access(inputPath);
  if (articlePath) await fs.access(articlePath);
  await prepareEmptyDirectory(outputRoot);

  const { sharp, vtracer, Resvg } = loadDependencies(depsRoot);
  const sourceSheetPath = path.join(outputRoot, 'source-sheet.png');
  await sharp(inputPath).png().toFile(sourceSheetPath);
  const sourceBuffer = await fs.readFile(sourceSheetPath);
  const sourceHash = sha256(sourceBuffer);
  const metadata = await sharp(sourceSheetPath).metadata();
  const width = metadata.width;
  const height = metadata.height;
  if (!width || !height || width % columns !== 0 || height % rows !== 0) {
    throw new Error(`Sheet dimensions ${width}x${height} do not divide into ${columns}x${rows}.`);
  }
  const cellWidth = width / columns;
  const cellHeight = height / rows;
  if (cellWidth !== cellHeight) {
    throw new Error(`Sheet cells are ${cellWidth}x${cellHeight}; square cells are required.`);
  }

  const tileDir = path.join(outputRoot, 'tiles');
  const svgDir = path.join(outputRoot, 'svg');
  const previewRoot = path.join(outputRoot, 'previews');
  const contactDir = path.join(outputRoot, 'contact-sheets');
  const anonymousRoot = path.join(outputRoot, 'anonymous-review');
  await Promise.all([
    fs.mkdir(tileDir, { recursive: true }),
    fs.mkdir(svgDir, { recursive: true }),
    fs.mkdir(contactDir, { recursive: true }),
    fs.mkdir(anonymousRoot, { recursive: true }),
    ...sizes.map((size) => fs.mkdir(path.join(previewRoot, String(size)), { recursive: true })),
    ...sizes.map((size) => fs.mkdir(path.join(anonymousRoot, String(size)), { recursive: true })),
  ]);

  const candidateIds = Array.from({ length: columns * rows }, (_, index) => `c${index + 1}`);
  const candidates = {};

  for (let index = 0; index < candidateIds.length; index += 1) {
    const candidateId = candidateIds[index];
    const region = {
      left: (index % columns) * cellWidth,
      top: Math.floor(index / columns) * cellHeight,
      width: cellWidth,
      height: cellHeight,
    };
    const normalized = await normalizeTile(sharp, sourceSheetPath, region);
    const tilePath = path.join(tileDir, `${candidateId}.png`);
    await fs.writeFile(tilePath, normalized.png);

    let svg = vtracer.convertBuffer(normalized.png, VECTOR_SETTINGS);
    svg = cleanSvg(svg, cellWidth, cellHeight);
    const svgValidation = validateSvg(svg, cellWidth, cellHeight);
    const svgPath = path.join(svgDir, `${candidateId}.svg`);
    await fs.writeFile(svgPath, svg, 'utf8');

    const previewValidation = {};
    for (const size of sizes) {
      const png = renderSvg(Resvg, svg, size);
      const previewPath = path.join(previewRoot, String(size), `${candidateId}.png`);
      await fs.writeFile(previewPath, png);
      previewValidation[String(size)] = await validatePreview(sharp, png, size);
    }

    candidates[candidateId] = {
      sourceCell: region,
      normalizedCounts: normalized.counts,
      tileSha256: sha256(normalized.png),
      svg: {
        sha256: sha256(Buffer.from(svg, 'utf8')),
        bytes: Buffer.byteLength(svg, 'utf8'),
        pathCount: svgValidation.pathCount,
        fills: svgValidation.fills,
      },
      previews: previewValidation,
    };
  }

  for (const size of sizes) {
    const paths = candidateIds.map((candidateId) =>
      path.join(previewRoot, String(size), `${candidateId}.png`),
    );
    await createContactSheet(
      sharp,
      paths,
      size,
      columns,
      { r: 255, g: 255, b: 255, alpha: 1 },
      path.join(contactDir, `white-${size}.png`),
    );
    await createContactSheet(
      sharp,
      paths,
      size,
      columns,
      { r: 32, g: 32, b: 31, alpha: 1 },
      path.join(contactDir, `dark-neutral-${size}.png`),
    );
  }

  const reviewSeed = args['review-seed'] ?? sourceHash;
  const shuffledCandidates = seededShuffle(candidateIds, reviewSeed);
  const aliasMap = {};
  for (let index = 0; index < REVIEW_ALIASES.length; index += 1) {
    const alias = REVIEW_ALIASES[index];
    const candidateId = shuffledCandidates[index];
    aliasMap[alias] = candidateId;
    for (const size of sizes) {
      await fs.copyFile(
        path.join(previewRoot, String(size), `${candidateId}.png`),
        path.join(anonymousRoot, String(size), `${alias}.png`),
      );
    }
  }
  if (articlePath) {
    await fs.copyFile(articlePath, path.join(anonymousRoot, 'article.txt'));
  }
  await writeJson(path.join(outputRoot, 'review-map.json'), { reviewSeed, aliasMap });

  const validation = {
    sourceSheet: {
      path: sourceSheetPath,
      dimensions: [width, height],
      bytes: sourceBuffer.length,
      sha256: sourceHash,
      grid: { columns, rows, cellWidth, cellHeight },
    },
    toolVersions: {
      vtracer: await packageVersion(depsRoot, ['@visioncortex', 'vtracer']),
      resvg: await packageVersion(depsRoot, ['@resvg', 'resvg-js']),
      sharp: await packageVersion(depsRoot, ['sharp']),
    },
    vectorSettings: VECTOR_SETTINGS,
    previewSizes: sizes,
    candidates,
  };
  const validationPath = path.join(outputRoot, 'validation.json');
  await writeJson(validationPath, validation);

  process.stdout.write(
    `${JSON.stringify({
      ok: true,
      outputRoot,
      validationPath,
      candidateCount: candidateIds.length,
      previewSizes: sizes,
      reviewPack: anonymousRoot,
    }, null, 2)}\n`,
  );
}

main().catch((error) => {
  process.stderr.write(`aiconographer: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
