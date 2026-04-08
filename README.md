# Articulous Static Site Generator

[![Articulous](https://github.com/geraldo-netto/articulous/actions/workflows/main.yml/badge.svg)](https://github.com/geraldo-netto/articulous/actions/workflows/main.yml)  
A fast, parallel, incremental static site generator powered by **XML + XSLT**.  
Written in Python, with optional SaxonC acceleration for high‑performance builds.

---

## 🚀 Features

- XML‑based article format  
- XSLT‑driven rendering pipeline  
- Parallel build execution  
- Incremental caching (only rebuilds changed files)  
- Automatic generation of:
  - Article pages  
  - Paginated index pages  
  - Tag pages  
  - RSS feed  
  - Sitemap  
  - Search index (JSON)  
- Dry‑run mode  
- Section‑limited builds (`--only`)  
- Optional SaxonC support  

---

## 📁 Project Structure

Your project should follow this layout:

articulous/
├── sitegen.py
├── config.json
├── content/
│   └── (your .xml articles)
│
├── xsl/
│   └── pages/
│       ├── article.xsl
│       ├── index.xsl
│       ├── tags.xsl
│       ├── rss.xsl
│       ├── sitemap.xsl
│       └── search.xsl
│
├── assets/
│   └── (images, css, js, etc.)
│
├── output/
│   ├── en/
│   │   ├── articles/
│   │   ├── page/
│   │   ├── tags/
│   │   └── (generated files)
│   ├── rss.xml
│   ├── sitemap.xml
│   └── search.json
│
└── .build-cache.json

---

## 📝 Article Format (XML)

Place your articles inside `content/` using this structure:

<article>
  <title>Hello World</title>
  <date>2024-01-01</date>
  <description>My first article.</description>
  <tag>intro</tag>
  <tag>welcome</tag>
</article>

---

## 🧩 Required XSL Templates

The generator requires these files inside `xsl/pages/`:

- article.xsl
- index.xsl
- tags.xsl
- rss.xsl
- sitemap.xsl
- search.xsl

---

## ⚙️ Running the Generator

Make the script executable:

chmod +x sitegen.py

Run it:

./sitegen.py

Or explicitly:

python3 sitegen.py

---

## 🔧 Useful CLI Options

--config FILE        Use a custom config file
--only SECTIONS      Build only specific sections (comma-separated)
--lang LANG          Limit build to specific languages
--slug SLUG          Build only specific article slugs
--dry-run            Do not write output files
--force              Ignore cache and rebuild everything
-v, --verbose        Enable debug logging

Examples:

./sitegen.py --only articles
./sitegen.py --only index,tags --verbose
./sitegen.py --slug hello-world
./sitegen.py --dry-run

---

## 🛠️ Configuration

The generator uses config.json.  
If missing, defaults are applied automatically.

Key sections include:

- paths (content, output, xsl, assets)
- engines (lxml or saxonc)
- site (name, base URL, languages, pagination)
- urls (routing patterns)
- build (cache file, parallelism)
- logging (level, optional file)

---

## 📦 Output

Generated files are written to output/, including:

- en/articles/<slug>/index.html
- en/page/<n>/index.html
- en/tags/<tag>/index.html
- rss.xml
- sitemap.xml
- search.json

---

## 🧪 Development Notes

- Incremental builds use .build-cache.json
- Parallelism defaults to CPU count
- SaxonC is optional but supported
- All XSLT transformations fall back to lxml if SaxonC is unavailable

---

## 📜 License

MIT
