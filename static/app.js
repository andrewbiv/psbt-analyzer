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
  const renderSummary = (r) => {
    const f = r.fees;
    const cmp = r.fee_comparison || {};
    const feeCompText = cmp.note ? cmp.note : "";
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
      </div>
      <p class="muted" style="margin-top:10px">${r.script_mix_note}</p>
      ${feeCompText ? `<p class="muted">${feeCompText}</p>` : ""}
      ${(r.warnings || []).length ? `<p class="muted">\u26a0\ufe0f ${r.warnings.join(" \u00b7 ")}</p>` : ""}
    `;
    $("#summary").innerHTML = html;
  };

  const renderInputs = (inputs) => {
    const rows = inputs
      .map(
        (i) => `
        <tr>
          <td>${i.index}</td>
          <td class="mono">${i.txid}:${i.vout}</td>
          <td><span class="badge accent">${i.script_type}</span></td>
          <td class="mono">${i.address || "\u2014"}</td>
          <td class="numeric">${fmtSats(i.value_sats)}</td>
          <td class="numeric">${i.vsize.toFixed(1)}</td>
          <td>${i.partial_sigs ? `<span class="badge good">${i.partial_sigs} sig</span>` : ""}${i.final_scriptwitness || i.final_scriptsig ? ' <span class="badge good">final</span>' : ""}</td>
        </tr>`
      )
      .join("");
    $("#inputsTable").innerHTML = `
      <thead><tr>
        <th>#</th><th>Outpoint</th><th>Type</th><th>Address</th>
        <th class="numeric">Value</th><th class="numeric">vsize</th><th>Status</th>
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
          <td class="numeric">${fmtSats(o.value_sats)}</td>
          <td>${o.is_change_candidate ? `<span class="badge good">change? ${(o.change_confidence * 100).toFixed(0)}%</span>` : ""}
              ${(o.change_reasons || []).map((r) => `<span class="reason-pill">${r}</span>`).join("")}
          </td>
        </tr>`
      )
      .join("");
    $("#outputsTable").innerHTML = `
      <thead><tr>
        <th>#</th><th>Type</th><th>Address</th>
        <th class="numeric">Value</th><th>Heuristic</th>
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
    $("#feesBlock").innerHTML = cells
      .map(
        ([l, v]) =>
          `<div class="summary-cell"><div class="label">${l}</div><div class="value">${v}</div></div>`
      )
      .join("");
  };

  const renderEditControls = (r) => {
    const inputs = r.inputs
      .map(
        (i) => `<div class="edit-add-row">
          <span class="badge">Input #${i.index}</span>
          <span class="mono">${i.txid.slice(0, 10)}\u2026:${i.vout}</span>
          <span>${fmtSats(i.value_sats)}</span>
          <button class="danger" data-drop-input="${i.index}">Drop</button>
        </div>`
      )
      .join("");
    const outputs = r.outputs
      .map(
        (o) => `<div class="edit-add-row">
          <span class="badge">Output #${o.index}</span>
          <span>${o.script_type}</span>
          <input type="number" min="0" step="1" value="${o.value_sats}" data-out-value="${o.index}" />
          <button data-save-output="${o.index}">Save value</button>
          <button class="danger" data-drop-output="${o.index}">Drop</button>
        </div>`
      )
      .join("");
    $("#editControls").innerHTML = `${inputs}${outputs}`;
    $("#rawEdit").value = r.psbt_base64;
  };

  const renderSimUtxos = () => {
    const rows = state.sim.utxos
      .map(
        (u, i) => `
        <tr>
          <td class="mono">${u.outpoint}</td>
          <td><span class="badge accent">${u.script_type}</span></td>
          <td class="mono">${u.address || ""}</td>
          <td class="numeric">${fmtSats(u.value_sats)}</td>
          <td><button class="danger" data-drop-utxo="${i}">Remove</button></td>
        </tr>`
      )
      .join("");
    $("#simUtxos").innerHTML = `
      <thead><tr><th>Outpoint</th><th>Type</th><th>Address</th><th class="numeric">Value</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    `;
  };

  const renderSimTargets = () => {
    const rows = state.sim.targets
      .map(
        (t, i) => `
        <tr>
          <td class="mono">${t.address || ""}</td>
          <td><span class="badge accent">${t.script_type}</span></td>
          <td class="numeric"><input type="number" min="0" step="1" value="${t.value_sats}" data-target-value="${i}" /></td>
        </tr>`
      )
      .join("");
    $("#simTargets").innerHTML = `
      <thead><tr><th>Address</th><th>Type</th><th class="numeric">Value (sats)</th></tr></thead>
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
    renderEditControls(r);
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
    if (ev.target.id === "addOutBtn") {
      const addr = $("#addOutAddr").value.trim();
      const v = Number($("#addOutValue").value);
      if (!addr || !v) return showError("Address and value required.");
      applyOps([{ op: "add_output", address: addr, value_sats: v }]);
    }
    if (ev.target.id === "rawReanalyzeBtn") {
      const val = $("#rawEdit").value.trim();
      $("#psbtText").value = val;
      analyzeText();
    }
  });

  // --- Sim -----------------------------------------------------------------
  const bootstrapSim = async (psbtBase64) => {
    try {
      const req = await api("/api/coin-sim/bootstrap", { psbt_base64: psbtBase64 });
      state.sim.utxos = req.utxos;
      state.sim.targets = req.targets;
      $("#simSection").classList.remove("hidden");
      renderSimUtxos();
      renderSimTargets();
    } catch (e) {
      // Non-fatal
      console.warn("Sim bootstrap failed:", e);
    }
  };

  $("#addUtxoBtn").addEventListener("click", () => {
    const outpoint = $("#addUtxoOutpoint").value.trim();
    const value = Number($("#addUtxoValue").value);
    const script_type = $("#addUtxoType").value;
    if (!outpoint || !value) return;
    state.sim.utxos.push({ outpoint, value_sats: value, script_type });
    $("#addUtxoOutpoint").value = "";
    $("#addUtxoValue").value = "";
    renderSimUtxos();
  });

  document.addEventListener("click", (ev) => {
    const idx = ev.target.getAttribute?.("data-drop-utxo");
    if (idx !== null && idx !== undefined) {
      state.sim.utxos.splice(Number(idx), 1);
      renderSimUtxos();
    }
  });

  document.addEventListener("input", (ev) => {
    const idx = ev.target.getAttribute?.("data-target-value");
    if (idx !== null && idx !== undefined) {
      state.sim.targets[Number(idx)].value_sats = Number(ev.target.value);
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
})();
