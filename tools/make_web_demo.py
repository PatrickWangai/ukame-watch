"""Generate index.html: the dashboard running entirely in the visitor's browser (stlite + Pyodide),
served free by GitHub Pages straight from this repository. No server, no account.

Usage: python tools/make_web_demo.py   (rerun after adding files the app reads)

The local-LLM assistant cannot run in a browser, so the "Draft an advisory" tab explains how to
run it locally instead. Everything else, including the live 7-day forecast, works.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STLITE = "1.12.2"  # bundles Streamlit 1.65; tested with this version

APP_FILES = (
    ["app/streamlit_app.py", "docs/limitations.md"]
    + [f"src/ukame/{m}.py" for m in ["__init__", "config", "agent", "agent_tools", "guardrails", "watch",
                                     "outlook", "data"]]
    + sorted(str(p.relative_to(ROOT)) for p in (ROOT / "data/processed").glob("*") if p.suffix in
             {".csv", ".json", ".geojson"})
    + sorted(str(p.relative_to(ROOT)) for p in (ROOT / "data/reference").glob("*") if p.suffix in {".csv", ".json"})
)

STREAMLIT_CONFIG = {
    "theme.base": "light", "theme.primaryColor": "#0F6E66", "theme.backgroundColor": "#EEF0EC",
    "theme.secondaryBackgroundColor": "#FCFCFB", "theme.textColor": "#1B1D1C", "client.toolbarMode": "viewer",
}

HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />
  <title>Ukame Watch: drought, heavy-rain and heat early warning for northern Kenya</title>
  <meta name="description" content="Planning-support dashboard for eight arid counties of northern Kenya. Zetech Hackathon 2026, Climate Sentinel." />
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@stlite/browser@{stlite}/build/stlite.css" />
  <style>
    body {{ margin: 0; background: #EEF0EC; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: #1B1D1C; }}
    #loading {{ max-width: 640px; margin: 18vh auto 0; padding: 0 1.5rem; }}
    #loading h1 {{ font-size: 2rem; margin: 0 0 .4rem; }} #loading h1 span {{ color: #0F6E66; }}
    #loading p {{ color: #52514e; line-height: 1.5; }}
    #loading .bar {{ height: 4px; background: #d9dcd6; border-radius: 2px; overflow: hidden; margin-top: 1.2rem; }}
    #loading .bar div {{ height: 100%; width: 30%; background: #0F6E66; animation: slide 1.4s ease-in-out infinite; }}
    @keyframes slide {{ 0% {{ margin-left: -30%; }} 100% {{ margin-left: 100%; }} }}
    @media (prefers-reduced-motion: reduce) {{ #loading .bar div {{ animation: none; width: 100%; }} }}
  </style>
</head>
<body>
  <div id="loading">
    <h1>Ukame <span>Watch</span></h1>
    <p>Starting the dashboard in your browser. The first visit downloads Python and the data
       (about 30–60 seconds); later visits are faster.</p>
    <p>Planning support only — not an official warning. Kenya Meteorological Department warnings and NDMA
       drought bulletins take priority.</p>
    <div class="bar" aria-hidden="true"><div></div></div>
  </div>
  <div id="root"></div>
  <script type="module">
    import {{ mount }} from "https://cdn.jsdelivr.net/npm/@stlite/browser@{stlite}/build/stlite.js";
    const files = {files};
    mount(
      {{
        requirements: ["pandas", "plotly", "shapely", "requests"],
        entrypoint: "app/streamlit_app.py",
        files: Object.fromEntries(files.map((f) => [f, {{ url: "./" + f }}])),
        streamlitConfig: {config},
      }},
      document.getElementById("root"),
    );
    new MutationObserver((_, obs) => {{
      if (document.querySelector("[data-testid='stApp'] [data-testid='stMarkdown']")) {{
        document.getElementById("loading").remove(); obs.disconnect();
      }}
    }}).observe(document.getElementById("root"), {{ childList: true, subtree: true }});
  </script>
</body>
</html>
"""


def main():
    missing = [f for f in APP_FILES if not (ROOT / f).exists()]
    if missing:
        raise SystemExit(f"Missing files: {missing}")
    (ROOT / "index.html").write_text(HTML.format(stlite=STLITE, files=json.dumps(APP_FILES, indent=6),
                                                  config=json.dumps(STREAMLIT_CONFIG)))
    (ROOT / ".nojekyll").write_text("")  # serve dot-folders and every file as-is on GitHub Pages
    print(f"wrote index.html ({len(APP_FILES)} files mounted)")


if __name__ == "__main__":
    main()
