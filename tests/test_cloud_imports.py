"""The dashboard must start on a small cloud server without the heavy build-time libraries."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_app_modules_import_without_geopandas_rasterio_or_sklearn():
    code = (
        "import sys, builtins\n"
        "real = builtins.__import__\n"
        "def guard(name, *a, **k):\n"
        "    if name.split('.')[0] in {'geopandas', 'rasterio', 'rasterstats', 'pymannkendall', 'sklearn'}:\n"
        "        raise ImportError('blocked for cloud test: ' + name)\n"
        "    return real(name, *a, **k)\n"
        "builtins.__import__ = guard\n"
        f"sys.path.insert(0, {str(ROOT / 'src')!r})\n"
        "from ukame import agent, agent_tools, config, guardrails, watch\n"
        "from ukame.data import fetch_forecast\n"
        "from ukame.outlook import display_probability\n"
        "print('ok')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
