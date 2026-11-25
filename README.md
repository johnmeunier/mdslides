# Slides Generator

This repository generates HTML presentations from Markdown files, then exports those presentations to PDF.

## Features

**Current features :**
- Generate HTML presentations from Markdown files
- Export presentations to PDF
- Include speaker notes in the presentation
- Support a huge type of slides :
  - Title 
  - Subtitle
  - Content 
  - Image 
  - Code 
  - Quote 
  - List 
  - Closing
  - Iframe
- Support mermaid diagrams
- Broadcast synchronized slides on the local network
- Use a smartphone as a password-protected remote with speaker notes and the shared timer

**Incoming features :**
- [x] Support for additional slide types
- [x] Theme support (`corpo` by default, `corail` and `clean` available)
- [] Auto internationalization
- [x] Smartphone as a remote and note viewer

## Prerequisites

- Python 3 to generate the HTML
- Node.js and npm for PDF export

## Installation

If you want to export to PDF, install the Node.js dependencies once at the project root:

```bash
npm install
npx playwright install chromium
```

The exporter uses Playwright's headless Chromium browser. On Linux, use
`npx playwright install --with-deps chromium` if browser system libraries are missing.

## Generate HTML from Markdown

The main generator is [generate.py](generate.py).

Example using a presentation:

```bash
python3 generate.py --input <PATH_TO_MD_FILE>
```

This automatically creates an HTML file next to the source Markdown file:

```text
<PATH_TO_HTML_FILE>
```

Other available usages:

```bash
python3 generate.py
python3 generate.py --watch
python3 generate.py --input <PATH_TO_MD_FILE>
```

Quick explanation:

- without an option, the script attempts to generate HTML from `content.md`
- `--input` lets you target any Markdown file
- `--watch` automatically regenerates the HTML when the Markdown changes

## Themes

The default theme remains `corpo`. To use the minimal white theme with generous
spacing, serif slide titles, bold subtitles and restrained blue accents, set `clean` in the
Markdown front matter:

```md
---
theme: clean
---
```

The `corail` theme remains available as well.

## Speaker Notes

In a slide block, lines beginning with `>>` are private comments for the speaker. They are omitted from the visible slide content, but can be viewed during the presentation using the `Notes` button or the `N` key.

```md
---content
# Slide title
>> Remember to give a concrete example here.
Visible text on the slide.
```

Comments are also excluded from PDF exports.

## Presentation Timer

Set `timer` in the front matter to display a countdown in the presentation header. Its value is expressed in minutes and may be fractional. The timer starts when the presentation leaves the first slide; click it to reset the countdown.

```md
---
presentation-title: My presentation
timer: 20
---
```

## LAN Broadcast and Smartphone Remote

Install the optional server dependency in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Start the server on demand with a Markdown presentation:

```bash
python3 generate.py --input <PATH_TO_MD_FILE> --serve
```

The terminal displays:

- the LAN broadcast URL, for example `http://192.168.1.42:8000/`
- the remote URL, for example `http://192.168.1.42:8000/?mode=remote`
- a randomly generated remote password
- a local presenter URL: open it on the computer to control the slides using the
  usual keyboard, mouse and notes panel
- a scannable **QR code directly in the terminal**, granting access to the
  smartphone remote without typing the password

Use a reasonably wide terminal with a light background around the QR code.
If scanning is difficult, open the remote URL and enter the displayed password.

The phone and computer must be on the same network. Allow incoming connections
to the selected port in the computer's firewall. Guest Wi-Fi or access-point
client isolation may prevent devices from communicating.

The public broadcast follows the current slide in read-only mode. Authenticated
remotes and the local presenter share navigation and the countdown; a newly
connected viewer immediately joins the current slide. The countdown starts when
leaving the first slide and can be reset remotely. The phone displays the current
slide's notes, which are never embedded in the broadcast HTML or returned by the
public state API. Multiple authenticated remotes can control the same presentation.

The remote shows the timer and slide counter at the top, internally scrollable
notes in the middle, and a fixed bottom navigation bar. The next-slide button
occupies half the bar. Tap the timer to reset it. Authentication and connection
errors only appear when needed.

Choose a different port or network interface when necessary:

```bash
python3 generate.py --input <PATH_TO_MD_FILE> --serve --port 9000 --address 192.168.1.42
```

`--address` is the computer's LAN IPv4 address, not the phone's address.
`--port 0` selects an available port automatically.

Stop with **Ctrl+C**. Each launch creates a new password, QR access token and
presentation state, invalidating previous sessions. The server serves an
in-memory snapshot without writing an HTML file or exposing the source directory.
Restart it after editing the Markdown; `--serve` cannot be combined with `--watch`.

**Privacy:** this is plain HTTP for a trusted local network, not an Internet
hosting service. Do not forward its port to the Internet. Keep the password,
presenter link and QR code private: anyone possessing them can read notes and
control the slides. LAN peers able to intercept HTTP traffic can also obtain
credentials. No cloud relay is used. Existing external fonts, diagrams or embeds
may still require Internet access.

Tests: `python3 -m unittest discover -s tests -v` and
`node --test tests/client.test.mjs`.

## Generate the PDF

The available npm command is:

```bash
npm run slides:pdf -- <PATH_TO_MD_OR_HTML_FILE>
```

Example:

```bash
npm run slides:pdf -- <PATH_TO_MD_FILE>
```

Behavior:

- if the input is an `.md` file, the HTML is automatically regenerated before export
- if the input is an `.html` file, it is used directly
- the PDF is generated next to the input file when no output path is specified

Default output examples:

```text
<PATH_TO_PDF_FILE>
```

## PDF Command Options

### Input Path

You can provide either a Markdown or an HTML file:

```bash
npm run slides:pdf -- <PATH_TO_MD_FILE>
npm run slides:pdf -- <PATH_TO_HTML_FILE>
```

### Output Path

Use `--output` or `-o` to choose the name or directory of the generated PDF:

```bash
npm run slides:pdf -- <PATH_TO_MD_FILE> --output <PATH_TO_PDF_FILE>
npm run slides:pdf -- <PATH_TO_MD_FILE> --output <OUTPUT_DIRECTORY>/<PDF_FILE_NAME>
npm run slides:pdf -- <PATH_TO_MD_FILE> -o <OUTPUT_DIRECTORY>/<PDF_FILE_NAME>
```

### HD Quality

PDF exports are currently generated in HD by default. No additional option needs to be enabled.

Specifically:

- slides are rendered in high definition before being assembled into the PDF
- interactive elements that are not useful in PDF format are hidden
- each PDF page corresponds to the final visible state of a slide

The render uses a 1920 x 1080 viewport at 2x resolution (3840 x 2160 pixels)
and a 16:9 PDF page. Fonts, images and Mermaid diagrams are awaited before capture.
The PDF contains slide images, so its text is not selectable. External resources
(fonts, diagrams and embeds) may require Internet access.

## Recommended Workflow

For a Markdown presentation:

```bash
python3 generate.py --input <PATH_TO_MD_FILE>
npm run slides:pdf -- <PATH_TO_MD_FILE>
```

Or directly, with a single command for the PDF:

```bash
npm run slides:pdf -- <PATH_TO_MD_FILE>
```

In the latter case, the HTML is generated automatically before the PDF is exported.