# report/

Final 6-page term-project report (English).

| File | Purpose |
|---|---|
| `report.md` | Source text (subset of Markdown: headings, paragraphs, bullets, pipe tables, code fences, `![w=<fraction> caption](path)`) |
| `build.py` | `report.md` -> `report.docx` (python-docx) -> `report.pdf` (docx2pdf, needs Microsoft Word); prints the PDF page count |
| `make_figures.py` | Draws `figures/er.png` (ER diagram) and `figures/perf.png` (reads `bench/results/*.csv`) |
| `console/` | Raw CLI transcripts shown in the report (`drive.py` feeds scripted input to `python -m scouting`; run on a copy of `data/scouting.sqlite` with an admin account `demo`) |

## Build

```bash
pip install python-docx docx2pdf pymupdf matplotlib   # installed only for this report tool; not in requirements.txt
python report/make_figures.py
python report/build.py            # add --no-pdf to skip the Word conversion
```

Layout: A4, 2.0 cm margins, Times New Roman 11 pt body (code 7.5 pt, tables 9 pt), single column. The page count is measured on the PDF exported by Word (`PDF pages: 6` is printed by `build.py`). If Word is not available, `build.py --no-pdf` still produces the DOCX, but the page count must then be checked in Word.
Every number in `report.md` comes from `bench/results/*` or `docs/CONTRACT.md` §1 (see the source list in the hand-off note).
