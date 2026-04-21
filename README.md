# PSBT Analyzer

A Bitcoin PSBT analysis and optimization tool. Paste, upload, or POST a PSBT
and get a human-readable breakdown of inputs, outputs, script types, weight,
fees, and change heuristics. Compare coin-selection strategies and edit the
PSBT (structured or raw) with live re-analysis.

## Features

- Accept PSBT via file upload, base64/hex text, or raw API body.
- Parse and display:
  - PSBT version (v0 / v2).
  - Per-input and per-output amount, address, script type, weight contribution.
  - Total input value, output value, and inferred fee plus sat/vB fee rate.
- Summary of:
  - Change-output heuristics (with confidence label).
  - Fee reasonableness vs current mempool (via [mempool.space](https://mempool.space/docs/api/)).
  - Script types used and weight / fee implications (segwit and taproot discounts).
- Coin-selection simulator pre-filled from the parsed PSBT (outputs -> targets,
  inputs -> initial UTXO pool); compare strategies (largest-first, smallest-first,
  naive branch-and-bound).
- Structured PSBT editor: toggle inputs, edit output amounts, re-serialize,
  and re-run analysis. Raw base64/hex textarea remains as a fallback.

## Quick start

```powershell
# 1. Create venv and install in editable mode
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]

# 2. Copy env template
copy .env.example .env

# 3. Run the API + UI
uvicorn psbt_tool.api.main:app --reload
```

Then open `http://127.0.0.1:8000/` for the web UI or
`http://127.0.0.1:8000/docs` for interactive OpenAPI.

## API

| Method | Path                   | Purpose                                                   |
| ------ | ---------------------- | --------------------------------------------------------- |
| POST   | `/api/psbt/analyze`    | Analyze a PSBT (JSON body, form, or file upload).         |
| POST   | `/api/psbt/apply`      | Apply structured edits and return the new PSBT + report.  |
| POST   | `/api/coin-sim/run`    | Run coin-selection strategies on a UTXO pool and targets. |
| GET    | `/api/fees/recommended`| Current mempool.space recommended fees (cached).          |

## Trust and privacy

- PSBT bytes are parsed locally in this service.
- Only **fee rates** are fetched from the configured mempool endpoint; the PSBT
  itself never leaves the server.
- See `.env.example` for configuration.

## Tests

```powershell
pytest
```
