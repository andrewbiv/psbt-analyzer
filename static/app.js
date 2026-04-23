(() => {
  const state = {
    report: null,
    psbtBase64: null,
    sim: { utxos: [], targets: [] },
  };

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  // --- Tabs ----------------------------------------------------------------
  $$(".tab").forEach((t) => {
    t.addEventListener("click", () => {
      $$(".tab").forEach((x) => x.classList.remove("active"));
      t.classList.add("active");
      $$(".tab-panel").forEach((p) => p.classList.add("hidden"));
      $(`.tab-panel[data-panel="${t.dataset.tab}"]`).classList.remove("hidden");
    });
  });

  // --- Helpers -------------------------------------------------------------
  const showError = (msg) => {
    const box = $("#errorBox");
    box.textContent = msg;
    box.classList.remove("hidden");
  };
  const clearError = () => $("#errorBox").classList.add("hidden");

  const fmtSats = (s) => {
    if (s === null || s === undefined) return "\u2014";
    return Number(s).toLocaleString("en-US") + " sats";
  };
  const fmtRate = (r) => (r === null || r === undefined ? "\u2014" : r.toFixed(2) + " sat/vB");

  const inferScriptType = (addr) => {
    if (!addr) return null;
    const a = addr.trim();
    const lower = a.toLowerCase();
    if (lower.startsWith("bc1p") || lower.startsWith("tb1p") || lower.startsWith("bcrt1p")) return "P2TR";
    if (lower.startsWith("bc1q") || lower.startsWith("tb1q") || lower.startsWith("bcrt1q")) {
      return lower.length <= 45 ? "P2WPKH" : "P2WSH";
    }
    if (lower.startsWith("bc1") || lower.startsWith("tb1") || lower.startsWith("bcrt1")) return "P2WPKH";
    const first = a[0];
    if (first === "1" || first === "m" || first === "n") return "P2PKH";
    if (first === "3" || first === "2") return "P2SH-P2WPKH";
    return null;
  };

  const bucketBadge = (bucket) => {
    const cls = {
      below_min: "bad",
      min: "warn",
      economy: "warn",
      hour: "accent",
      half_hour: "accent",
      fastest: "good",
      over_fastest: "warn",
    }[bucket] || "";
    return `<span class="badge ${cls}">${(bucket || "n/a").replace(/_/g, " ")}</span>`;
  };

  // --- API -----------------------------------------------------------------
  const api = async (path, body) => {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${res.status}: ${text}`);
    }
    return res.json();
  };

  // --- Render --------------------------------------------------------------
  const parseMixSide = (note, label) => {
    const m = new RegExp(`${label}:\\s*([^;]*)`, "i").exec(note || "");
    if (!m) return "\u2014";
    const body = m[1].trim();
    if (!body || body === "\u2014") return "\u2014";
    return body
      .split(",")
      .map((p) => p.trim())
      .filter(Boolean)
      .map((p) => `<span class="badge">${p}</span>`)
      .join(" ");
  };

  const renderSummary = (r) => {
    const f = r.fees;
    const cmp = r.fee_comparison || {};
    const inMix = parseMixSide(r.script_mix_note, "inputs");
    const outMix = parseMixSide(r.script_mix_note, "outputs");
    const html = `
      <div class="summary-grid">
        <div class="summary-cell"><div class="label">PSBT version</div><div class="value">v${r.psbt_version}</div></div>
        <div class="summary-cell"><div class="label">Network</div><div class="value">${r.network}</div></div>
        <div class="summary-cell"><div class="label">Total in</div><div class="value">${fmtSats(f.total_in_sats)}</div></div>
        <div class="summary-cell"><div class="label">Total out</div><div class="value">${fmtSats(f.total_out_sats)}</div></div>
        <div class="summary-cell"><div class="label">Fee</div><div class="value">${fmtSats(f.fee_sats)}</div></div>
        <div class="summary-cell"><div class="label">Fee rate</div><div class="value">${fmtRate(f.fee_rate_sat_vb)}</div></div>
        <div class="summary-cell"><div class="label">Vsize</div><div class="value">${f.vsize.toFixed(1)} vB</div></div>
        <div class="summary-cell"><div class="label">Weight</div><div class="value">${f.weight} WU</div></div>
        <div class="summary-cell"><div class="label">Mempool bucket</div><div class="value">${bucketBadge(cmp.bucket)}</div></div>
        <div class="summary-cell"><div class="label">Inputs mix</div><div class="value">${inMix}</div></div>
        <div class="summary-cell"><div class="label">Outputs mix</div><div class="value">${outMix}</div></div>
      </div>
      ${(r.warnings || []).length ? `<p class="muted" style="margin-top:10px">\u26a0\ufe0f ${r.warnings.join(" \u00b7 ")}</p>` : ""}
    `;
    $("#summary").innerHTML = html;
  };

  const renderInputs = (inputs) => {
    const rows = inputs
      .map(
        (i) => `
        <tr>
          <td>${i.index}</td>
          <td><span class="badge accent">${i.script_type}</span></td>
          <td class="mono">${i.address || "\u2014"}</td>
          <td class="numeric">${
            i.value_sats != null
              ? `<input type="number" min="0" step="1" value="${i.value_sats}" data-in-value="${i.index}" />`
              : "\u2014"
          }</td>
          <td class="numeric">${i.vsize.toFixed(1)}</td>
          <td>
            ${
              i.value_sats != null
                ? `<button type="button" data-save-input="${i.index}">Save</button>`
                : ""
            }
            <button type="button" class="danger" data-drop-input="${i.index}">Remove</button>
          </td>
        </tr>`
      )
      .join("");
    $("#inputsTable").innerHTML = `
      <thead><tr>
        <th>#</th><th>Type</th><th>Address</th>
        <th class="numeric">Value (sats)</th><th class="numeric">vsize</th><th>Actions</th>
      </tr></thead><tbody>${rows}</tbody>
    `;
  };

  const renderOutputs = (outputs) => {
    const rows = outputs
      .map(
        (o) => `
        <tr>
          <td>${o.index}</td>
          <td><span class="badge accent">${o.script_type}</span></td>
          <td class="mono">${o.address || "\u2014"}</td>
          <td class="numeric"><input type="number" min="0" step="1" value="${o.value_sats}" data-out-value="${o.index}" /></td>
          <td>${o.is_change_candidate ? `<span class="badge good">change? ${(o.change_confidence * 100).toFixed(0)}%</span>` : ""}
              ${(o.change_reasons || []).map((r) => `<span class="reason-pill">${r}</span>`).join("")}
          </td>
          <td>
            <button type="button" data-save-output="${o.index}">Save</button>
            <button type="button" class="danger" data-drop-output="${o.index}">Remove</button>
          </td>
        </tr>`
      )
      .join("");
    $("#outputsTable").innerHTML = `
      <thead><tr>
        <th>#</th><th>Type</th><th>Address</th>
        <th class="numeric">Value (sats)</th><th>Heuristic</th><th>Actions</th>
      </tr></thead><tbody>${rows}</tbody>
    `;
  };

  const renderFees = (r) => {
    const f = r.fees;
    const cmp = r.fee_comparison || {};
    const rec = cmp.recommended || {};
    const cells = [
      ["Effective", fmtRate(f.fee_rate_sat_vb)],
      ["Minimum", rec.minimumFee ? rec.minimumFee + " sat/vB" : "\u2014"],
      ["Economy", rec.economyFee ? rec.economyFee + " sat/vB" : "\u2014"],
      ["~1 hour", rec.hourFee ? rec.hourFee + " sat/vB" : "\u2014"],
      ["~30 min", rec.halfHourFee ? rec.halfHourFee + " sat/vB" : "\u2014"],
      ["Next block", rec.fastestFee ? rec.fastestFee + " sat/vB" : "\u2014"],
    ];
    const noteCell = cmp.note
      ? `<div class="summary-cell full"><div class="label">Fee reasonableness</div><div class="value">${cmp.note}</div></div>`
      : "";
    $("#feesBlock").innerHTML =
      cells
        .map(
          ([l, v]) =>
            `<div class="summary-cell"><div class="label">${l}</div><div class="value">${v}</div></div>`
        )
        .join("") + noteCell;
  };

  const renderSimUtxos = () => {
    const rows = state.sim.utxos
      .map(
        (u, i) => `
        <tr>
          <td>${u.index != null ? u.index : i}</td>
          <td><span class="badge accent">${u.script_type}</span></td>
          <td class="mono">${u.address || ""}</td>
          <td class="numeric"><input type="number" min="0" step="1" value="${u.value_sats}" data-utxo-value="${i}" /></td>
          <td><button class="danger" data-drop-utxo="${i}">Remove</button></td>
        </tr>`
      )
      .join("");
    $("#simUtxos").innerHTML = `
      <thead><tr><th>#</th><th>Type</th><th>Address</th><th class="numeric">Value (sats)</th><th>Actions</th></tr></thead>
      <tbody>${rows}</tbody>
    `;
  };

  const renderSimTargets = () => {
    const rows = state.sim.targets
      .map(
        (t, i) => `
        <tr>
          <td>${t.index != null ? t.index : i}</td>
          <td><span class="badge accent">${t.script_type}</span></td>
          <td class="mono">${t.address || ""}</td>
          <td class="numeric"><input type="number" min="0" step="1" value="${t.value_sats}" data-target-value="${i}" /></td>
          <td><button type="button" class="danger" data-drop-target="${i}">Remove</button></td>
        </tr>`
      )
      .join("");
    $("#simTargets").innerHTML = `
      <thead><tr><th>#</th><th>Type</th><th>Address</th><th class="numeric">Value (sats)</th><th>Actions</th></tr></thead>
      <tbody>${rows}</tbody>
    `;
  };

  const renderSimResults = (res) => {
    const rows = res.results
      .map((r) => {
        const best = r.strategy === res.best_strategy && r.ok ? " best" : "";
        if (!r.ok) {
          return `<tr class="strategy-row"><td>${r.strategy}</td><td colspan="5"><span class="badge bad">${r.message || "failed"}</span></td></tr>`;
        }
        return `<tr class="strategy-row${best}">
          <td>${r.strategy}</td>
          <td class="numeric">${r.num_inputs}</td>
          <td class="numeric">${fmtSats(r.fee_sats)}</td>
          <td class="numeric">${fmtRate(r.fee_rate_sat_vb)}</td>
          <td class="numeric">${fmtSats(r.change_sats)}</td>
          <td class="numeric">${r.vsize.toFixed(1)} vB</td>
        </tr>`;
      })
      .join("");
    $("#simResults").innerHTML = `
      <div class="table-wrap"><table>
        <thead><tr>
          <th>Strategy</th><th class="numeric"># inputs</th><th class="numeric">Fee</th>
          <th class="numeric">Fee rate</th><th class="numeric">Change</th><th class="numeric">vsize</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
    `;
  };

  // --- Analyze flows -------------------------------------------------------
  const renderAll = (r) => {
    state.report = r;
    state.psbtBase64 = r.psbt_base64;
    $("#reportSection").classList.remove("hidden");
    renderSummary(r);
    renderInputs(r.inputs);
    renderOutputs(r.outputs);
    renderFees(r);
    bootstrapSim(r.psbt_base64);
  };

  const analyzeText = async () => {
    clearError();
    const text = $("#psbtText").value.trim();
    if (!text) return showError("Please paste a PSBT.");
    const isHex = /^[0-9a-fA-F]+$/.test(text) && text.length % 2 === 0;
    try {
      const r = await api("/api/psbt/analyze", isHex ? { psbt_hex: text } : { psbt_base64: text });
      renderAll(r);
    } catch (e) {
      showError(e.message);
    }
  };

  const analyzeFile = async () => {
    clearError();
    const f = $("#psbtFile").files[0];
    if (!f) return showError("Choose a file first.");
    const form = new FormData();
    form.append("file", f);
    try {
      const res = await fetch("/api/psbt/analyze/upload", { method: "POST", body: form });
      if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
      renderAll(await res.json());
    } catch (e) {
      showError(e.message);
    }
  };

  $("#analyzeBtn").addEventListener("click", analyzeText);
  $("#analyzeFileBtn").addEventListener("click", analyzeFile);

  // --- Edit ops ------------------------------------------------------------
  const applyOps = async (ops) => {
    clearError();
    try {
      const r = await api("/api/psbt/apply", { psbt_base64: state.psbtBase64, ops });
      $("#editNotes").textContent = r.notes.join(" \u00b7 ");
      renderAll(r.report);
    } catch (e) {
      showError(e.message);
    }
  };

  document.addEventListener("click", (ev) => {
    const dropIn = ev.target.getAttribute?.("data-drop-input");
    if (dropIn !== null && dropIn !== undefined) {
      applyOps([{ op: "drop_input", input_index: Number(dropIn) }]);
      return;
    }
    const dropOut = ev.target.getAttribute?.("data-drop-output");
    if (dropOut !== null && dropOut !== undefined) {
      applyOps([{ op: "drop_output", output_index: Number(dropOut) }]);
      return;
    }
    const saveOut = ev.target.getAttribute?.("data-save-output");
    if (saveOut !== null && saveOut !== undefined) {
      const input = document.querySelector(`input[data-out-value="${saveOut}"]`);
      applyOps([{ op: "set_output_value", output_index: Number(saveOut), value_sats: Number(input.value) }]);
      return;
    }
    const saveIn = ev.target.getAttribute?.("data-save-input");
    if (saveIn !== null && saveIn !== undefined) {
      const input = document.querySelector(`input[data-in-value="${saveIn}"]`);
      applyOps([{ op: "set_input_value", input_index: Number(saveIn), value_sats: Number(input.value) }]);
      return;
    }
    if (ev.target.id === "addOutBtn") {
      const addr = $("#addOutAddr").value.trim();
      const v = Number($("#addOutValue").value);
      if (!addr || !v) return showError("Address and value required.");
      applyOps([{ op: "add_output", address: addr, value_sats: v }]);
      $("#addOutAddr").value = "";
      $("#addOutValue").value = "";
    }
    if (ev.target.id === "addInBtn") {
      const addr = $("#addInAddr").value.trim();
      const v = Number($("#addInValue").value);
      if (!addr || !v) return showError("Address and value required.");
      applyOps([{ op: "add_input", address: addr, value_sats: v }]);
      $("#addInAddr").value = "";
      $("#addInValue").value = "";
    }
  });

  // --- Sim -----------------------------------------------------------------
  const bootstrapSim = async (psbtBase64) => {
    try {
      const req = await api("/api/coin-sim/bootstrap", { psbt_base64: psbtBase64 });
      state.sim.utxos = req.utxos;
      state.sim.targets = req.targets;
      renderSimUtxos();
      renderSimTargets();
    } catch (e) {
      // Non-fatal
      console.warn("Sim bootstrap failed:", e);
    }
  };

  $("#addUtxoBtn").addEventListener("click", () => {
    const address = $("#addUtxoAddress").value.trim();
    const value = Number($("#addUtxoValue").value);
    if (!address) return showError("UTXO address required.");
    if (!value || value < 0) return showError("UTXO value required.");
    const script_type = inferScriptType(address);
    if (!script_type) return showError(`Unable to infer script type from address: ${address}`);
    clearError();
    const outpoint = `manual:${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
    state.sim.utxos.push({ outpoint, value_sats: value, script_type, address });
    $("#addUtxoAddress").value = "";
    $("#addUtxoValue").value = "";
    renderSimUtxos();
  });

  $("#addTargetBtn").addEventListener("click", () => {
    const address = $("#addTargetAddress").value.trim();
    const value = Number($("#addTargetValue").value);
    if (!address) return showError("Target address required.");
    if (!value || value < 0) return showError("Target value required.");
    const script_type = inferScriptType(address);
    if (!script_type) return showError(`Unable to infer script type from address: ${address}`);
    clearError();
    state.sim.targets.push({ script_type, value_sats: value, address });
    $("#addTargetAddress").value = "";
    $("#addTargetValue").value = "";
    renderSimTargets();
  });

  document.addEventListener("click", (ev) => {
    const idx = ev.target.getAttribute?.("data-drop-utxo");
    if (idx !== null && idx !== undefined) {
      state.sim.utxos.splice(Number(idx), 1);
      renderSimUtxos();
      return;
    }
    const tidx = ev.target.getAttribute?.("data-drop-target");
    if (tidx !== null && tidx !== undefined) {
      state.sim.targets.splice(Number(tidx), 1);
      renderSimTargets();
    }
  });

  document.addEventListener("input", (ev) => {
    const tidx = ev.target.getAttribute?.("data-target-value");
    if (tidx !== null && tidx !== undefined) {
      state.sim.targets[Number(tidx)].value_sats = Number(ev.target.value);
      return;
    }
    const uidx = ev.target.getAttribute?.("data-utxo-value");
    if (uidx !== null && uidx !== undefined) {
      state.sim.utxos[Number(uidx)].value_sats = Number(ev.target.value);
    }
  });

  $("#simRunBtn").addEventListener("click", async () => {
    clearError();
    try {
      const body = {
        utxos: state.sim.utxos,
        targets: state.sim.targets,
        change_script_type: $("#simChangeType").value,
        fee_rate_sat_vb: Number($("#simFeeRate").value),
      };
      const res = await api("/api/coin-sim/run", body);
      renderSimResults(res);
    } catch (e) {
      showError(e.message);
    }
  });

  renderSimUtxos();
  renderSimTargets();
})();
