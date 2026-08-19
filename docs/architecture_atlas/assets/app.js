/* TradingBot Architecture Atlas — interactive explorer */
(function () {
  "use strict";

  const state = {
    master: null,
    timelineGraphs: null,
    cy: null,
    timelineCy: null,
    mapCy: null,
    activeTimelineStep: null,
    activeMapKey: null,
    architectureMap: null,
    currentGraph: "architecture",
    filters: {
      productionOnly: false,
      hideResearch: false,
      executionPathOnly: false,
      typeFilter: "all",
    },
    collapsedFolders: new Set(),
  };

  const EXECUTION_PATH_IDS = new Set([
    "tradingbot.application.live_runner",
    "tradingbot.kernel.trading_kernel",
    "tradingbot.pipeline.data_stage",
    "tradingbot.pipeline.indicator_stage",
    "tradingbot.pipeline.signal_stage",
    "tradingbot.pipeline.risk_stage",
    "tradingbot.pipeline.execution_stage",
    "tradingbot.adapters.mt5_market_data",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
    "tradingbot.adapters.vol_regime_strategy_registry",
    "tradingbot.services.trade_journal",
  ]);

  async function loadJSON(path) {
    if (window.ATLAS_BUNDLE) {
      if (path === "json/master.json") return window.ATLAS_BUNDLE.master;
      if (path === "json/architecture_map.json") return window.ATLAS_BUNDLE.architectureMap;
      if (path === "json/sequences.json") return window.ATLAS_BUNDLE.sequences;
      if (path.startsWith("graphs/")) {
        const name = path.replace("graphs/", "").replace(".json", "");
        if (window.ATLAS_BUNDLE.graphs[name]) return window.ATLAS_BUNDLE.graphs[name];
      }
      if (path === "json/timeline_graphs.json" && window.ATLAS_BUNDLE.timelineGraphs) {
        return window.ATLAS_BUNDLE.timelineGraphs;
      }
    }
    const r = await fetch(path);
    if (!r.ok) throw new Error("Failed " + path);
    return r.json();
  }

  function stars(n) {
    return "★".repeat(Math.min(5, n || 1)) + "☆".repeat(Math.max(0, 5 - (n || 1)));
  }

  function applyFilters(nodes, edges) {
    let ns = nodes.slice();
    let es = edges.slice();
    const f = state.filters;

    if (f.productionOnly) {
      ns = ns.filter((n) => n.production && !n.research);
    }
    if (f.hideResearch) {
      ns = ns.filter((n) => !n.research);
    }
    if (f.executionPathOnly) {
      ns = ns.filter((n) => EXECUTION_PATH_IDS.has(n.id) || n.type === "folder");
    }
    if (f.typeFilter !== "all") {
      ns = ns.filter((n) => n.type === f.typeFilter);
    }

    const ids = new Set(ns.map((n) => n.id));
    es = es.filter((e) => ids.has(e.source) && ids.has(e.target));
    return { nodes: ns, edges: es };
  }

  function buildElements(nodes, edges) {
    const els = [];
    for (const n of nodes) {
      els.push({
        group: "nodes",
        data: {
          id: n.id,
          label: n.label.length > 22 ? n.label.slice(0, 20) + "…" : n.label,
          fullLabel: n.label,
          type: n.type,
          district: n.district,
          color: n.color || "#888",
          importance: n.importance || 1,
          production: n.production,
          research: n.research,
          meta: n,
        },
      });
    }
    for (const e of edges) {
      els.push({
        group: "edges",
        data: {
          id: e.source + "->" + e.target + ":" + e.type,
          source: e.source,
          target: e.target,
          label: e.label || e.type,
          edgeType: e.type,
        },
      });
    }
    return els;
  }

  function createCy(container, nodes, edges, opts) {
    opts = opts || {};
    const skipFilters = opts.skipFilters || false;
    const onReady = opts.onReady || null;

    const fn = skipFilters ? { nodes: nodes.slice(), edges: edges.slice() } : applyFilters(nodes, edges);
    const elements = buildElements(fn.nodes, fn.edges);

    const cy = cytoscape({
      container: container,
      elements: elements,
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "font-size": opts.fontSize || "9px",
            color: "#e8eaed",
            "text-outline-color": "#0a0e14",
            "text-outline-width": 2,
            "background-color": "data(color)",
            width: "mapData(importance, 1, 5, 32, 58)",
            height: "mapData(importance, 1, 5, 32, 58)",
            "border-width": 2,
            "border-color": "#2a3544",
          },
        },
        {
          selector: 'node[type = "folder"]',
          style: {
            shape: "round-rectangle",
            "background-color": "#1a2332",
            "border-color": "#d4a017",
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#3d4f66",
            "target-arrow-color": "#3d4f66",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            label: "data(label)",
            "font-size": "7px",
            color: "#6b7785",
            "text-rotation": "autorotate",
            "text-margin-y": -8,
          },
        },
        {
          selector: 'edge[edgeType = "flow"]',
          style: {
            "line-color": "#2ecc71",
            "target-arrow-color": "#2ecc71",
            width: 2.5,
          },
        },
        {
          selector: ".highlight",
          style: {
            "border-color": "#2ecc71",
            "border-width": 4,
            "background-color": "#152218",
          },
        },
        {
          selector: ".highlight-edge",
          style: {
            "line-color": "#2ecc71",
            "target-arrow-color": "#2ecc71",
            width: 3,
          },
        },
        {
          selector: ":selected",
          style: {
            "border-color": "#d4a017",
            "border-width": 4,
          },
        },
      ],
      layout: {
        name: "cose",
        animate: false,
        nodeRepulsion: 9000,
        idealEdgeLength: 90,
        padding: 30,
      },
      minZoom: 0.2,
      maxZoom: 4,
      wheelSensitivity: 0.3,
    });

    cy.on("tap", "node", (evt) => showDetail(evt.target.data("meta")));
    cy.on("tap", (evt) => {
      if (evt.target === cy) clearHighlights(cy);
    });

    if (onReady) onReady(cy, fn.nodes.length, fn.edges.length);
    return cy;
  }

  function initCy(container, nodes, edges) {
    if (state.cy) state.cy.destroy();
    state.cy = createCy(container, nodes, edges, {
      onReady: function (cy, nCount, eCount) {
        document.getElementById("stat-nodes").textContent = nCount + " nodes";
        document.getElementById("stat-edges").textContent = eCount + " edges";
      },
    });
  }

  function clearHighlights(cy) {
    cy = cy || state.cy;
    if (!cy) return;
    cy.elements().removeClass("highlight highlight-edge");
  }

  function highlightNode(nodeId, direction, cy) {
    cy = cy || state.cy;
    if (!cy) return;
    clearHighlights(cy);
    const node = cy.getElementById(nodeId);
    if (!node.length) return;
    node.addClass("highlight");

    if (direction === "deps" || direction === "both") {
      const out = node.outgoers("edge");
      out.addClass("highlight-edge");
      out.targets().addClass("highlight");
    }
    if (direction === "rev" || direction === "both") {
      const inc = node.incomers("edge");
      inc.addClass("highlight-edge");
      inc.sources().addClass("highlight");
    }
  }

  function showDetail(meta) {
    const el = document.getElementById("detail");
    if (!meta) {
      el.innerHTML = '<div class="empty">یک گره را کلیک کنید<br><small>Click any node on the map</small></div>';
      return;
    }

    const calledBy = (meta.calledBy || []).map((x) => `<li>${x}</li>`).join("") || "<li>—</li>";
    const calls = (meta.calls || []).map((x) => `<li>${x}</li>`).join("") || "<li>—</li>";
    const files = (meta.files || []).map((x) => `<li><code>${x}</code></li>`).join("") || "<li>—</li>";
    const stages = (meta.stages || []).join(" → ");

    el.innerHTML = `
      <h3>${meta.label || meta.id}</h3>
      <span class="type-badge">${meta.type} · ${meta.districtLabel || meta.district}</span>
      <div class="stars" title="Importance">${stars(meta.importance)}</div>
      <p>${meta.description || ""}</p>
      <div class="fa-box">${meta.descriptionFa || ""}</div>
      <div class="section">
        <div class="section-title">When it runs</div>
        <p>${meta.runsWhen || "—"}</p>
      </div>
      <div class="section">
        <div class="section-title">Risk if removed</div>
        <p>${meta.riskIfRemoved || "—"}</p>
      </div>
      ${stages ? `<div class="section"><div class="section-title">Pipeline stages</div><p>${stages}</p></div>` : ""}
      <div class="section">
        <div class="section-title">Called by</div>
        <ul>${calledBy}</ul>
      </div>
      <div class="section">
        <div class="section-title">Calls / uses</div>
        <ul>${calls}</ul>
      </div>
      <div class="section">
        <div class="section-title">Files</div>
        <ul>${files}</ul>
      </div>
      <div class="section">
        <button type="button" id="btn-deps">Highlight dependencies →</button>
        <button type="button" id="btn-rev">← Highlight callers</button>
      </div>
    `;

    document.getElementById("btn-deps").onclick = () => highlightNode(meta.id, "deps", state.timelineCy || state.cy);
    document.getElementById("btn-rev").onclick = () => highlightNode(meta.id, "rev", state.timelineCy || state.cy);
  }

  function showPanel(name) {
    const panels = {
      graph: "canvas-wrap",
      timeline: "timeline-panel",
      heatmap: "heatmap-panel",
      map: "map-panel",
      seq: "seq-panel",
    };
    Object.entries(panels).forEach(([key, id]) => {
      const el = document.getElementById(id);
      if (el) el.style.display = key === name ? "block" : "none";
    });
    document.querySelectorAll(".nav-btn[data-view]").forEach((b) => {
      b.classList.toggle("active", b.dataset.view === name);
    });
  }

  async function loadGraph(name) {
    state.currentGraph = name;
    let data;
    try {
      data = await loadJSON("graphs/" + name + ".json");
    } catch {
      data = { nodes: state.master.nodes.slice(0, 80), edges: state.master.edges.slice(0, 120) };
    }
    initCy(document.getElementById("cy"), data.nodes, data.edges);
    showPanel("graph");
  }

  function renderTimeline() {
    const panel = document.getElementById("timeline-panel");
    panel.innerHTML = `
      <div id="timeline-layout">
        <div id="timeline-steps-col">
          <h2>Timeline — click a step</h2>
          <p style="font-size:11px;color:#8b949e;margin-bottom:12px;direction:rtl;text-align:right">
            روی هر مرحله کلیک کن → فایل‌ها و ارتباط‌ها
          </p>
          <div id="timeline-steps-list"></div>
        </div>
        <div id="timeline-graph-col">
          <div id="timeline-step-header">
            <h3 id="tl-title">Select a step</h3>
            <p id="tl-subtitle">یک مرحله از لیست چپ را انتخاب کن</p>
          </div>
          <div id="timeline-files"></div>
          <div id="timeline-graph-toolbar">
            <button type="button" id="tl-fit">Fit</button>
            <button type="button" id="tl-clear">Clear highlights</button>
          </div>
          <div id="cy-timeline"></div>
        </div>
      </div>`;

    const list = document.getElementById("timeline-steps-list");
    (state.master.timeline || []).forEach((step) => {
      const div = document.createElement("div");
      div.className = "step";
      div.dataset.stepId = step.id;
      div.innerHTML = `
        <div class="step-num">${step.icon || step.step}</div>
        <div>
          <strong>${step.step}. ${step.label}</strong>
          <div style="color:#8b949e;font-size:11px;margin-top:4px;direction:rtl;text-align:right">${step.labelFa || ""}</div>
        </div>`;
      div.addEventListener("click", () => showTimelineStep(step.id));
      list.appendChild(div);
    });

    document.getElementById("tl-fit").onclick = () => state.timelineCy?.fit(undefined, 40);
    document.getElementById("tl-clear").onclick = () => clearHighlights(state.timelineCy);
  }

  function showTimelineStep(stepId) {
    state.activeTimelineStep = stepId;
    document.querySelectorAll("#timeline-steps-list .step").forEach((el) => {
      el.classList.toggle("active", el.dataset.stepId === stepId);
    });

    const graphs = state.timelineGraphs || {};
    const payload = graphs[stepId];
    if (!payload) return;

    const step = payload.step || {};
    document.getElementById("tl-title").textContent = step.label || stepId;
    document.getElementById("tl-subtitle").textContent = step.labelFa || "";

    const filesEl = document.getElementById("timeline-files");
    filesEl.innerHTML = "";
    (payload.files || []).forEach((fp) => {
      const chip = document.createElement("span");
      chip.className = "file-chip";
      chip.textContent = fp;
      chip.title = "Click to highlight in graph";
      chip.addEventListener("click", () => {
        if (!state.timelineCy) return;
        const stem = fp.split("/").pop().replace(".py", "").replace(".bat", "").replace(".ps1", "");
        let found = null;
        state.timelineCy.nodes().forEach((n) => {
          const meta = n.data("meta") || {};
          const file = meta.file || "";
          if (file === fp || file.endsWith(stem + ".py") || (meta.files || []).includes(fp)) {
            found = n;
          }
        });
        if (found) {
          state.timelineCy.center(found);
          found.select();
          showDetail(found.data("meta"));
          highlightNode(found.id(), "both", state.timelineCy);
        }
      });
      filesEl.appendChild(chip);
    });

    if (state.timelineCy) state.timelineCy.destroy();
    state.timelineCy = createCy(
      document.getElementById("cy-timeline"),
      payload.nodes || [],
      payload.edges || [],
      { skipFilters: true, fontSize: "10px" }
    );

    setTimeout(() => state.timelineCy?.fit(undefined, 40), 50);

    document.getElementById("stat-nodes").textContent = (payload.nodes || []).length + " nodes (timeline)";
    document.getElementById("stat-edges").textContent = (payload.edges || []).length + " edges (timeline)";
    showDetail(null);
  }

  function renderHeatmap() {
    const h = state.master.heatmaps || {};
    const panel = document.getElementById("heatmap-panel");
    panel.innerHTML = `
      <h2 style="margin-bottom:16px;color:#d4a017">Dependency Heatmaps</h2>
      <p style="margin-bottom:16px;color:#8b949e">Files: ${h.stats?.totalPythonFiles || "?"} · Nodes: ${h.stats?.totalNodes || "?"} · Production: ${h.stats?.productionFiles || "?"} · Research: ${h.stats?.researchFiles || "?"}</p>
      <h3 style="margin:16px 0 8px;font-size:13px">Most connected</h3>
      <table><tr><th>Module</th><th>Score</th></tr>
      ${(h.mostConnected || []).map((r) => `<tr><td>${r.label}</td><td>${r.score}</td></tr>`).join("")}
      </table>
      <h3 style="margin:16px 0 8px;font-size:13px">Most imported (central)</h3>
      <table><tr><th>Module</th><th>Imports in</th></tr>
      ${(h.mostImported || []).slice(0, 15).map((r) => `<tr><td>${r.label}</td><td>${r.inDegree}</td></tr>`).join("")}
      </table>
      <h3 style="margin:16px 0 8px;font-size:13px;color:#e74c3c">Most dangerous (live impact)</h3>
      <ul>${(h.mostDangerous || []).map((id) => `<li><code>${id}</code></li>`).join("")}</ul>
      <h3 style="margin:16px 0 8px;font-size:13px">Research-only sample</h3>
      <ul>${(h.researchOnly || []).slice(0, 10).map((id) => `<li><code>${id}</code></li>`).join("")}</ul>
    `;
  }

  function subgraphFromMaster(rootIds, maxNodes) {
    maxNodes = maxNodes || 25;
    const nodeById = {};
    (state.master.nodes || []).forEach((n) => {
      nodeById[n.id] = n;
    });

    const roots = new Set();
    rootIds.forEach((r) => {
      if (nodeById[r]) roots.add(r);
      else {
        Object.keys(nodeById).forEach((nid) => {
          if (nid === r || nid.startsWith(r + ".")) roots.add(nid);
        });
      }
    });

    const pool = new Set(roots);
    const edgeList = [];
    (state.master.edges || []).forEach((e) => {
      if (roots.has(e.source) || roots.has(e.target)) {
        pool.add(e.source);
        pool.add(e.target);
        edgeList.push(e);
      }
    });

    const nodes = [...pool]
      .map((id) => nodeById[id])
      .filter((n) => n && n.type !== "folder")
      .sort((a, b) => {
        const aRoot = roots.has(a.id) ? 0 : 1;
        const bRoot = roots.has(b.id) ? 0 : 1;
        if (aRoot !== bRoot) return aRoot - bRoot;
        return (b.importance || 1) - (a.importance || 1);
      })
      .slice(0, maxNodes);

    const idSet = new Set(nodes.map((n) => n.id));
    const edges = edgeList.filter((e) => idSet.has(e.source) && idSet.has(e.target));
    return { nodes, edges };
  }

  function collectTreeRootIds(node) {
    if (node.id) return [node.id];
    if (node.roots && node.roots.length) return node.roots.slice();
    const ids = [];
    (node.children || []).forEach((c) => {
      if (c.id) ids.push(c.id);
      else if (c.roots && c.roots.length) ids.push(...c.roots);
    });
    return ids.length ? ids : (node.children || []).flatMap((c) => collectTreeRootIds(c));
  }

  function renderMap() {
    const panel = document.getElementById("map-panel");
    panel.innerHTML = `
      <div id="map-layout">
        <div id="map-tree-col">
          <h2>Architecture Map</h2>
          <p style="font-size:11px;color:#8b949e;margin-bottom:12px;direction:rtl;text-align:right">
            روی هر بخش کلیک کن → فایل‌ها و ارتباط‌ها
          </p>
          <div id="tree-root"></div>
        </div>
        <div id="map-graph-col">
          <div id="map-node-header">
            <h3 id="map-title">Select an item</h3>
            <p id="map-subtitle">یک بخش از درخت را انتخاب کن</p>
          </div>
          <div id="map-graph-toolbar">
            <button type="button" id="map-fit">Fit</button>
            <button type="button" id="map-clear">Clear highlights</button>
          </div>
          <div id="cy-map"></div>
        </div>
      </div>`;

    document.getElementById("map-fit").onclick = () => state.mapCy?.fit(undefined, 40);
    document.getElementById("map-clear").onclick = () => clearHighlights(state.mapCy);

    const tree = state.architectureMap;
    if (!tree) {
      document.getElementById("tree-root").innerHTML = "<p style='color:#e74c3c'>Map data missing — rebuild atlas</p>";
      return;
    }

    function showMapNode(node, mapKey) {
      state.activeMapKey = mapKey;
      document.querySelectorAll("#tree-root .tree-item").forEach((el) => {
        el.classList.toggle("active", el.dataset.mapKey === mapKey);
      });

      document.getElementById("map-title").textContent = node.label;
      document.getElementById("map-subtitle").textContent = node.meta || node.id || "";

      const roots = collectTreeRootIds(node);
      if (!roots.length) {
        document.getElementById("map-subtitle").textContent = "No code modules — documentation folder only";
        if (state.mapCy) state.mapCy.destroy();
        state.mapCy = null;
        return;
      }

      const sub = subgraphFromMaster(roots);
      if (!sub.nodes.length) {
        document.getElementById("map-subtitle").textContent = "No graph nodes found for this section";
        return;
      }

      if (state.mapCy) state.mapCy.destroy();
      state.mapCy = createCy(document.getElementById("cy-map"), sub.nodes, sub.edges, {
        skipFilters: true,
        fontSize: "10px",
      });
      setTimeout(() => state.mapCy?.fit(undefined, 40), 50);
      document.getElementById("stat-nodes").textContent = sub.nodes.length + " nodes (map)";
      document.getElementById("stat-edges").textContent = sub.edges.length + " edges (map)";
      showDetail(null);
    }

    function renderNode(node, depth) {
      const mapKey = node.id || node.mapKey || node.label;
      const clickable = !!(node.id || node.roots || (node.children && node.children.some((c) => c.id || c.roots)));
      const d = document.createElement("div");
      d.className = "tree-item" + (clickable ? " clickable" : "");
      d.style.marginLeft = depth * 14 + "px";
      d.dataset.mapKey = mapKey;
      d.textContent = (depth ? "└ " : "") + node.label + (node.meta ? " — " + node.meta : "");
      if (clickable) {
        d.addEventListener("click", (ev) => {
          ev.stopPropagation();
          showMapNode(node, mapKey);
        });
      }
      document.getElementById("tree-root").appendChild(d);
      (node.children || []).forEach((c) => renderNode(c, depth + 1));
    }
    renderNode(tree, 0);

    // Auto-select TradingKernel
    const kernelId = "tradingbot.kernel.trading_kernel.TradingKernel";
    const pick = findTreeNode(tree, kernelId);
    if (pick) showMapNode(pick.node, pick.key);
  }

  function findTreeNode(node, idOrKey, key) {
    key = key || node.id || node.mapKey || node.label;
    if (node.id === idOrKey) return { node, key };
    for (const c of node.children || []) {
      const found = findTreeNode(c, idOrKey);
      if (found) return found;
    }
    return null;
  }

  async function renderSequences() {
    const seq = await loadJSON("json/sequences.json");
    const panel = document.getElementById("seq-panel");
    panel.innerHTML = "<h2 style='margin-bottom:16px;color:#d4a017'>Execution Sequence Diagrams</h2>";
    const titles = {
      buy_trade: "BUY trade",
      sell_trade: "SELL trade",
      rejected_trade: "Rejected trade",
      cooldown: "Entry cooldown",
      daily_loss_stop: "Daily loss stop",
      trailing_stop: "Trailing stop",
      partial_tp: "Partial take profit",
      emergency_close: "Emergency close",
      friday_close: "Friday no-entry",
    };
    Object.entries(seq).forEach(([key, body]) => {
      const wrap = document.createElement("div");
      wrap.innerHTML = `<h3 style="font-size:13px;margin:20px 0 8px;color:#7cb8ff">${titles[key] || key}</h3><pre class="mermaid-wrap">${body.replace(/</g, "&lt;")}</pre>`;
      panel.appendChild(wrap);
    });
  }

  function setupSearch() {
    const input = document.getElementById("search");
    input.addEventListener("input", () => {
      const q = input.value.toLowerCase().trim();
      if (!state.cy || !q) {
        state.cy?.nodes().style("display", "element");
        return;
      }
      state.cy.nodes().forEach((n) => {
        const label = (n.data("fullLabel") || n.data("label") || "").toLowerCase();
        const id = (n.id() || "").toLowerCase();
        n.style("display", label.includes(q) || id.includes(q) ? "element" : "none");
      });
    });
  }

  function setupFilters() {
    document.querySelectorAll(".chip[data-filter]").forEach((chip) => {
      chip.addEventListener("click", () => {
        const key = chip.dataset.filter;
        state.filters[key] = !state.filters[key];
        chip.classList.toggle("on", state.filters[key]);
        loadGraph(state.currentGraph);
      });
    });

    document.getElementById("type-filter").addEventListener("change", (e) => {
      state.filters.typeFilter = e.target.value;
      loadGraph(state.currentGraph);
    });
  }

  async function init() {
    if (window.ATLAS_BUNDLE && window.ATLAS_BUNDLE.master) {
      state.master = window.ATLAS_BUNDLE.master;
      state.timelineGraphs = window.ATLAS_BUNDLE.timelineGraphs || null;
      state.architectureMap = window.ATLAS_BUNDLE.architectureMap || null;
    } else {
      try {
        state.master = await loadJSON("json/master.json");
        state.timelineGraphs = await loadJSON("json/timeline_graphs.json");
        state.architectureMap = await loadJSON("json/architecture_map.json");
      } catch (e) {
        document.body.innerHTML =
          "<div style='padding:40px;color:#e74c3c;font-family:sans-serif'>" +
          "<h2>Atlas data missing</h2>" +
          "<p>Run from project root:</p>" +
          "<pre style='background:#121820;padding:12px;color:#7cb8ff'>python docs/architecture_atlas/build_atlas.py</pre>" +
          "<p style='margin-top:12px;color:#8b949e'>Or open via OPEN_ATLAS.bat (local web server)</p></div>";
        return;
      }
    }

    renderTimeline();
    renderHeatmap();
    renderMap();
    await renderSequences();
    setupSearch();
    setupFilters();

    document.querySelectorAll(".nav-btn[data-graph]").forEach((btn) => {
      btn.addEventListener("click", () => loadGraph(btn.dataset.graph));
    });

    document.querySelectorAll(".nav-btn[data-view]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (btn.dataset.view === "graph") {
          showPanel("graph");
        } else {
          showPanel(btn.dataset.view);
          if (btn.dataset.view === "timeline" && !state.activeTimelineStep) {
            const first = (state.master.timeline || [])[0];
            if (first) showTimelineStep(first.id);
          }
          if (btn.dataset.view === "map") {
            if (!state.mapCy && state.architectureMap) renderMap();
            setTimeout(() => {
              state.mapCy?.resize();
              state.mapCy?.fit(undefined, 40);
            }, 80);
          }
        }
      });
    });

    document.getElementById("btn-fit").onclick = () => state.cy?.fit(undefined, 40);
    document.getElementById("btn-reset").onclick = () => loadGraph(state.currentGraph);
    document.getElementById("btn-clear").onclick = clearHighlights;

    await loadGraph("architecture");
    showDetail(null);
    document.getElementById("stat-gen").textContent = "Generated: " + (state.master.generatedAt || "").slice(0, 19);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
