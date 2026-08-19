# License Checking Guide

This document describes how to run license checks on both the frontend and backend dependencies of the UC App project.

## Overview

License checking helps ensure compliance with open-source licenses and provides transparency about the dependencies used in the project.

## What Was Added

### Frontend
- **Tool**: `license-checker` (npm package)
- **Added to**: `devDependencies` in `src/frontend/package.json`
- **Scripts**: `license-check`, `license-check:full`, `license-check:production`

### Backend  
- **Tool**: `pip-licenses` (Python package)
- **Added to**: `requirements.txt` in `src/backend/`

### Root Scripts
- **Location**: `src/package.json`
- **Combined scripts** for easy execution from the root

## Prerequisites

### Frontend
- npm (bundled with Node.js)
- `license-checker` npm package (automatically installed with `npm install`)

### Backend
- Python environment with dependencies installed (virtual environment recommended)
- `pip-licenses` package (included in requirements.txt)
- **Note:** Install pip-licenses in your project's virtual environment:
  ```bash
  # Activate your virtual environment first, then:
  pip install pip-licenses
  # Or install all requirements:
  pip install -r requirements.txt
  ```

## Quick Start

### Check All Licenses

From the `src/` directory:

```bash
npm run license-check:all
```

This will display license information for both frontend and backend dependencies.

## Frontend License Checks

### From `src/frontend/` Directory (Recommended)

```bash
cd src/frontend

# Quick summary
npm run license-check

# Full export (JSON + CSV)
npm run license-check:full

# Production dependencies only
npm run license-check:production
```

### From `src/` Directory

```bash
# Check frontend licenses
npm run license-check:frontend

# Full export with JSON and CSV files
npm run license-check:frontend:full
```

**Note:** Commands run from `src/` automatically change to the `frontend/` directory before executing. This is the simplest and most reliable approach.

### Output Formats

**Summary View:**
```
├─ MIT: 579
├─ ISC: 62
├─ Apache-2.0: 14
├─ BSD-3-Clause: 9
├─ BSD-2-Clause: 3
└─ ...
```

**Full Export:** Generates two files in `src/frontend/`:
- `licenses.json` - Full license data in JSON format
- `licenses.csv` - Spreadsheet-compatible format

## Backend License Checks

### From `src/` Directory

```bash
# Markdown format (recommended)
npm run license-check:backend

# JSON export
npm run license-check:backend:json
```

### From `src/backend/` Directory

```bash
cd src/backend

# Markdown format
pip-licenses --format=markdown

# Or other formats
pip-licenses --format=json
```

### Direct pip-licenses Usage

From the `src/backend/` directory:

```bash
# Summary table
pip-licenses

# Markdown format
pip-licenses --format=markdown

# JSON format
pip-licenses --format=json

# CSV format
pip-licenses --format=csv

# Filter by license
pip-licenses --from=classifier --order=license

# With URLs
pip-licenses --with-urls
```

### Output Format

**Markdown Table:**
```
| Name           | Version | License     | URL                                    |
|----------------|---------|-------------|----------------------------------------|
| fastapi        | 0.110.2 | MIT         | https://github.com/tiangolo/fastapi    |
| uvicorn        | 0.32.0  | BSD-3-Clause| https://www.uvicorn.org/              |
| ...            | ...     | ...         | ...                                    |
```

## Understanding License Types

Common licenses you'll encounter:

- **MIT**: Permissive license allowing commercial use
- **Apache-2.0**: Permissive license with patent grant
- **BSD**: Family of permissive licenses
- **ISC**: Similar to MIT
- **LGPL/GPL**: Copyleft licenses (requires attention)
- **Python Software Foundation**: Python-specific license

## Compliance Tips

1. **Regular Checks**: Run license checks before major releases
2. **Document Changes**: Track when new dependencies are added
3. **Review Restrictive Licenses**: Pay special attention to GPL, AGPL licenses
4. **Commercial Use**: Ensure all licenses permit commercial use
5. **Attribution**: Some licenses require attribution in documentation

## CI/CD Integration

You can add license checking to your CI/CD pipeline:

```yaml
# Example GitHub Actions step
- name: Check licenses
  run: |
    cd src/frontend
    npm run license-check
    cd ../backend
    bash check_licenses.sh
```

## Troubleshooting

### Frontend: "license-checker: command not found"

Install dependencies:
```bash
cd src/frontend
npm install
```

### Backend: "pip-licenses: command not found"

Make sure you're in your Python virtual environment and install the package:
```bash
cd src/backend

# Activate your virtual environment first (example for venv)
source venv/bin/activate  # On Unix/macOS
# or
venv\Scripts\activate  # On Windows

# Then install pip-licenses
pip install pip-licenses
# or install all requirements
pip install -r requirements.txt
```

If you're not using a virtual environment, you may need to use:
```bash
pip install --user pip-licenses
```

### npm not found

Make sure Node.js (which bundles npm) is installed. See the [Node.js downloads page](https://nodejs.org/en/download) or use a version manager such as `nvm`.

## Output Files

The following files are generated by license checks and are excluded from git:

- `licenses.json` - JSON format license data
- `licenses.csv` - CSV format license data

These files are automatically ignored by `.gitignore`.

## Additional Resources

- [license-checker documentation](https://github.com/davglass/license-checker)
- [pip-licenses documentation](https://github.com/raimon49/pip-licenses)
- [Choose an open source license](https://choosealicense.com/)
- [SPDX License List](https://spdx.org/licenses/)

## Files Modified

1. `src/frontend/package.json` - Added `license-checker` and scripts
2. `src/backend/requirements.txt` - Added `pip-licenses`
3. `src/package.json` - Added convenience wrapper scripts
4. `.gitignore` - Excluded license output files
5. `README.md` - Added license checking section
6. `docs/LICENSE_CHECKING.md` - This documentation

## Key Benefits

1. **Compliance**: Track all open-source licenses in use
2. **Transparency**: Know what licenses govern your dependencies
3. **Automated**: Easy to run before releases
4. **CI/CD Ready**: Can be integrated into pipelines
5. **Multiple Formats**: Summary, JSON, CSV, and Markdown outputs
