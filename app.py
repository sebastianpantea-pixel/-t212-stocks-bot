<!DOCTYPE html>
<html lang="ro">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>T212 Stocks Bot</title>
  <style>
    :root{
      --bg:#090d14;
      --panel:#121826;
      --panel-2:#171f31;
      --line:#283148;
      --text:#dbe6ff;
      --muted:#8d9ab6;
      --green:#22c55e;
      --red:#ef4444;
      --amber:#f59e0b;
      --blue:#60a5fa;
      --cyan:#22d3ee;
      --violet:#8b5cf6;
      --card-radius:18px;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      background: linear-gradient(180deg, #0a0f17 0%, #08101a 100%);
      color: var(--text);
    }

    .wrap {
      max-width: 1600px;
      margin: 0 auto;
      padding: 24px;
    }

    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 22px;
      flex-wrap: wrap;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 14px;
      font-weight: 700;
      letter-spacing: .04em;
    }

    .pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 14px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255,255,255,.03);
      color: var(--muted);
      font-size: 13px;
    }

    .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--muted);
    }

    .dot.green { background: var(--green); }
    .dot.red { background: var(--red); }
    .dot.amber { background: var(--amber); }

    .grid {
      display: grid;
      grid-template-columns: 330px 1fr;
      gap: 20px;
    }

    .panel {
      background: linear-gradient(180deg, rgba(22,29,46,.95), rgba(18,24,38,.98));
      border: 1px solid var(--line);
      border-radius: var(--card-radius);
      padding: 18px;
      box-shadow: 0 10px 30px rgba(0,0,0,.18);
    }

    .sidebar h3,
    .section-title {
      margin: 0 0 14px;
      color: var(--muted);
      font-size: 13px;
      letter-spacing: .08em;
      text-transform: uppercase;
    }

    .stats {
      display: grid;
      grid-template-columns: repeat(4, minmax(0,1fr));
      gap: 16px;
      margin-bottom: 20px;
    }

    .stat {
      background: rgba(255,255,255,.02);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
      min-height: 118px;
    }

    .stat .label {
      color: var(--muted);
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: .07em;
      margin-bottom: 8px;
    }

    .stat .value {
      font-size: 22px;
      font-weight: 800;
      margin-bottom: 6px;
    }

    .stat .sub {
      color: var(--muted);
      font-size: 13px;
    }

    .green { color: var(--green); }
    .red { color: var(--red); }
    .amber { color: var(--amber); }
    .blue { color: var(--blue); }

    .symbols-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;
      margin-bottom: 18px;
    }

    .symbol-chip {
      border: 1px solid #4d5ec9;
      color: #9fb0ff;
      background: rgba(105,126,255,.08);
      border-radius: 12px;
      padding: 12px 10px;
      text-align: center;
      font-weight: 700;
      font-size: 14px;
    }

    .field {
      margin-bottom: 14px;
    }

    .field label {
      display: block;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: .05em;
    }

    .field input,
    .field textarea {
      width: 100%;
      border: 1px solid var(--line);
      background: #0c1321;
      color: var(--text);
      border-radius: 12px;
      padding: 12px 14px;
      outline: none;
      font-size: 14px;
    }

    .field textarea {
      min-height: 88px;
      resize: vertical;
    }

    .btns {
      display: flex;
      gap: 10px;
      margin-top: 12px;
      flex-wrap: wrap;
    }

    button {
      border: 0;
      border-radius: 12px;
      padding: 12px 16px;
      font-weight: 700;
      cursor: pointer;
      color: white;
    }

    .btn-start { background: var(--green); }
    .btn-stop { background: var(--red); }
    .btn-save { background: var(--blue); }

    .main-grid {
      display: grid;
      grid-template-columns: 1.1fr .9fr;
      gap: 20px;
      margin-bottom: 20px;
    }

    .chart-placeholder {
      height: 280px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background:
        linear-gradient(to bottom, rgba(255,255,255,.02), rgba(255,255,255,.01)),
        repeating-linear-gradient(
          to bottom,
          transparent 0,
          transparent 34px,
          rgba(255,255,255,.04) 35px
        );
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--muted);
      font-size: 14px;
    }

    .log-box {
      height: 280px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #0a101b;
      padding: 12px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
      line-height: 1.55;
    }

    .log-row {
      padding: 4px 0;
      border-bottom: 1px solid rgba(255,255,255,.03);
      word-break: break-word;
    }

    .log-time {
      color: #90a4d4;
      margin-right: 8px;
    }

    .log-info { color: var(--blue); }
    .log-warn { color: var(--amber); }
    .log-err  { color: var(--red); }
    .log-ok   { color: var(--green); }

    .tables {
      display: grid;
      grid-template-columns: 1fr;
      gap: 20px;
    }

    .table-wrap {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #0b1220;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 900px;
    }

    th, td {
      padding: 12px 14px;
      border-bottom: 1px solid rgba(255,255,255,.05);
      text-align: left;
      font-size: 14px;
    }

    th {
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: .06em;
      font-size: 12px;
      background: rgba(255,255,255,.02);
    }

    .small {
      font-size: 12px;
      color: var(--muted);
    }

    .top-right {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }

    .muted { color: var(--muted); }

    @media (max-width: 1180px) {
      .grid {
        grid-template-columns: 1fr;
      }
      .stats {
        grid-template-columns: repeat(2, minmax(0,1fr));
      }
      .main-grid {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 720px) {
      .stats {
        grid-template-columns: 1fr;
      }
      .symbols-grid {
        grid-template-columns: repeat(2, 1fr);
      }
      .wrap {
        padding: 14px;
      }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <div class="brand">
        <div style="font-size:22px;">T212/STOCKS/BOT</div>
        <div id="statusPill" class="pill">
          <span id="statusDot" class="dot red"></span>
          <span id="statusText">Oprit</span>
        </div>
        <div id="demoPill" class="pill">PAPER</div>
        <div id="marketPill" class="pill">
          <span id="marketDot" class="dot amber"></span>
          <span id="marketText">Market Unknown</span>
        </div>
        <div id="regimePill" class="pill">Regim: unknown</div>
      </div>

      <div class="top-right">
        <div class="pill">Scan: <span id="scanCount" style="margin-left:6px;">0</span></div>
        <div class="pill">Last scan: <span id="lastScan" style="margin-left:6px;">—</span></div>
      </div>
    </div>

    <div class="grid">
      <div class="sidebar panel">
        <h3>Simboluri active</h3>
        <div id="symbolsGrid" class="symbols-grid"></div>

        <div class="field">
          <label>Simboluri, separate prin virgula</label>
          <textarea id="symbolsInput">AAPL,NVDA,MSFT,SPY,QQQ,TSLA,AMZN,META,GOOGL,JPM</textarea>
        </div>

        <div class="field">
          <label>Risc per trade (%)</label>
          <input id="riskPct" type="number" step="0.1" min="0.1" value="1" />
        </div>

        <div class="field">
          <label>SL % de la entry</label>
          <input id="slPct" type="number" step="0.1" min="0.1" value="1.5" />
        </div>

        <div class="field">
          <label>RR ratio (1:X)</label>
          <input id="rrRatio" type="number" step="0.1" min="0.5" value="3" />
        </div>

        <div class="field">
          <label>Drawdown max (%)</label>
          <input id="ddLimit" type="number" step="0.1" min="0.5" value="5" />
        </div>

        <div class="field">
          <label>Max pozitii simultan</label>
          <input id="maxPositions" type="number" step="1" min="1" value="3" />
        </div>

        <div class="field">
          <label>Scan interval (sec)</label>
          <input id="scanInterval" type="number" step="1" min="5" value="300" />
        </div>

        <div class="btns">
          <button class="btn-save" onclick="saveSettings()">Salveaza setari</button>
          <button class="btn-start" onclick="startBot()">Start bot</button>
          <button class="btn-stop" onclick="stopBot()">Stop bot</button>
        </div>
      </div>

      <div>
        <div class="stats">
          <div class="stat">
            <div class="label">Balanta T212</div>
            <div class="value" id="balanceVal">$0.00</div>
            <div class="sub" id="demoText">Paper USD</div>
          </div>

          <div class="stat">
            <div class="label">P&L realizat</div>
            <div class="value" id="pnlVal">$0.00</div>
            <div class="sub" id="pnlPctVal">0.00%</div>
          </div>

          <div class="stat">
            <div class="label">P&L live</div>
            <div class="value" id="livePnlVal">$0.00</div>
            <div class="sub"><span id="activePosCount">0</span> pozitii active</div>
          </div>

          <div class="stat">
            <div class="label">Win rate</div>
            <div class="value" id="winRateVal">0%</div>
            <div class="sub"><span id="winsVal">0</span>W / <span id="lossesVal">0</span>L</div>
          </div>
        </div>

        <div class="main-grid">
          <div class="panel">
            <div class="section-title">P&L cumulativ</div>
            <div class="chart-placeholder">
              Grafic placeholder. Daca vrei, dupa asta iti fac si chart real din history.
            </div>
          </div>

          <div class="panel">
            <div class="section-title">Log bot</div>
            <div id="logBox" class="log-box"></div>
          </div>
        </div>

        <div class="tables">
          <div class="panel">
            <div class="section-title">Pozitii deschise / inchise</div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Simbol</th>
                    <th>Dir</th>
                    <th>Entry</th>
                    <th>Mark</th>
                    <th>SL</th>
                    <th>TP</th>
                    <th>Shares</th>
                    <th>P&L Live</th>
                    <th>Status</th>
                    <th>Motiv</th>
                    <th>Open Time</th>
                  </tr>
                </thead>
                <tbody id="positionsBody"></tbody>
              </table>
            </div>
          </div>

          <div class="panel">
            <div class="section-title">Trade history</div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Simbol</th>
                    <th>Dir</th>
                    <th>Entry</th>
                    <th>Exit</th>
                    <th>Shares</th>
                    <th>P&L</th>
                    <th>RR</th>
                    <th>Motiv</th>
                  </tr>
                </thead>
                <tbody id="historyBody"></tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script>
    const el = id => document.getElementById(id);

    function fmtMoney(v) {
      const n = Number(v || 0);
      const sign = n > 0 ? "+" : "";
      return `${sign}$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }

    function fmtNum(v, d = 2) {
      const n = Number(v || 0);
      return n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
    }

    function setText(id, value) {
      const node = el(id);
      if (node) node.textContent = value;
    }

    function setMoney(id, value) {
      const node = el(id);
      if (!node) return;
      node.textContent = fmtMoney(value);
      node.classList.remove("green", "red", "amber");
      const n = Number(value || 0);
      if (n > 0) node.classList.add("green");
      else if (n < 0) node.classList.add("red");
    }

    function renderSymbols(symbols) {
      const grid = el("symbolsGrid");
      grid.innerHTML = "";
      (symbols || []).forEach(sym => {
        const div = document.createElement("div");
        div.className = "symbol-chip";
        div.textContent = sym;
        grid.appendChild(div);
      });
    }

    function renderLog(logs) {
      const box = el("logBox");
      box.innerHTML = "";
      (logs || []).forEach(row => {
        const div = document.createElement("div");
        div.className = `log-row log-${row.level || "info"}`;
        div.innerHTML = `<span class="log-time">${row.time}</span>${escapeHtml(row.msg || "")}`;
        box.appendChild(div);
      });
    }

    function renderPositions(rows) {
      const body = el("positionsBody");
      body.innerHTML = "";

      if (!rows || rows.length === 0) {
        body.innerHTML = `<tr><td colspan="11" class="muted">Nu exista pozitii.</td></tr>`;
        return;
      }

      rows.forEach(p => {
        const tr = document.createElement("tr");
        const pnl = Number(p.pnl_live || 0);
        const pnlClass = pnl > 0 ? "green" : pnl < 0 ? "red" : "";
        const dirClass = p.direction === "LONG" ? "green" : "red";

        tr.innerHTML = `
          <td>${escapeHtml(p.symbol || "")}</td>
          <td class="${dirClass}">${escapeHtml(p.direction || "")}</td>
          <td>${fmtNum(p.entry, 4)}</td>
          <td>${fmtNum(p.mark_price, 4)}</td>
          <td>${fmtNum(p.sl, 4)}</td>
          <td>${fmtNum(p.tp, 4)}</td>
          <td>${fmtNum(p.shares, 2)}</td>
          <td class="${pnlClass}">${fmtMoney(pnl)}</td>
          <td>${escapeHtml(p.status || "")}</td>
          <td>${escapeHtml(p.reason || "")}</td>
          <td>${escapeHtml(p.open_time || "-")}</td>
        `;
        body.appendChild(tr);
      });
    }

    function renderHistory(rows) {
      const body = el("historyBody");
      body.innerHTML = "";

      if (!rows || rows.length === 0) {
        body.innerHTML = `<tr><td colspan="9" class="muted">Nu exista istoric.</td></tr>`;
        return;
      }

      rows.forEach(p => {
        const tr = document.createElement("tr");
        const pnl = Number(p.pnl || 0);
        const pnlClass = pnl > 0 ? "green" : pnl < 0 ? "red" : "";
        const dirClass = p.dir === "LONG" ? "green" : "red";

        tr.innerHTML = `
          <td>${escapeHtml(p.date || "")}</td>
          <td>${escapeHtml(p.symbol || "")}</td>
          <td class="${dirClass}">${escapeHtml(p.dir || "")}</td>
          <td>${fmtNum(p.entry, 4)}</td>
          <td>${fmtNum(p.exit, 4)}</td>
          <td>${fmtNum(p.shares, 2)}</td>
          <td class="${pnlClass}">${fmtMoney(pnl)}</td>
          <td>${escapeHtml(p.rr || "")}</td>
          <td>${escapeHtml(p.reason || "")}</td>
        `;
        body.appendChild(tr);
      });
    }

    function escapeHtml(str) {
      return String(str)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    async function fetchJSON(url, options = {}) {
      const res = await fetch(url, options);
      return await res.json();
    }

    async function refreshStatus() {
      try {
        const s = await fetchJSON("/api/status");

        setMoney("balanceVal", s.balance);
        setMoney("pnlVal", s.pnl);
        setMoney("livePnlVal", s.live_pnl);
        setText("pnlPctVal", `${fmtNum(s.pnl_pct, 2)}%`);
        setText("activePosCount", s.active_positions || 0);
        setText("winRateVal", `${fmtNum(s.win_rate, 1)}%`);
        setText("winsVal", s.wins || 0);
        setText("lossesVal", s.losses || 0);
        setText("scanCount", s.scan_count || 0);
        setText("lastScan", s.last_scan || "—");
        setText("demoText", s.demo ? "Paper USD" : "Live USD");

        const running = !!s.running;
        el("statusText").textContent = running ? "Activ" : "Oprit";
        el("statusDot").className = `dot ${running ? "green" : "red"}`;

        const market = String(s.market || "unknown").toLowerCase();
        let marketColor = "amber";
        if (market === "open") marketColor = "green";
        if (market === "closed" || market === "weekend") marketColor = "red";

        el("marketDot").className = `dot ${marketColor}`;
        el("marketText").textContent = market.toUpperCase();

        el("regimePill").textContent = `Regim: ${s.regime || "unknown"}`;

        if (s.settings) {
          const symbols = s.settings.symbols || [];
          renderSymbols(symbols);
          el("symbolsInput").value = symbols.join(", ");
          el("riskPct").value = s.settings.risk_pct ?? 1;
          el("slPct").value = s.settings.sl_pct ?? 1.5;
          el("rrRatio").value = s.settings.rr_ratio ?? 3;
          el("ddLimit").value = s.settings.dd_limit ?? 5;
          el("maxPositions").value = s.settings.max_positions ?? 3;
          el("scanInterval").value = s.settings.scan_interval ?? 300;
        }
      } catch (e) {
        console.error("Status error", e);
      }
    }

    async function refreshPositions() {
      try {
        const rows = await fetchJSON("/api/positions");
        renderPositions(rows);
      } catch (e) {
        console.error("Positions error", e);
      }
    }

    async function refreshHistory() {
      try {
        const rows = await fetchJSON("/api/history");
        renderHistory(rows);
      } catch (e) {
        console.error("History error", e);
      }
    }

    async function refreshLog() {
      try {
        const logs = await fetchJSON("/api/log");
        renderLog(logs);
      } catch (e) {
        console.error("Log error", e);
      }
    }

    async function startBot() {
      try {
        const data = await fetchJSON("/api/start", { method: "POST" });
        if (!data.ok) alert(data.msg || "Nu am putut porni botul");
        await refreshAll();
      } catch (e) {
        alert("Eroare la start");
      }
    }

    async function stopBot() {
      try {
        await fetchJSON("/api/stop", { method: "POST" });
        await refreshAll();
      } catch (e) {
        alert("Eroare la stop");
      }
    }

    async function saveSettings() {
      try {
        const symbols = el("symbolsInput").value
          .split(",")
          .map(s => s.trim().toUpperCase())
          .filter(Boolean);

        const payload = {
          symbols,
          risk_pct: parseFloat(el("riskPct").value || "1"),
          sl_pct: parseFloat(el("slPct").value || "1.5"),
          rr_ratio: parseFloat(el("rrRatio").value || "3"),
          dd_limit: parseFloat(el("ddLimit").value || "5"),
          max_positions: parseInt(el("maxPositions").value || "3", 10),
          scan_interval: parseInt(el("scanInterval").value || "300", 10),
        };

        const data = await fetchJSON("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (!data.ok) {
          alert("Nu am putut salva setarile");
          return;
        }

        await refreshAll();
      } catch (e) {
        alert("Eroare la salvarea setarilor");
      }
    }

    async function refreshAll() {
      await Promise.all([
        refreshStatus(),
        refreshPositions(),
        refreshHistory(),
        refreshLog()
      ]);
    }

    refreshAll();
    setInterval(refreshStatus, 3000);
    setInterval(refreshPositions, 4000);
    setInterval(refreshHistory, 5000);
    setInterval(refreshLog, 2500);
  </script>
</body>
</html>
