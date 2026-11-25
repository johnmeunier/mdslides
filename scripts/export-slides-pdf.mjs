import { execFile } from 'node:child_process';
import { mkdir, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { parseArgs, promisify } from 'node:util';
import { PDFDocument } from 'pdf-lib';
import { chromium } from 'playwright';

const root = fileURLToPath(new URL('../', import.meta.url));
const run = promisify(execFile);
const viewport = { width: 1920, height: 1080 };

async function main() {
  const { values, positionals } = parseArgs({
    options: {
      output: { type: 'string', short: 'o' },
      help: { type: 'boolean', short: 'h' },
    },
    allowPositionals: true,
  });
  if (values.help) {
    console.log('Usage: npm run slides:pdf -- <file.md|file.html> [-o <file.pdf|directory/>]');
    return;
  }
  if (positionals.length !== 1) throw new Error('Provide exactly one Markdown or HTML input file.');
  const input = path.resolve(positionals[0]);
  const extension = path.extname(input).toLowerCase();
  if (!['.md', '.html', '.htm'].includes(extension)) {
    throw new Error('Input must be a Markdown (.md) or HTML (.html, .htm) file.');
  }
  if (!(await stat(input)).isFile()) throw new Error(`Not a file: ${input}`);
  const stem = path.basename(input, path.extname(input));
  let output = path.resolve(values.output ?? path.join(path.dirname(input), `${stem}.pdf`));
  const outputInfo = await stat(output).catch(error => {
    if (error.code !== 'ENOENT') throw error;
    return null;
  });
  if (outputInfo?.isDirectory() || values.output?.endsWith(path.sep)) {
    output = path.join(output, `${stem}.pdf`);
  }
  if (path.extname(output).toLowerCase() !== '.pdf') {
    throw new Error('Output must be a .pdf file or a directory.');
  }

  let html = input;
  if (extension === '.md') {
    // The generator does not fail on an empty deck; reject it before using stale HTML.
    const { stdout, stderr } = await run('python3', [
      '-c',
      'import sys; import generate; text = open(sys.argv[1], encoding="utf-8").read(); '
        + '_, body = generate.parse_front_matter(text); '
        + 'slides = generate.parse_content(body); '
        + 'sys.exit(0 if any(not generate.is_hidden_slide(slide) for slide in slides) else "No visible slides in Markdown input.")',
      input,
    ], { cwd: root });
    if (stdout) process.stdout.write(stdout);
    if (stderr) process.stderr.write(stderr);
    const generated = await run('python3', [path.join(root, 'generate.py'), '--input', input], { cwd: root });
    process.stdout.write(generated.stdout);
    process.stderr.write(generated.stderr);
    html = path.join(path.dirname(input), `${stem}.html`);
  }

  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport, deviceScaleFactor: 2 });
    page.setDefaultTimeout(30_000);
    page.on('console', message => {
      if (message.type() === 'warning' || message.type() === 'error') {
        console.warn(`Page warning: ${message.text()}`);
      }
    });
    page.on('pageerror', error => console.warn(`Page warning: ${error.message}`));
    page.on('requestfailed', request => console.warn(`Resource warning: ${request.url()} (${request.failure()?.errorText})`));
    await page.goto(pathToFileURL(html).href, { waitUntil: 'load', timeout: 60_000 });
    const slides = page.locator('.slide');
    const count = await slides.count();
    if (!count) throw new Error('No slides found in the HTML presentation.');

    await page.addStyleTag({ content: `
      html, body { scroll-behavior: auto !important; scroll-snap-type: none !important; }
      * { animation: none !important; transition: none !important; caret-color: transparent !important; }
      .reveal { opacity: 1 !important; transform: none !important; filter: none !important; }
      .top-controls, .toc-backdrop, .toc-panel, .notes-panel, .network-status,
      .quote-copy-btn, .code-copy-btn, .code-scroll-hint { display: none !important; }
      .quote-typewriter::after { display: none !important; }
    ` });
    if (await page.locator('.mermaid').count()) {
      await page.waitForFunction(() => [...document.querySelectorAll('.mermaid')]
        .every(element => element.querySelector('svg') && !element.querySelector('.error-icon')));
    }

    const pdf = await PDFDocument.create();
    for (let index = 0; index < count; index += 1) {
      await slides.nth(index).evaluate((element, slideIndex) => {
        element.querySelectorAll('img').forEach(image => { image.loading = 'eager'; });
        if (typeof goToIndex === 'function') goToIndex(slideIndex, false);
        else element.scrollIntoView({ behavior: 'instant', block: 'start' });
      }, index);
      await slides.nth(index).evaluate(async element => {
        await document.fonts.ready;
        await Promise.all([...element.querySelectorAll('img')].map(image => image.decode().catch(error => {
          console.warn(`Image warning: ${image.src} (${error.message})`);
        })));
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      });
      await slides.nth(index).evaluate(element => {
        if (typeof runQuoteTypewriter === 'function') runQuoteTypewriter(element, true);
        else element.querySelectorAll('[data-typewriter-text]').forEach(quote => {
          quote.textContent = quote.dataset.typewriterText;
        });
      });
      const image = await pdf.embedPng(await page.screenshot({ type: 'png' }));
      const pdfPage = pdf.addPage([960, 540]);
      pdfPage.drawImage(image, { x: 0, y: 0, width: 960, height: 540 });
    }
    await mkdir(path.dirname(output), { recursive: true });
    await writeFile(output, await pdf.save());
    console.log(`PDF: ${output} (${count} slides, 3840 x 2160)`);
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(`PDF export failed: ${error.message}`);
  process.exitCode = 1;
});
