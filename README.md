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

**Incoming features :**
- [] Support for additional slide types
- [x] Theme support (`corpo` by default, `corail` available)
- [] Auto internationalization

## Prerequisites

- Python 3 to generate the HTML
- Node.js and npm for PDF export

## Installation

If you want to export to PDF, install the Node.js dependencies once at the project root:

```bash
npm install
```

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