import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { inflateSync } from 'node:zlib';
import test from 'node:test';
import { PDFDocument, PDFName } from 'pdf-lib';

const run = promisify(execFile);
const script = fileURLToPath(new URL('../scripts/export-slides-pdf.mjs', import.meta.url));

async function workspace(t) {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'mdslides-pdf-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}

test('HTML export creates one HD image per slide and hides private controls', async t => {
  const directory = await workspace(t);
  const input = path.join(directory, 'deck with spaces.html');
  await writeFile(input, `<!doctype html><style>
    * { margin: 0; } .slide { height: 100vh; background: #00ff00; }
    .reveal { opacity: 0; }
    .reveal { height: 100%; background: blue; }
    blockquote:not(:empty) { height: 100%; background: yellow; }
    .notes-panel { position: fixed; inset: 0; background: red; z-index: 99; }
  </style><div class="notes-panel">PRIVATE</div>
  <section class="slide"><p class="reveal">First</p></section>
  <section class="slide"><blockquote data-typewriter-text="Complete quote"></blockquote></section>`);
  const { stdout } = await run(process.execPath, [script, input], { cwd: directory });
  assert.match(stdout, /2 slides, 3840 x 2160/);
  const pdf = await PDFDocument.load(await readFile(path.join(directory, 'deck with spaces.pdf')));
  assert.equal(pdf.getPageCount(), 2);
  for (const [index, page] of pdf.getPages().entries()) {
    assert.deepEqual(page.getSize(), { width: 960, height: 540 });
    const objects = page.node.Resources().lookup(PDFName.of('XObject'));
    const image = pdf.context.lookup(objects.values()[0]);
    assert.equal(image.dict.lookup(PDFName.of('Width')).asNumber(), 3840);
    assert.equal(image.dict.lookup(PDFName.of('Height')).asNumber(), 2160);
    assert.deepEqual([...inflateSync(image.contents).subarray(0, 3)],
      index === 0 ? [0, 0, 255] : [255, 255, 0]);
  }
});

test('custom output directories are created and invalid inputs fail explicitly', async t => {
  const directory = await workspace(t);
  const input = path.join(directory, 'deck.html');
  await writeFile(input, '<style>*{margin:0}.slide{height:100vh}</style><section class="slide">Slide</section>');
  const output = path.join(directory, 'nested', 'custom.pdf');
  await run(process.execPath, [script, input, '-o', output]);
  assert.equal((await PDFDocument.load(await readFile(output))).getPageCount(), 1);
  await assert.rejects(run(process.execPath, [script, input, '-o', input]), /Output must be a .pdf/);
  await assert.rejects(run(process.execPath, [script, '--unknown']), /Unknown option/);
  await assert.rejects(run(process.execPath, [script]), /exactly one/);
  await writeFile(input, '<html><body>No slides</body></html>');
  await assert.rejects(run(process.execPath, [script, input]), /No slides found/);
});

test('empty Markdown cannot export stale HTML', async t => {
  const directory = await workspace(t);
  const input = path.join(directory, 'empty.md');
  await writeFile(input, '');
  await writeFile(path.join(directory, 'empty.html'), '<section class="slide">Stale content</section>');
  await assert.rejects(run(process.execPath, [script, input]), /No visible slides/);
});

test('Markdown is regenerated with diagrams and hidden slides excluded', { timeout: 120_000 }, async t => {
  const directory = await workspace(t);
  const input = path.join(directory, 'presentation.md');
  await writeFile(input, `---
theme: clean
presentation-title: PDF integration test
---
---title
# PDF integration test
>> Private speaker note
---content
hidden: true
# Draft
---content
# Diagram
\`\`\`mermaid
graph LR
  A[Markdown] --> B[PDF]
\`\`\`
---quote
A complete quotation, without a typewriter animation.
`);
  await writeFile(path.join(directory, 'presentation.html'), 'Stale HTML');
  const output = `${directory}${path.sep}`;
  await run(process.execPath, [script, input, '--output', output], { timeout: 110_000 });
  const html = await readFile(path.join(directory, 'presentation.html'), 'utf8');
  assert.match(html, /PDF integration test/);
  assert.doesNotMatch(html, />Draft</);
  const pdf = await PDFDocument.load(await readFile(path.join(directory, 'presentation.pdf')));
  assert.equal(pdf.getPageCount(), 3);
});
