# PSBT Analyzer — Code Review

**Repo:** `andrewbiv/psbt-analyzer`
**Reviewed commit:** `c120b82` (3 commits total on `main`)
**Scope:** correctness, security, API contract, concurrency, tests, code quality, production readiness, UI.
**Verdict:** Happy-path parser/editor logic is solid and the codebase reads like someone who has done this before. The soft spots are all at the boundaries: adversarial input, network mixing, and untrusted data rendering. Fixing the Critical + High items below moves this from "competent" to "staff-level."

Findings are ranked **Critical → High → Medium → Low → Nit**. Every finding has a file + line reference, a concrete problem statement, why it matters, and a suggested fix.

---

## Table of contents

- [Executive summary](#executive-summary)
- [Critical](#critical)
- [High](#high)
- [Medium](#medium)
- [Low](#low)
- [Nits](#nits)
- [Quick-win punch list (~30 min)](#quick-win-punch-list-30-min)
- [Testing gaps](#testing-gaps)
- [Functional test results](#functional-test-results)

---

## Executive summary

**The 8 findings most likely to cost points in an employer review:**

1. **XSS throughout the frontend** (C1) — untrusted server fields written to `innerHTML` in `static/app.js`. Mechanical, pervasive, easy to fix with one `escapeHtml` helper.
2. **Open CORS on a "privacy-focused" tool** (C3) — `allow_origins=["*"]` directly contradicts the README's "PSBT bytes are processed locally" claim. Any visited webpage can exfiltrate analyzed PSBTs.
3. **Network-mixing footgun** (H2, H3) — unknown `NETWORK` values silently fall back to mainnet; the editor accepts cross-network addresses without validation. A Bitcoin-focused employer will catch this first.
4. **Unbounded branch-and-bound recursion** (C2) — remote DoS via 2^N subset enumeration; no `utxos` length cap in the Pydantic model.
5. **`except Exception` in every route** (H7) — swallows 500s as 400s, leaks internal error strings to clients (including the configured mempool URL).
6. **`_synthetic_txid` silently produces unspendable PSBTs** (H4) — `add_input` without a caller-supplied txid hashes `time.time_ns()`. No warning to the user.
7. **Pydantic models missing constraints** (H5, C2) — negative `value_sats`, negative fee rates, unbounded UTXO lists. Pydantic is here but underused.
8. **No structured logging or observability** (L1, L2) — nothing to look at when something breaks in production.

**Total findings:** 3 Critical · 9 High · 14 Medium · 10 Low · 10 Nit.

---

## Critical

### C1. XSS in the frontend — untrusted fields injected as raw HTML

**File:** `static/app.js:120-166` (`renderInputs`/`renderOutputs`), `:188` (`cmp.note`), `:242` (`r.message`), `:157-158` (`change_reasons`).

`renderInputs`, `renderOutputs`, `renderSimUtxos`, `renderSimTargets`, `renderSimResults`, and `renderFees` all assign untrusted server-derived strings directly to `.innerHTML` via template literals:

```js
<td class="mono">${i.address || "—"}</td>
...
<span class="badge bad">${r.message || "failed"}</span>
```

`r.message` can contain `f"Unknown strategy: {name}"` where `name` is entirely client-supplied. `cmp.note`, `change_reasons`, `script_pub_key_hex`, and `script_mix_note` are all unescaped.

**Why it matters:** self-XSS today (attacker-supplied strategy name reflected into their own DOM), but the pattern is pervasive — it will bite as soon as any free-text field is added. In an interview review this is the first thing a reviewer flags.

**Fix:** add an escape helper and wrap every `${...}` that is not a known integer/enum:

```js
const escapeHtml = (s) => String(s).replace(/[&<>"']/g, c => ({
  '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
}[c]));
```

Better: build DOM nodes with `textContent` / `createElement` rather than `innerHTML`.

---

### C2. `_branch_and_bound` is exponential and user-controlled — DoS vector

**File:** `src/psbt_tool/core/coin_sim.py:117-163`.

Full 2^N subset enumeration with only a `MAX_TRIES = 100_000` counter as a cap. Each node also does `sum(u.value_sats for u in pool[idx:])` plus `sum(...) for chosen` per recursion — effectively **O(N · 2^N)** per request. There is no input-size limit on `utxos` in `CoinSimRequest`.

A client can POST `{"utxos": [...200 items...], "strategies": ["branch_and_bound"]}` and burn the event loop.

**Why it matters:** trivially remote-DoS-able. No auth, no rate limit, route is fully async — one heavy request parks the uvicorn worker.

**Fix:**
- Cap `utxos` length in `CoinSimRequest`: `Field(max_length=64)`.
- Pre-compute `suffix_sum[i]` once instead of summing in each branch.
- Move `MAX_TRIES` into `Settings` and surface a warning when exhausted (see M4).
- Consider `await asyncio.to_thread(run_simulation, ...)` so sim work doesn't block the loop.

---

### C3. Open CORS on a service that holds PSBT contents

**File:** `src/psbt_tool/api/main.py:31-37`.

```python
allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
```

With the service listening on `127.0.0.1`, any web page the user visits can `fetch()`-POST a PSBT they are about to analyze and read the full parsed report (addresses, amounts, script types, change candidates). Credentials off does **not** help — the browser same-origin policy does not block request *bodies* with open CORS.

**Why it matters:** README explicitly says *"PSBT bytes are processed locally"* as a privacy feature. Open CORS contradicts that.

**Fix:** default `allow_origins=[]` (same-origin only); make it configurable via `Settings.allow_origins`. If the service is truly local-only, skip CORS middleware entirely.

---

## High

### H1. `_load_dotenv` never reloads and uses a relative path

**File:** `src/psbt_tool/config.py:18-35`.

Two problems:

1. `_load_dotenv(path: str = ".env")` is a **relative path**. Starting the process from anywhere other than the repo root (IDE runner, docker workdir, systemd `ExecStart`) silently skips the `.env`. `NETWORK` then falls back to `mainnet` regardless of user config — a real footgun for testnet work.
2. `get_settings()` is `lru_cache`'d, so runtime env changes are invisible. That part is intentional but should be explicit.

**Fix:** anchor the path to the package:

```python
_DOTENV = Path(__file__).resolve().parents[2] / ".env"
def _load_dotenv(path: Path = _DOTENV) -> None:
    if not path.is_file(): return
    ...
```

---

### H2. Non-mainnet addresses silently render as mainnet

**File:** `src/psbt_tool/core/parser.py:35-37`, `src/psbt_tool/core/editor.py:54-55`.

```python
def _network(network: str) -> dict[str, Any]:
    key = _NETWORK_KEYS.get(network.lower(), "main")
    return NETWORKS[key]
```

If `NETWORK=foo` or any typo slips through, PSBTs get encoded with **mainnet** addresses without warning. `Settings` does not validate `network` against the four supported values. The `network` field in `PSBTReport` echoes the raw user string, but address rendering silently uses mainnet — a downstream UI will display a mainnet-looking address for a signet PSBT.

**Fix:** validate in `Settings` (raise on unknown). Optionally log a warning and fall back; never silently map to mainnet.

---

### H3. Editor accepts addresses from any network

**File:** `src/psbt_tool/core/editor.py:58-63`.

`address_to_scriptpubkey(op.address)` happily decodes **any** bech32/base58 string — mainnet, testnet, signet, regtest. A server running `NETWORK=testnet` will accept an `add_output` with a mainnet `bc1...` address and produce a PSBT that mixes networks and will never broadcast.

The `network` param is threaded through but only used for `_ = _network(network)` on line 186 — a dead lookup, no cross-check.

**Why it matters:** exactly the class of bug a Bitcoin-focused employer hunts for.

**Fix:**

```python
expected_hrp = _network(network).get("bech32")
if op.address and not op.address.startswith(expected_hrp):
    raise ValueError(f"Address {op.address} does not match network {network}")
```

Do it properly: decode and compare the HRP / version byte against the configured network dict.

---

### H4. `add_input` synthesizes a fake txid — silently creates an unspendable PSBT

**File:** `src/psbt_tool/core/editor.py:66-73, 162-171`.

When the client omits `txid`, `_synthetic_txid()` returns `sha256("manual-input-<nanosecond>")`. That hash has **no chance** of matching a real UTXO. The resulting PSBT parses cleanly (tests confirm this at `test_editor.py:70-83`) but is unsignable and unspendable.

The note `"Added input of X sats (address)"` does not warn the user.

**Why it matters:** the tool silently produces broken outputs. An interview reviewer reads this as "author didn't think about invariants."

**Fix:** require `txid` + `vout` for `add_input` (reject otherwise), OR when synthesized, append a prominent warning to both `notes` and `PSBTReport.warnings`:

> Input N: synthetic prevout txid; PSBT is for analysis only and cannot be signed.

---

### H5. Pydantic models missing field constraints

**File:** `src/psbt_tool/core/models.py` (EditOp, UTXO, PaymentTarget, CoinSimRequest).

- `EditOp.value_sats: int | None` — no `ge=0`. Negative values produce PSBTs with negative prevouts → parser reports "negative fee" instead of rejecting at the boundary.
- `UTXO.value_sats`, `PaymentTarget.value_sats` — no `ge=546` dust check.
- `CoinSimRequest.fee_rate_sat_vb` — no `ge=0`.
- `CoinSimRequest.dust_threshold_sats` — no `ge=0`.
- `CoinSimRequest.utxos` — no `max_length` (see C2).
- `CoinSimRequest.strategies` — no `Literal[...]` (see N3).

**Fix:** add constraints to every `value_sats`, `fee_rate_sat_vb`, and collection field. Pydantic is already a dep; use it.

---

### H6. Fee reasonableness misclassifies boundary values; upstream missing keys mis-default

**File:** `src/psbt_tool/core/fees.py:80-99`, `:50`.

The cascade `rate < minimum` → `below_min`, `rate < economy` → `min`, ..., `rate < fastest` → `half_hour`, `rate <= fastest * 1.25` → `fastest` is **off by one at every boundary**. E.g. `rate == hour` lands in `economy` rather than `hour`. The user-facing `note` says "Economy range" when the effective rate exactly matches the hour target.

Separately: `minimumFee` defaults to `1` if missing from the mempool response (`.get("minimumFee", 1)`). A future API change or a malicious mirror that returns string values will leave an empty dict after the `isinstance(v, (int, float))` filter, then `.get(..., 1)` substitutes `1` everywhere → all rates labeled `fastest`.

**Fix:** use `<=` for bucket transitions. Reject or warn when required keys are missing from the mempool response.

---

### H7. Route-level `except Exception` swallows internal errors as 400 and leaks details

**File:** `src/psbt_tool/api/routes.py:62-65, 88-89, 102-103, 119-120, 142-144, 151-154`.

Every route catches bare `Exception` and puts `str(exc)` into `HTTPException.detail`. That:

1. Leaks internal error messages (embit internals, Python type errors, file paths) to the client.
2. Converts legitimate 500s (programming bugs) into 400s (client errors), hiding them from ops dashboards.
3. Returns `502` with `str(exc)` in `/api/fees/recommended` — `httpx.ConnectError` messages include the upstream host, leaking the configured `MEMPOOL_BASE_URL`.

**Fix:** catch specific classes (`ValueError`, `binascii.Error`, `IndexError`, any embit `PSBTError`, `httpx.HTTPError`). Use a generic `"Invalid PSBT"` message for the catch-all. Log full tracebacks server-side via `logging.exception(...)`.

---

### H8. Size guard runs after the full body is read into memory

**File:** `src/psbt_tool/api/routes.py:27-40, 95-106`.

`_guard_size` runs **after** `python-multipart` has consumed the form body or `await file.read()` has loaded the whole upload. Default FastAPI form parsing has no explicit cap on field length. A 100 MB form body is read into memory before the guard fires.

**Fix:** stream uploads with a running counter; abort at `MAX_PSBT_BYTES`. For `analyze_text`, inspect `Content-Length` before consuming. Or add a Starlette middleware that rejects `Content-Length > MAX_PSBT_BYTES * 2` (base64 overhead).

---

### H9. Global fee cache has no stampede protection

**File:** `src/psbt_tool/core/fees.py:21, 33-55`.

`_CACHE` is a module-level dict keyed by `url_base`. Under concurrent requests with an empty cache, every one of them fires the upstream call — no `asyncio.Lock`. A burst of N requests at boot hits mempool.space N times; mempool rate-limits; the error path downgrades all responses to "Could not fetch mempool fees."

**Fix:** wrap the refetch in a per-key `asyncio.Lock`. One module-level lock is simplest and fine for a single upstream.

---

## Medium

### M1. No httpx client lifecycle — every cache miss spins up a new connection pool

**File:** `src/psbt_tool/core/fees.py:38-48`.

`httpx.AsyncClient` is instantiated per call when the caller doesn't pass one. No connection reuse, HTTP/2 keepalive, etc.

**Fix:** init a singleton `AsyncClient` in a FastAPI `lifespan` handler, attach to `app.state`, pass it to `fetch_recommended_fees`. Gives a clean shutdown path via `await client.aclose()`.

---

### M2. Fee rate display is not clamped

**File:** `src/psbt_tool/core/parser.py:215-221`, `static/app.js` (fees render).

Guard `vsize > 0` is fine, but a malformed PSBT where `fee` is huge yields absurd fee rates. Report: `note = f"{(rate / fastest - 1) * 100:.0f}% above next-block rate"` overflows visually ("1742309% above...").

**Fix:** clamp display in the frontend or surface "fee rate anomaly" in warnings.

---

### M3. `_psbt_version` silently returns `0` for anything non-int

**File:** `src/psbt_tool/core/parser.py:118-122`.

If embit changes its version attribute name, the report claims v2 PSBTs are v0. No test covers a real v2 PSBT — all fixtures use `Transaction(...)` + `PSBT(tx)` which defaults to v0.

**Fix:** explicitly handle v2. If `psbt.version` is `None` or unknown, surface a warning instead of defaulting to 0.

---

### M4. `_branch_and_bound` silently falls back to `_largest_first`, mislabeling results

**File:** `src/psbt_tool/core/coin_sim.py:161-163`.

```python
if best is None:
    return _largest_first(utxos, targets, fee_rate, change_type, dust)
```

On fallback (or `MAX_TRIES` exhaustion), the response is labeled `"branch_and_bound"` but contains `largest_first` output. User reads "best strategy: branch_and_bound" and is misled.

**Fix:** mark `ok=False` with `message="BnB exhausted"`, OR add a `fallback_from` field to `CoinSimResult`.

---

### M5. `heuristics._is_round` is crude

**File:** `src/psbt_tool/core/heuristics.py:14-21`.

A 1000-sat threshold treats `101_000` as round (likely a change amount) but `100_543` as non-round (which would often be a payment). Combined with `annotate_change`'s `script_type match: +0.35` weight, a 2-output PSBT where both outputs share the input script type can flip on "round amount" alone.

**Fix:** reduce `_is_round` weight, or document more clearly that the heuristic is indicative-only (already noted in the README; the concern is the interaction with other signals).

---

### M6. `TemplateResponse(request, ...)` signature

**File:** `src/psbt_tool/api/main.py:46-52`.

Works on `fastapi>=0.115`, deprecated on older pins. Fine given `pyproject.toml`'s lower bound; note if a downgrade happens this breaks.

**Fix:** add a smoke test that renders `/` and asserts a 200.

---

### M7. `/health` is just "process alive"

**File:** `src/psbt_tool/api/main.py:54-56`.

No mempool probe, no embit version check. Proper prod split is liveness vs readiness.

**Fix:** add a `/ready` endpoint that probes the fee cache (without refetching) and returns `degraded` if mempool has been unreachable for > N seconds.

---

### M8. `_guard_size` approximates, and `b64decode(validate=False)` accepts malformed base64

**File:** `src/psbt_tool/api/routes.py:30-33`.

`len(psbt_b64) * 3 // 4` is the lower bound of decoded bytes (fine for a guard). But `base64.b64decode(data, validate=False)` silently discards non-base64 chars and produces garbage bytes up to ~75% of input length. Neither the guard nor the decode step validates that the decoded bytes are a PSBT before consuming the full size.

**Fix:** `validate=True` on `b64decode` to fail fast; re-check size post-decode.

---

### M9. `normalize_psbt_base64_paste` space handling

**File:** `src/psbt_tool/core/parser.py:40-47`.

Comment correctly notes form-encoded `+` becomes space. Function also strips other whitespace (line breaks). Works for wrapped base64 paste; the `text` route only accepts strings so binary collision isn't possible via that path. Brittle but OK — worth a note.

---

### M10. `output_size(ScriptType.OP_RETURN, None) = 11` lowballs sim fees

**File:** `src/psbt_tool/core/scripts.py:50-53, 135-139`.

OP_RETURN payloads are commonly 40-80 bytes. The parser uses actual `spk_bytes` so the report is fine; the sim does not.

**Fix:** in sim, warn if any target is OP_RETURN and estimate with a conservative (e.g. 80-byte) default.

---

### M11. `UTXO.outpoint` is a free-form string

**File:** `src/psbt_tool/core/models.py:85-95`.

`"txid:vout"` is by convention. No regex / validator. Becomes a problem once this ever joins with real on-chain data.

**Fix:** add a validator / regex constraint.

---

### M12. JS `inferScriptType` is length-based and doesn't check network

**File:** `static/app.js:35-48`.

```js
if (lower.startsWith("bc1q") || lower.startsWith("tb1q") || lower.startsWith("bcrt1q")) {
  return lower.length <= 45 ? "P2WPKH" : "P2WSH";
}
```

Length-based P2WPKH/P2WSH discrimination is fragile. Also: mainnet `bc1...` accepted when server is testnet → server rejects → bad UX.

**Fix:** use a real bech32 decode or delegate to the backend. At minimum, compare `bc1`/`tb1`/`bcrt1` prefix against the known network.

---

### M13. Float arithmetic for fee math

**File:** `src/psbt_tool/core/coin_sim.py:56-73`.

`fee_with_change = vsize_with_change * fee_rate` in float, then `round()`. `249.4999...` rounds to `249`, yielding an effective rate slightly below the requested `fee_rate`.

**Fix:** `math.ceil` for fees. Same in `fee_no_change`. Consider `Decimal` for sats math.

---

### M14. `tests/test_api.py` uses a module-level monkeypatch

**File:** `tests/test_api.py:11-25`.

Works today because `routes.py` imports `fees_mod.fetch_recommended_fees`. Brittle — a refactor that inlines the import silently breaks the mock, prod hits real mempool.space.

**Fix:** use `httpx.MockTransport` (as `test_fees.py` does). Covers more of the stack.

---

## Low

### L1. No rate limiting anywhere

No `slowapi`, no IP throttle, no request counter. Combined with the in-memory fee cache, a bot can hammer `/api/psbt/analyze`. For a local tool this is accepted; for prod, call out that it would need `slowapi` or a reverse-proxy rate limit.

---

### L2. No structured logging

No `logging` import anywhere. No request ID, no fee-cache hit/miss counter, no editor op audit. When something goes wrong, there's nothing to look at.

**Fix:** add `logging.getLogger(__name__)` at module scope, log at boundaries (analyze success/failure, mempool fetch result, editor ops applied).

---

### L3. `run()` hardcodes host/port/reload

**File:** `src/psbt_tool/api/main.py:64-68`.

No way to run on `0.0.0.0` for docker without bypassing the entrypoint. No port env var.

**Fix:** read `HOST` / `PORT` from env; pass to uvicorn.

---

### L4. Tests can't inject settings

**File:** `src/psbt_tool/config.py:10-41`.

`get_settings()` returns a cached singleton, so `test_api.py` creating a fresh `create_app()` per test still gets whatever `NETWORK` is in the env. Hard to test behavior under `NETWORK=testnet`.

**Fix:** inject `Settings` into `create_app(settings=None)` as an argument, default to `get_settings()`.

---

### L5. `_synthetic_txid` uses `time.time_ns()` — non-deterministic

**File:** `src/psbt_tool/core/editor.py:66-73`.

Already flagged in H4. Non-reproducibility also makes testing painful; current tests for `add_input` never inspect `txid`.

---

### L6. `_to_base64` re-serializes unnecessarily

**File:** `src/psbt_tool/core/parser.py:125-127`, called from `build_report:245`.

Each analyze round-trip is parse → serialize → base64 even when the original bytes are untouched. Functional; slightly wasteful.

---

### L7. Test coverage gaps

**File:** `tests/test_api.py`.

Missing:

- `POST /api/psbt/analyze/upload` with raw bytes (vs base64 text content).
- Same endpoint with a `>MAX_PSBT_BYTES` payload (would reveal H8).
- `GET /api/fees/recommended` direct test.
- `apply` with invalid op name.
- `apply` with negative `value_sats` (would reveal H5).
- `coin-sim/run` with `strategies=["nonsense"]`.
- PSBT v2 parsing (all fixtures are v0).
- P2SH-P2WPKH end-to-end (only unit-tested in `test_scripts.py`).
- Multi-sig P2WSH (vsize estimate `104.5` is hard-coded to 2-of-3).

---

### L8. `scripts/generate_psbt.py` always uses sequence `0xFFFFFFFD` (RBF)

**File:** `scripts/generate_psbt.py:92`.

Users testing non-RBF cannot. Worth a CLI flag.

---

### L9. `_guard_size` re-calls `get_settings()` inside the function

**File:** `src/psbt_tool/api/routes.py:28`.

Negligible cost; routes also call `get_settings()` right after. Minor pattern cleanup.

---

### L10. Module-level `_UPLOAD = File(...)` / `_PSBT_FORM = Form(...)`

**File:** `src/psbt_tool/api/routes.py:71-72`.

Workaround for ruff B008 (don't call functions in default args). Works, but modern FastAPI uses `Annotated[UploadFile, File(...)]` instead, which is clearer.

**Fix:**

```python
from typing import Annotated
async def analyze_upload(file: Annotated[UploadFile, File()]) -> PSBTReport:
```

---

## Nits

| # | File | Note |
|---|---|---|
| N1 | `editor.py:186` | `_ = _network(network)` is dead — remove it or call `_network(network)` explicitly. |
| N2 | `parser.py:25-32`, `editor.py:44-51` | `_NETWORK_KEYS` duplicated; extract to shared module. |
| N3 | `models.py:141-145` | `EditOp.op` is `str` — should be `Literal[...]` or `StrEnum`; Pydantic would then reject unknown ops at the boundary. |
| N4 | `templates/index.html:116` | `<a href="/docs">OpenAPI docs</a>` linked even if FastAPI docs get disabled in prod. |
| N5 | `static/app.js` | Mixes global click delegation with direct `addEventListener` — two paradigms in one file. |
| N6 | `static/app.js:280, 293, 346, 378, 381, 393, 396` | `showError` displays full HTTPException JSON body instead of parsing `detail`. |
| N7 | `pyproject.toml:11` | `license = { text = "MIT" }` but no `LICENSE` file in repo root. |
| N8 | `src/psbt_tool/core/scripts.py:12` | `StrEnum` requires 3.11+; `pyproject.toml` agrees — just keep in mind. |
| N9 | `coin_sim.py:226` | `bootstrap_from_report` params typed as bare `list`; should be `list[InputView]`, `list[OutputView]`. |
| N10 | `README.md:145` vs UI | Claims "raw base64/hex textarea remains as a fallback" for the editor, but the UI has no raw-PSBT editor — only the structured form. Docs drift. |

---

## Quick-win punch list (~30 min)

These move the submission meaningfully forward with minimal surgery:

1. **Escape HTML in `app.js`** (C1) — one `escapeHtml` helper, ~8 replace sites.
2. **Close CORS** (C3) — change `allow_origins=["*"]` to an env-controlled list defaulting to empty.
3. **Validate network** (H2) — whitelist `{mainnet, testnet, signet, regtest}` in `Settings`; raise on unknown.
4. **Add Pydantic constraints** (H5, C2) — `ge=0` on every `value_sats`, `fee_rate_sat_vb`; `max_length=64` on `CoinSimRequest.utxos`.
5. **Narrow route exception handlers** (H7) — replace bare `except Exception` with `(ValueError, binascii.Error, IndexError, httpx.HTTPError)`. Log full traceback server-side.
6. **Warn on synthetic txid** (H4) — append a `PSBTReport.warnings` entry when `add_input` synthesizes a prevout.
7. **Fix BnB fallback labeling** (M4) — set `message="BnB exhausted, fell back to largest_first"` so the UI doesn't claim BnB won.

---

## Testing gaps

Beyond the coverage list in L7, critical scenarios with no tests:

- PSBT v2 round-trip (parser → editor → parser).
- `NETWORK=testnet` or `signet` end-to-end path.
- Editor + cross-network address (would reveal H3).
- Coin-sim `branch_and_bound` with > 20 UTXOs (would reveal C2 in a benchmark).
- Frontend: no JS tests at all.

---

## Functional test results

Manual testing was performed against a fresh clone running on `http://127.0.0.1:8100`.

| # | Scenario | Result |
|---|---|---|
| 1 | `GET /health` | ✅ `{"status":"ok","network":"mainnet"}` |
| 2 | `pytest` | ✅ **37/37 tests pass** |
| 3 | Generate synthetic PSBTs (2/2, 3/4, 1/2) via `scripts/generate_psbt.py` | ✅ All wrote correctly; fee/vsize math checks out |
| 4 | Paste base64 in UI → Analyze (2-in/2-out) | ✅ Report: 202,085 in / 200,000 out / 2,085 fee @ 10 sat/vB / 208.5 vB; "over fastest" mempool badge |
| 5 | Edit output in UI (100,000 → 95,000) + Save | ✅ Live re-analysis; fee jumped to 7,085 sats / 33.98 sat/vB; output 0 flagged "change? 43%" |
| 6 | Coin-selection simulation (bootstrapped from PSBT) | ✅ All 3 strategies ran; `smallest_first` marked "best" |
| 7 | File upload of 3-in/4-out PSBT | ✅ Correctly analyzed; heuristics picked output 0 as highest change candidate (46%) |
| 8 | Raw hex path (`POST /api/psbt/analyze` with `psbt_hex`) | ✅ Works; fee rate 5.00 sat/vB |
| 9 | `POST /api/psbt/apply` with `set_output_value`, `drop_output`, `add_output` | ✅ All three ops work; live re-analysis returns new report |
| 10 | `POST /api/psbt/apply` with `output_index=99` (out of range) | ✅ Clean 400 `"output_index out of range: 99"` |
| 11 | `POST /api/psbt/apply` with `value_sats=999999999999` (negative fee) | ⚠️ Returns **HTTP 200** with `warnings: ["Computed fee is negative; outputs exceed known inputs..."]`. Arguable UX choice; related to H5. |
| 12 | `POST /api/psbt/analyze` with `{}` (no PSBT) | ✅ Clean 400 `"No PSBT provided: expected psbt_base64 or psbt_hex."` |
| 13 | Upload non-PSBT file (README.md) | ✅ Clean 400 `"Invalid PSBT magic"` |
| 14 | `POST /api/psbt/analyze` with malformed base64 | ✅ Clean 400 with base64 decode detail |
| 15 | `POST /api/coin-sim/run` with missing required fields | ✅ Pydantic validation error with per-field `loc` |
| 16 | `GET /api/fees/recommended` | ✅ Returns mempool.space buckets |
| 17 | Browser console after all UI tests | ✅ No JS errors |
| 18 | `GET /docs` (OpenAPI UI) | ✅ 200; all 9 endpoints listed |

Happy-path functionality is solid. Every finding in this review is about **boundaries** — adversarial input, cross-network handling, untrusted rendering, and observability — not about core PSBT logic, which works.
