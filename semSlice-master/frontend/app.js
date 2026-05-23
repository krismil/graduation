const state = {
  token: null,
  role: null,
  user: null,
  adminResult: null,
  tenantResult: null,
  tenantStrategyRuns: {},
  tenantSelectedStrategy: null,
};

const tenantTasks = [];
let tenantTaskSeq = 1;
let adminRealtimeTimer = null;
let adminRealtimeDigest = "";
let tenantRealtimeTimer = null;
let tenantRealtimeDigest = "";
let tenantSelectedCodecTask = "";
const TASK_STATUS_PENDING = "PENDING";
const TASK_STATUS_SUBMITTED = "SUBMITTED";
const TASK_STATUS_RUNNING = "RUNNING";
const RESOURCE_SLICE_COUNT = 3;
const PKL_VOCAB_MAP = {
  "test_data_en.pkl": "vocab_en.json",
  "test_data-en90%.pkl": "vocab_en90%.json",
  "test_data-en80%.pkl": "vocab_en80%.json",
};
const VOCAB_BASE_SIM_MAP = {
  "vocab_en.json": 0.74,
  "vocab_en90%.json": 0.71,
  "vocab_en80%.json": 0.69,
};

function byId(id) {
  return document.getElementById(id);
}

function apiBase() {
  return byId("apiBase").value.replace(/\/$/, "");
}

function setText(id, text) {
  const el = byId(id);
  if (el) el.textContent = text;
}

function escapeHtml(value) {
  return String(value ?? "-")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function shortText(value, limit = 52) {
  const text = String(value || "");
  return text.length > limit ? `${text.slice(0, limit)}...` : text || "-";
}

function formatEncodedPreview(metric) {
  if (!metric) return "暂无数据";
  const shape = String(metric.encoded_signal_shape || "").trim();
  const preview = String(metric.encoded_signal_preview || "").trim();
  if (!shape && !preview) return "暂无数据";
  return [shape ? `shape: ${shape}` : "shape: -", preview || "[]"].join("\n");
}

function normalizeStrategy(raw) {
  const value = String(raw || "semslice").toLowerCase().trim();
  if (value === "random" || value === "no_slice") return "noslice";
  if (value === "semantic" || value === "semantic_slice" || value === "pso") return "semslice";
  if (value === "weighted" || value === "latency_first") return "netslice";
  return value === "semslice" || value === "netslice" || value === "noslice" ? value : "semslice";
}

const STRATEGY_ORDER = ["semslice", "netslice", "noslice"];
const STRATEGY_LABELS = {
  semslice: "语义切片",
  netslice: "网络切片",
  noslice: "无切片",
};

function strategyLabel(raw) {
  const key = normalizeStrategy(raw);
  return STRATEGY_LABELS[key] || key;
}

const REQUIREMENT_LABELS = {
  high_fidelity: "高保真",
  low_latency: "低时延",
};

function requirementLabel(raw) {
  return REQUIREMENT_LABELS[String(raw || "").trim()] || raw || "-";
}

function firstNonEmpty(...values) {
  for (const value of values) {
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      return value;
    }
  }
  return "";
}

function formatNumber(value, digits = 3, unit = "") {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return `${number.toFixed(digits)}${unit}`;
}

function findByUserId(rows, userId) {
  return (rows || []).find((row) => String(row.user_id) === String(userId)) || null;
}

function flowSliceTone(sliceId, sliceName) {
  const token = String(`${sliceId || ""} ${sliceName || ""}`).toLowerCase();
  if (token.includes("90") || token.endsWith("2") || token.includes("slice-2")) return 1;
  if (token.includes("80") || token.endsWith("3") || token.includes("slice-3")) return 2;
  return 0;
}

function flowIconMarkup(kind) {
  if (kind === "slice") return "<span></span><span></span><span></span>";
  if (kind === "codec" || kind === "decoder") return "<span></span><span></span><span></span><span></span>";
  if (kind === "channel") return "<span></span><span></span><span></span>";
  if (kind === "kb") return "<span></span>";
  if (kind === "result") return "<span></span><span></span>";
  return "<span></span>";
}

function renderSemanticFlowNode(kind, title, value, sub, extraClass = "") {
  const cls = `semantic-flow-node flow-${kind}${extraClass ? ` ${extraClass}` : ""}`;
  return `
    <div class="${cls}">
      <div class="flow-icon flow-icon-${kind}" aria-hidden="true">${flowIconMarkup(kind)}</div>
      <div class="flow-node-title">${escapeHtml(title)}</div>
      <div class="flow-node-value">${escapeHtml(value || "-")}</div>
      <div class="flow-node-sub">${escapeHtml(sub || "-")}</div>
    </div>
  `;
}

function renderTenantSemanticFlow(selectedMetric = null, result = null) {
  const root = byId("tenantSemanticFlow");
  if (!root) return;

  const strategy = normalizeStrategy(
    (byId("tenantRunAlgorithm") && byId("tenantRunAlgorithm").value) ||
      state.tenantSelectedStrategy ||
      "semslice"
  );
  const isSemanticStrategy = strategy === "semslice";

  if (!selectedMetric) {
    root.className = `semantic-flow is-empty strategy-${strategy}`;
    root.innerHTML = '<div class="semantic-flow-empty">提交任务后展示任务、切片、编解码器与语义通信过程</div>';
    return;
  }

  const userId = selectedMetric.user_id;
  const run = result || state.tenantResult || {};
  const relations = (run.adaptation_output && run.adaptation_output.relations) || [];
  const slices = (run.slicing_output && run.slicing_output.slices) || [];
  const allocs = (run.allocation_output && run.allocation_output.allocations) || [];
  const task = tenantTasks.find((item) => String(item.task_id) === String(userId)) || {};
  const relation = findByUserId(relations, userId) || {};
  const allocation = findByUserId(allocs, userId) || {};
  const matchedSliceId = firstNonEmpty(relation.matched_slice_id, selectedMetric.slice_id, allocation.slice_id, task.slice_id);
  const matchedSliceName = firstNonEmpty(relation.matched_slice_name, task.slice_name, matchedSliceId);
  const matchedSlice =
    slices.find(
      (slice) =>
        String(slice.slice_id) === String(matchedSliceId) ||
        String(slice.slice_name) === String(matchedSliceName)
    ) || {};
  const codecId = firstNonEmpty(relation.codec_id, matchedSlice.codec_id, "codec-?");
  const kbId = firstNonEmpty(relation.kb_id, matchedSlice.kb_id, "kb-?");
  const kbType = firstNonEmpty(matchedSlice.kb_type, selectedMetric.task_vocab, task.codec_vocab, task.task_vocab, "-");
  const knowledgeLevel = firstNonEmpty(matchedSlice.knowledge_level, selectedMetric.knowledge_factor);
  const taskVocab = firstNonEmpty(selectedMetric.task_vocab, task.codec_vocab, task.task_vocab, "-");
  const requirement = firstNonEmpty(selectedMetric.requirement_type, relation.requirement_type, task.requirement_type);
  const similarity = firstNonEmpty(selectedMetric.similarity_score, relation.similarity_score, selectedMetric.fidelity);
  const modelProfile = firstNonEmpty(selectedMetric.model_profile, selectedMetric.checkpoint_name, "DeepSC");
  const encodedShape = firstNonEmpty(selectedMetric.encoded_signal_shape, "向量待生成");
  const toneIndex = flowSliceTone(matchedSliceId, matchedSliceName);

  root.className = `semantic-flow is-active strategy-${strategy} tone-${toneIndex} ${
    isSemanticStrategy ? "uses-kb" : "no-kb"
  }`;

  root.innerHTML = `
    <div class="semantic-flow-head">
      <div>
        <div class="semantic-flow-kicker">${escapeHtml(strategyLabel(strategy))}</div>
        <strong>${escapeHtml(userId || "任务")}</strong>
        <span>${escapeHtml(requirementLabel(requirement))} · ${escapeHtml(taskVocab)}</span>
      </div>
      <div class="semantic-flow-status">
        <span>${escapeHtml(matchedSliceName || matchedSliceId || "-")}</span>
        <span>${escapeHtml(codecId)}</span>
      </div>
    </div>
    <div class="semantic-flow-track" aria-label="语义通信流程动画">
      <svg class="semantic-flow-lines" viewBox="0 0 1000 260" preserveAspectRatio="none" aria-hidden="true">
        <path class="semantic-flow-base" d="M70 162 C132 122 178 96 245 102 S360 150 420 158 S536 112 585 102 S710 126 745 158 S870 118 930 100" />
        <path class="semantic-flow-pulse" d="M70 162 C132 122 178 96 245 102 S360 150 420 158 S536 112 585 102 S710 126 745 158 S870 118 930 100" />
        ${
          isSemanticStrategy
            ? `<path class="semantic-flow-kb-line" d="M370 118 C360 72 346 56 332 44" />
               <path class="semantic-flow-pulse kb-pulse" d="M370 118 C360 72 346 56 332 44" />
               <path class="semantic-flow-kb-line" d="M720 118 C710 72 696 56 682 44" />
               <path class="semantic-flow-pulse kb-pulse" d="M720 118 C710 72 696 56 682 44" />`
            : ""
        }
      </svg>
      ${renderSemanticFlowNode(
        "task",
        "任务接入",
        userId,
        `${requirementLabel(requirement)} / ${formatNumber(task.payload_symbols || selectedMetric.payload_symbols, 0, " 符号")}`
      )}
      ${renderSemanticFlowNode(
        "slice",
        "切片匹配",
        matchedSliceName || matchedSliceId,
        `相似度 ${formatNumber(similarity, 3)}`
      )}
      ${
        isSemanticStrategy
          ? `
            ${renderSemanticFlowNode(
              "kb",
              "编码知识库",
              kbId,
              `${kbType}${knowledgeLevel !== "" ? ` / ${formatNumber(knowledgeLevel, 2)}` : ""}`,
              "kb-enc flow-kb-enc"
            )}
            ${renderSemanticFlowNode(
              "kb",
              "解码知识库",
              kbId,
              `${kbType}${knowledgeLevel !== "" ? ` / ${formatNumber(knowledgeLevel, 2)}` : ""}`,
              "kb-dec flow-kb-dec"
            )}
          `
          : ""
      }
      ${renderSemanticFlowNode(
        "codec",
        "语义编码器",
        codecId,
        isSemanticStrategy
          ? `${modelProfile} / 带知识库 ${kbId}`
          : modelProfile
      )}
      ${renderSemanticFlowNode(
        "channel",
        "语义信道",
        `SNR ${formatNumber(selectedMetric.snr_db, 2, " dB")}`,
        `BW ${formatNumber(selectedMetric.bandwidth || allocation.bandwidth, 3)} / P ${formatNumber(selectedMetric.power || allocation.power, 3)}`
      )}
      ${renderSemanticFlowNode(
        "decoder",
        "语义解码器",
        codecId,
        isSemanticStrategy
          ? `带知识库 ${kbId} / shape ${encodedShape}`
          : `shape ${encodedShape}`
      )}
      ${renderSemanticFlowNode(
        "result",
        "结果输出",
        `SS ${formatNumber(selectedMetric.fidelity, 4)}`,
        `Delay ${formatNumber(selectedMetric.delay_ms, 3, " ms")}`
      )}
    </div>
    <div class="semantic-flow-meta">
      <span>任务与切片：${escapeHtml(userId || "-")} → ${escapeHtml(matchedSliceName || matchedSliceId || "-")}</span>
      <span>切片与编解码器：${escapeHtml(matchedSliceName || matchedSliceId || "-")} → ${escapeHtml(codecId)}</span>
      ${
        isSemanticStrategy
          ? `<span>编解码器各带知识库：${escapeHtml(kbType)}${knowledgeLevel !== "" ? ` / ${escapeHtml(formatNumber(knowledgeLevel, 2))}` : ""}</span>`
          : '<span>知识库：当前策略不参与语义匹配</span>'
      }
    </div>
  `;
}

async function callApi(path, body = null, method = "POST") {
  const headers = { "Content-Type": "application/json" };
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }

  const options = { method, headers };
  if (method !== "GET") {
    options.body = JSON.stringify(body || {});
  }

  const response = await fetch(`${apiBase()}${path}`, options);
  if (!response.ok) {
    let text = await response.text();
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed.detail === "string") {
        text = parsed.detail;
      }
    } catch (_error) {
      // keep raw text
    }
    throw new Error(`HTTP ${response.status}: ${text}`);
  }
  return response.json();
}

function stopAdminRealtimePolling() {
  if (adminRealtimeTimer) {
    clearInterval(adminRealtimeTimer);
    adminRealtimeTimer = null;
  }
}

function stopTenantRealtimePolling() {
  if (tenantRealtimeTimer) {
    clearInterval(tenantRealtimeTimer);
    tenantRealtimeTimer = null;
  }
}

function renderTable(targetId, rows) {
  const root = byId(targetId);
  if (!root) return;
  if (!rows || !rows.length) {
    root.innerHTML = '<div class="status">暂无数据</div>';
    return;
  }

  const keys = Object.keys(rows[0]);
  const head = keys.map((k) => `<th>${escapeHtml(k)}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${keys.map((k) => `<td>${escapeHtml(row[k])}</td>`).join("")}</tr>`)
    .join("");

  root.innerHTML = `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function renderBars(targetId, rows, key, maxValue = null) {
  const root = byId(targetId);
  if (!root) return;
  if (!rows || !rows.length) {
    root.innerHTML = '<div class="status">暂无数据</div>';
    return;
  }

  const max = maxValue || Math.max(...rows.map((r) => Number(r[key] || 0)), 1);
  root.innerHTML = rows
    .map((row) => {
      const value = Number(row[key] || 0);
      const pct = Math.max(0, Math.min(100, (value / max) * 100));
      return `
        <div class="bar-row">
          <div>${row.label || "-"}</div>
          <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
          <div>${value.toFixed(4)}</div>
        </div>
      `;
    })
    .join("");
}

function renderResourcePie(title, remaining, total, unit) {
  const safeTotal = Math.max(0, Number(total || 0));
  const safeRemaining = Math.max(0, Math.min(Number(remaining || 0), safeTotal));
  const remainingPct = safeTotal > 0 ? (safeRemaining / safeTotal) * 100 : 0;
  const usedPct = Math.max(0, 100 - remainingPct);
  const valueText = `${safeRemaining.toFixed(4)} / ${safeTotal.toFixed(4)}${unit ? ` ${unit}` : ""}`;

  return `
    <div class="pie-card">
      <div class="pie-title">${escapeHtml(title)}</div>
      <div
        class="pie"
        title="${escapeHtml(`剩余 ${remainingPct.toFixed(2)}%，已用 ${usedPct.toFixed(2)}%`)}"
        style="background: conic-gradient(#14b8a6 0 ${remainingPct.toFixed(2)}%, #d8e4f2 ${remainingPct.toFixed(2)}% 100%);"
      ></div>
      <div class="pie-text">${escapeHtml(valueText)}</div>
    </div>
  `;
}

function renderAdminResourcePies(result) {
  const root = byId("adminResourcePies");
  if (!root) return;

  const allocation = result && result.allocation_output;
  const network = (result && result.network_output && result.network_output.network) || {};
  const remaining = (allocation && allocation.remaining_resources) || {};
  const bandwidthInput = byId("totalBandwidth");
  const powerInput = byId("totalPower");
  const totalBandwidth = Number(network.total_bandwidth || (bandwidthInput && bandwidthInput.value) || 0);
  const totalPower = Number(network.total_power || (powerInput && powerInput.value) || 0);
  const remainingBandwidth = Object.prototype.hasOwnProperty.call(remaining, "bandwidth")
    ? Number(remaining.bandwidth || 0)
    : totalBandwidth;
  const remainingPower = Object.prototype.hasOwnProperty.call(remaining, "power") ? Number(remaining.power || 0) : totalPower;

  if (totalBandwidth <= 0 && totalPower <= 0) {
    root.innerHTML = '<div class="status">暂无剩余资源数据</div>';
    return;
  }

  root.innerHTML = [
    renderResourcePie("剩余带宽", remainingBandwidth, totalBandwidth, ""),
    renderResourcePie("剩余功率", remainingPower, totalPower, ""),
  ].join("");
}

function toFiniteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function clampPct(value) {
  return Math.max(0, Math.min(100, value));
}

function pctOf(value, total) {
  const safeTotal = Math.max(toFiniteNumber(total), 1e-9);
  return clampPct((toFiniteNumber(value) / safeTotal) * 100);
}

function getAdminFormNetwork() {
  return {
    total_bandwidth: toFiniteNumber((byId("totalBandwidth") && byId("totalBandwidth").value) || 2),
    total_power: toFiniteNumber((byId("totalPower") && byId("totalPower").value) || 1),
    target_snr_db: toFiniteNumber((byId("targetSnrDb") && byId("targetSnrDb").value) || 6),
    node_count: Math.max(1, Math.round(toFiniteNumber((byId("networkNodeCount") && byId("networkNodeCount").value) || 5, 5))),
    base_station_count: Math.max(1, Math.round(toFiniteNumber((byId("baseStationCount") && byId("baseStationCount").value) || 1, 1))),
  };
}

function getAdminFormSlices() {
  const names = ((byId("sliceNames") && byId("sliceNames").value) || "slice-en,slice-en90,slice-en80")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  let knowledgeBases = [];
  try {
    knowledgeBases = JSON.parse((byId("kbJson") && byId("kbJson").value) || "[]");
  } catch (_error) {
    knowledgeBases = [];
  }

  const count = Math.max(1, toFiniteNumber((byId("sliceCount") && byId("sliceCount").value) || names.length || 3, 3));
  return Array.from({ length: count }).map((_, index) => {
    const kb = knowledgeBases[index] || {};
    const name = names[index] || `slice-${index + 1}`;
    return {
      slice_id: `slice-${index + 1}`,
      slice_name: name,
      kb_type: kb.kb_type || "-",
      knowledge_level: toFiniteNumber(kb.knowledge_level, 0),
    };
  });
}

function getAdminTopologySlices(result) {
  const rawSlices = (result && result.slicing_output && result.slicing_output.slices) || [];
  const slices = rawSlices.length ? rawSlices : getAdminFormSlices();
  return slices.map((slice, index) => ({
    id: slice.slice_id || `slice-${index + 1}`,
    name: slice.slice_name || slice.slice_id || `slice-${index + 1}`,
    codecId: slice.codec_id || `codec-${index + 1}`,
    kbId: slice.kb_id || `kb-${index + 1}`,
    kbType: slice.kb_type || "-",
    knowledge: toFiniteNumber(slice.knowledge_level, 0),
    bandwidth: 0,
    power: 0,
    tasks: 0,
    delaySum: 0,
    fidelitySum: 0,
    snrSum: 0,
    sseSum: 0,
    metricCount: 0,
  }));
}

function findTopologySlice(slices, sliceId, sliceName, fallbackIndex = 0) {
  const id = String(sliceId || "");
  const name = String(sliceName || "");
  return (
    slices.find((slice) => String(slice.id) === id || String(slice.name) === name || String(slice.id) === name) ||
    slices[Math.max(0, Math.min(slices.length - 1, fallbackIndex))]
  );
}

function pushTopologyMetric(slice, metric) {
  if (!slice || !metric) return;
  slice.delaySum += toFiniteNumber(metric.delay_ms);
  slice.fidelitySum += toFiniteNumber(metric.fidelity);
  slice.snrSum += toFiniteNumber(metric.snr_db);
  slice.sseSum += toFiniteNumber(metric.s_se);
  slice.metricCount += 1;
}

function buildAdminTopologyData(result = null, boardRows = null, pendingRows = null) {
  const formNetwork = getAdminFormNetwork();
  const boardNetworkRow =
    boardRows &&
    boardRows.find((row) => row.total_bandwidth || row.total_power || row.target_snr_db || row.node_count || row.base_station_count);
  const boardNetwork = boardNetworkRow
    ? {
        total_bandwidth: boardNetworkRow.total_bandwidth,
        total_power: boardNetworkRow.total_power,
        target_snr_db: boardNetworkRow.target_snr_db,
        node_count: boardNetworkRow.node_count,
        base_station_count: boardNetworkRow.base_station_count,
      }
    : null;
  const network = (result && result.network_output && result.network_output.network) || boardNetwork || formNetwork;
  const totalBandwidth = toFiniteNumber(network.total_bandwidth, formNetwork.total_bandwidth);
  const totalPower = toFiniteNumber(network.total_power, formNetwork.total_power);
  // UI display should always follow the currently configured target SNR in the admin form,
  // instead of stale historical board rows from previous runs.
  const targetSnr = toFiniteNumber(formNetwork.target_snr_db, toFiniteNumber(network.target_snr_db, 6));
  const nodeCount = Math.max(1, Math.round(toFiniteNumber(network.node_count, formNetwork.node_count)));
  const baseStationCount = Math.max(1, Math.round(toFiniteNumber(network.base_station_count, formNetwork.base_station_count)));
  const selectedStrategy = normalizeStrategy((byId("adminRunAlgorithm") && byId("adminRunAlgorithm").value) || "semslice");
  const slices = getAdminTopologySlices(result);
  const topTasks = [];
  const taskChains = [];
  const seenTaskChains = new Set();
  const pending = pendingRows || [];
  const pushTaskChain = (row = {}, slice = null, extra = {}) => {
    const relation = extra.relation || {};
    const alloc = extra.alloc || row;
    const metric = extra.metric || row;
    const business = extra.business || row;
    const taskId = row.user_id || row.task_id || relation.user_id || alloc.user_id || metric.user_id || business.user_id || `task-${taskChains.length + 1}`;
    const key = String(taskId);
    if (seenTaskChains.has(key)) return;
    seenTaskChains.add(key);
    const matched = Boolean(slice);
    taskChains.push({
      id: taskId,
      status: row.status || extra.status || (matched ? "已运行" : "待运行"),
      matched,
      sliceId: matched ? slice.id : relation.matched_slice_id || row.slice_id || "",
      sliceName: matched ? slice.name : relation.matched_slice_name || row.slice || "待调度",
      sliceIndex: matched ? slices.indexOf(slice) : -1,
      codecId: matched ? slice.codecId : "",
      kbId: matched ? slice.kbId : "",
      kbType: matched ? slice.kbType : "",
      requirement: row.requirement || row.requirement_type || relation.requirement_type || business.requirement_type || "-",
      taskVocab: metric.task_vocab || row.task_vocab || business.task_vocab || "-",
      taskPkl: business.task_pkl || row.task_pkl || "",
      sampleIndex: business.sample_index ?? row.sample_index ?? 0,
      bandwidth: toFiniteNumber(alloc.bandwidth || row.bandwidth),
      power: toFiniteNumber(alloc.power || row.power),
      snr: toFiniteNumber(metric.snr_db || row.snr_db, targetSnr),
      delay: toFiniteNumber(metric.delay_ms || row.delay_ms),
      fidelity: toFiniteNumber(metric.fidelity || row.fidelity),
      sse: toFiniteNumber(metric.s_se || row.s_se),
    });
  };

  if (boardRows && boardRows.length) {
    boardRows.forEach((row, index) => {
      const slice = findTopologySlice(slices, row.slice_id || row.slice, row.slice || row.slice_id, index % slices.length);
      slice.bandwidth += toFiniteNumber(row.bandwidth);
      slice.power += toFiniteNumber(row.power);
      slice.tasks += 1;
      pushTopologyMetric(slice, row);
      pushTaskChain(row, slice, { status: row.status || "已运行" });
      if (topTasks.length < 4) {
        topTasks.push({
          id: row.user_id || `task-${index + 1}`,
          slice: slice.name,
          fidelity: toFiniteNumber(row.fidelity),
          delay: toFiniteNumber(row.delay_ms),
          status: row.status || "已运行",
        });
      }
    });
  } else if (result) {
    const relations = (result.adaptation_output && result.adaptation_output.relations) || [];
    const allocs = (result.allocation_output && result.allocation_output.allocations) || [];
    const metrics = (result.performance_output && result.performance_output.user_metrics) || [];
    const users = (result.business_output && result.business_output.users) || [];
    const relationMap = Object.fromEntries(relations.map((row) => [row.user_id, row]));
    const metricMap = Object.fromEntries(metrics.map((row) => [row.user_id, row]));
    const allocMap = Object.fromEntries(allocs.map((row) => [row.user_id, row]));
    const userMap = Object.fromEntries(users.map((row) => [row.user_id, row]));

    allocs.forEach((alloc, index) => {
      const relation = relationMap[alloc.user_id] || {};
      const slice = findTopologySlice(slices, relation.matched_slice_id || alloc.slice_id, relation.matched_slice_name || alloc.slice_id, index % slices.length);
      const metric = metricMap[alloc.user_id] || {};
      slice.bandwidth += toFiniteNumber(alloc.bandwidth);
      slice.power += toFiniteNumber(alloc.power);
      slice.tasks += 1;
      pushTopologyMetric(slice, metric);
      if (topTasks.length < 4) {
        topTasks.push({
          id: alloc.user_id || `task-${index + 1}`,
          slice: slice.name,
          fidelity: toFiniteNumber(metric.fidelity),
          delay: toFiniteNumber(metric.delay_ms),
          status: "已运行",
        });
      }
    });

    const taskIds = new Set([
      ...users.map((row) => row.user_id),
      ...relations.map((row) => row.user_id),
      ...allocs.map((row) => row.user_id),
      ...metrics.map((row) => row.user_id),
    ]);
    Array.from(taskIds).forEach((userId, index) => {
      const relation = relationMap[userId] || {};
      const alloc = allocMap[userId] || {};
      const metric = metricMap[userId] || {};
      const business = userMap[userId] || {};
      const hasMatchedSlice = Boolean(relation.matched_slice_id || relation.matched_slice_name || alloc.slice_id || metric.slice_id);
      const slice = hasMatchedSlice
        ? findTopologySlice(
            slices,
            relation.matched_slice_id || alloc.slice_id || metric.slice_id,
            relation.matched_slice_name || alloc.slice_id || metric.slice_id,
            index % Math.max(slices.length, 1)
          )
        : null;
      pushTaskChain({ user_id: userId }, slice, {
        relation,
        alloc,
        metric,
        business,
        status: slice ? "已运行" : "待调度",
      });
    });
  }

  if (!topTasks.length && pending.length) {
    pending.slice(0, 4).forEach((row, index) => {
      topTasks.push({
        id: row.user_id || `task-${index + 1}`,
        slice: "待调度",
        fidelity: 0,
        delay: 0,
        status: row.status || "待运行",
      });
    });
  }
  pending.forEach((row) => pushTaskChain(row, null, { status: row.status || "待运行" }));

  const usedBandwidth = Math.min(totalBandwidth, slices.reduce((sum, slice) => sum + slice.bandwidth, 0));
  const usedPower = Math.min(totalPower, slices.reduce((sum, slice) => sum + slice.power, 0));
  const metricCount = slices.reduce((sum, slice) => sum + slice.metricCount, 0);
  const totalTasks = slices.reduce((sum, slice) => sum + slice.tasks, 0) || pending.length;
  const avgDelay = metricCount ? slices.reduce((sum, slice) => sum + slice.delaySum, 0) / metricCount : 0;
  const avgFidelity = metricCount ? slices.reduce((sum, slice) => sum + slice.fidelitySum, 0) / metricCount : 0;
  const avgSnr = metricCount ? slices.reduce((sum, slice) => sum + slice.snrSum, 0) / metricCount : targetSnr;
  const avgSse = metricCount ? slices.reduce((sum, slice) => sum + slice.sseSum, 0) / metricCount : 0;

  return {
    strategy: selectedStrategy,
    totalBandwidth,
    totalPower,
    targetSnr,
    nodeCount,
    baseStationCount,
    usedBandwidth,
    usedPower,
    totalTasks,
    pendingTasks: pending.length,
    avgDelay,
    avgFidelity,
    avgSnr,
    avgSse,
    slices,
    taskChains,
    topTasks,
    active: totalTasks > 0 || usedBandwidth > 0 || usedPower > 0,
  };
}

function renderTopologyResourceRow(label, value, total, fillClass = "") {
  const pct = pctOf(value, total);
  return `
    <div class="topology-resource-row">
      <span>${escapeHtml(label)}</span>
      <div class="topology-resource-track"><div class="topology-resource-fill ${fillClass}" style="width:${pct.toFixed(1)}%"></div></div>
      <span>${pct.toFixed(0)}%</span>
    </div>
  `;
}

function renderAdminNetworkTopology(result = null, boardRows = null, pendingRows = null) {
  const root = byId("adminNetworkTopology");
  if (!root) return;

  const data = buildAdminTopologyData(result, boardRows, pendingRows);
  const VIEW_W = 1200;
  const VIEW_H = 560;
  const basePoint = { x: 565, y: 338 };
  const visibleSliceCount = Math.max(data.nodeCount, data.slices.length, 1);
  const slicePoint = (index) => {
    const radiusX = visibleSliceCount > 8 ? 320 : 285;
    const radiusY = visibleSliceCount > 8 ? 176 : 166;
    const angle = (-105 + (360 / visibleSliceCount) * index) * (Math.PI / 180);
    return {
      x: basePoint.x + Math.cos(angle) * radiusX,
      y: basePoint.y + Math.sin(angle) * radiusY,
    };
  };
  const baseStationPoint = (index) => {
    if (data.baseStationCount <= 1) return basePoint;
    const angle = (-90 + (360 / data.baseStationCount) * index) * (Math.PI / 180);
    return {
      x: basePoint.x + Math.cos(angle) * 76,
      y: basePoint.y + Math.sin(angle) * 58,
    };
  };
  const baseIds = Array.from({ length: data.baseStationCount }, (_, index) => `gnb-${index}`);
  const primaryBaseId = baseIds[0] || "gnb-0";
  const COLORS = {
    slice: { color: "#66bb6a", soft: "#f0fdf4", ink: "#166534" },
    user: { color: "#111827", soft: "#f9fafb", ink: "#111827" },
    base: { color: "#ef4444", soft: "#fee2e2", ink: "#991b1b" },
    control: { color: "#1f2937", soft: "#f3f4f6", ink: "#111827" },
  };
  const SLICE_ACCENTS = ["#16a34a", "#2563eb", "#9333ea", "#ea580c", "#0891b2", "#be123c"];
  const TASK_LINK_ACCENTS = ["#ef4444", "#2563eb", "#f59e0b", "#a855f7", "#06b6d4", "#ec4899"];
  const userPositions = [
    { x: 135, y: 235 },
    { x: 120, y: 345 },
    { x: 185, y: 455 },
    { x: 315, y: 520 },
    { x: 68, y: 292 },
    { x: 78, y: 430 },
  ];
  const receiverPositions = [
    { x: 1015, y: 235 },
    { x: 1065, y: 345 },
    { x: 985, y: 470 },
    { x: 820, y: 525 },
    { x: 1105, y: 276 },
    { x: 1088, y: 438 },
  ];
  const sliceAccent = (index) => SLICE_ACCENTS[index % SLICE_ACCENTS.length];
  const taskLinkAccent = (index) => TASK_LINK_ACCENTS[index % TASK_LINK_ACCENTS.length];
  const actualTaskChains = data.taskChains || [];
  const sfcChainKey = (task) =>
    task && task.matched
      ? [
          task.sliceId || task.sliceName || "",
          task.codecId || "",
          task.kbId || "",
          task.sliceIndex >= 0 ? `node-${task.sliceIndex}` : "",
        ].join("|")
      : "";
  const sfcAccentMap = new Map();
  actualTaskChains.forEach((task) => {
    const key = sfcChainKey(task);
    if (key && !sfcAccentMap.has(key)) {
      sfcAccentMap.set(key, taskLinkAccent(sfcAccentMap.size));
    }
  });
  const sfcAccent = (task, fallbackIndex = 0) =>
    task && task.matched ? sfcAccentMap.get(sfcChainKey(task)) || taskLinkAccent(fallbackIndex) : "#64748b";
  const visibleUserTasks = actualTaskChains.length ? actualTaskChains.slice(0, 6) : [];
  const graphTaskChains = visibleUserTasks.filter((task) => task.matched && task.sliceIndex >= 0);
  const graphTaskIndex = new Map(graphTaskChains.map((task, index) => [String(task.id), index]));
  const serviceLabel = (_slice, _index, task = null) => {
    const requirement = String((task && task.requirement) || "").toLowerCase();
    if (requirement.includes("low_latency") || requirement.includes("低时延")) return "低时延业务";
    return "高保真业务";
  };

  const sliceDeployments = data.slices
    .map((slice, index) => `
      <div class="slice-deploy-row slice-node-row">
        <span class="deploy-dot"></span>
        <strong>${escapeHtml(slice.name)}</strong>
        <span>控制器下发到节点：切片 ${index + 1}</span>
        <em>${escapeHtml(slice.kbType)} KB ${slice.knowledge.toFixed(2)} / ${slice.tasks || 0} 任务</em>
      </div>
    `)
    .join("");

  const glyphMarkup = (_type, token) => `<span class="circle-token">${escapeHtml(token || "")}</span><span class="circle-halo"></span>`;
  const nodes = [];
  const sliceInfoCards = [];
  const addNode = (node) => {
    nodes.push({ diameter: 34, width: 92, cls: "", token: "", x: 0, y: 0, ...node });
  };

  addNode({ id: "admin", cls: "topology-upper topology-admin", token: "A", name: "管理员", sub: "发布任务", x: 155, y: 80, diameter: 58, width: 120, ...COLORS.control });
  addNode({ id: "controller", cls: "topology-upper topology-control", token: "CTL", name: "切片控制器", sub: "按切片下发", x: 590, y: 80, diameter: 64, width: 140, ...COLORS.control });
  baseIds.forEach((baseId, index) => {
    const point = baseStationPoint(index);
    addNode({
      id: baseId,
      cls: "topology-lower topology-bs-main",
      token: "BS",
      name: index === 0 ? "基站" : "",
      sub: index === 0 ? (data.baseStationCount > 1 ? `基站集群 x${data.baseStationCount}` : "无线接入 + QoS保障") : `BS${index + 1}`,
      x: point.x,
      y: point.y,
      diameter: index === 0 ? 64 : 54,
      width: index === 0 ? 124 : 76,
      ...COLORS.base,
    });
  });
  if (visibleUserTasks.length) {
    visibleUserTasks.forEach((task, index) => {
      const point = userPositions[index % userPositions.length];
      addNode({
        id: `u${index + 1}`,
        cls: `topology-lower topology-client ${task.matched ? "is-task-bound" : "is-task-pending"}`,
        token: "U",
        name: index === 0 ? "用户端" : "",
        sub: task.id,
        x: point.x,
        y: point.y,
        diameter: task.matched ? 36 : 32,
        width: 94,
        ...COLORS.user,
      });
    });
    graphTaskChains.forEach((task, index) => {
      const point = receiverPositions[index % receiverPositions.length];
      addNode({
        id: `r${index + 1}`,
        cls: "topology-lower topology-client topology-receiver is-task-bound",
        token: "R",
        name: index === 0 ? "接收端" : "",
        sub: task.id,
        x: point.x,
        y: point.y,
        diameter: 34,
        width: 94,
        ...COLORS.user,
      });
    });
  } else {
    addNode({ id: "u1", cls: "topology-lower topology-client", token: "U", name: "用户端", sub: "等待任务", x: 135, y: 275, diameter: 36, width: 82, ...COLORS.user });
    addNode({ id: "u2", cls: "topology-lower topology-client", token: "U", x: 130, y: 410, diameter: 32, width: 54, ...COLORS.user });
    addNode({ id: "u3", cls: "topology-lower topology-client", token: "U", x: 270, y: 505, diameter: 32, width: 54, ...COLORS.user });
    addNode({ id: "u4", cls: "topology-lower topology-client", token: "U", x: 470, y: 515, diameter: 32, width: 54, ...COLORS.user });
  }
  Array.from({ length: visibleSliceCount }).forEach((_, index) => {
    const slice = data.slices[index];
    const point = slicePoint(index);
    const isActiveSlice = Boolean(slice);
    addNode({
      id: `slice-${index}`,
      cls: `topology-lower topology-slice-node ${isActiveSlice ? "is-bound" : "is-candidate"}`,
      token: `${index + 1}`,
      name: slice ? slice.name : "候选节点",
      sub: slice ? `切片${index + 1}` : "待匹配",
      x: point.x,
      y: point.y,
      diameter: isActiveSlice ? 44 : 36,
      width: 108,
      accent: isActiveSlice ? sliceAccent(index) : COLORS.slice.color,
      ...COLORS.slice,
    });
    if (isActiveSlice) {
      sliceInfoCards.push({
        id: `slice-card-${index}`,
        slice,
        x: Math.min(point.x + 34, VIEW_W - 180),
        y: Math.max(132, point.y - 28),
        index,
      });
    }
  });

  const pointMap = Object.fromEntries(nodes.map((node) => [node.id, node]));
  const pathFromIds = (ids) => ids
    .map((id, index) => {
      const node = pointMap[id];
      if (!node) return "";
      return `${index === 0 ? "M" : "L"}${node.x} ${node.y}`;
    })
    .filter(Boolean)
    .join(" ");
  const lineMarkup = [];
  const addLine = (ids, cls = "topology-line", style = "") => {
    if (ids.some((id) => !pointMap[id])) return;
    const d = pathFromIds(ids);
    if (d) lineMarkup.push(`<path class="${cls}"${style ? ` style="${style}"` : ""} d="${d}" />`);
  };
  const addDeployArrow = (targetId) => {
    const from = pointMap.controller;
    const to = pointMap[targetId];
    if (!from || !to) return;
    const stop = {
      x: from.x + (to.x - from.x) * 0.72,
      y: from.y + (to.y - from.y) * 0.72,
    };
    const control = {
      x: from.x + (to.x - from.x) * 0.44,
      y: Math.min(from.y, stop.y) - 36,
    };
    lineMarkup.push(
      `<path class="topology-deploy-arrow topology-arrow-line" d="M${from.x} ${from.y} Q${control.x} ${control.y} ${stop.x} ${stop.y}" />`
    );
  };
  const sfcModels = actualTaskChains.map((task, index) => {
    const slice = task.sliceIndex >= 0 ? data.slices[task.sliceIndex] : null;
    const graphIndex = graphTaskIndex.has(String(task.id)) ? graphTaskIndex.get(String(task.id)) : -1;
    const sourceIndex = visibleUserTasks.findIndex((item) => String(item.id) === String(task.id));
    const source = sourceIndex >= 0 ? `u${sourceIndex + 1}` : "";
    const receiver = graphIndex >= 0 ? `r${graphIndex + 1}` : "";
    const baseNode = sourceIndex >= 0 ? baseIds[sourceIndex % baseIds.length] : primaryBaseId;
    const sliceIndex = task.sliceIndex >= 0 ? task.sliceIndex : index;
    return {
      task,
      slice,
      index,
      accent: sfcAccent(task, index),
      source,
      receiver,
      baseNode,
      nodeId: task.matched ? `slice-${task.sliceIndex}` : "",
      nodeLabel: task.matched ? `节点${task.sliceIndex + 1}` : "待匹配节点",
      sourceLabel: task.id,
      receiverLabel: task.matched ? `${task.id}-接收端` : "待接收",
      kbLabel: `知识库${(sliceIndex % 3) + 1}`,
      service: serviceLabel(slice, index, task),
      sfcCount: 1,
      snr: task.snr || data.avgSnr,
      delay: task.delay || data.avgDelay,
      fidelity: toFiniteNumber(task.fidelity, data.avgFidelity),
      sse: toFiniteNumber(task.sse, data.avgSse),
      matched: task.matched && graphIndex >= 0,
    };
  });

  addLine(["admin", "controller"], "topology-control-link topology-arrow-line");
  baseIds.forEach((baseId) => {
    Array.from({ length: visibleSliceCount }).forEach((_, index) => addLine([baseId, `slice-${index}`], "topology-network-link"));
  });
  Array.from({ length: visibleSliceCount }).forEach((_, index) => {
    const next = (index + 1) % visibleSliceCount;
    addLine([`slice-${index}`, `slice-${next}`], "topology-network-link");
    if (index % 2 === 0) addLine([`slice-${index}`, `slice-${(index + 2) % visibleSliceCount}`], "topology-network-link");
  });
  visibleUserTasks.forEach((task, index) => {
    const source = `u${index + 1}`;
    const baseId = baseIds[index % baseIds.length] || primaryBaseId;
    const target = task.matched && task.sliceIndex >= 0 ? `slice-${task.sliceIndex}` : null;
    addLine(target ? [source, baseId, target] : [source, baseId], task.matched ? "topology-task-access-link" : "topology-pending-link", `--task-accent:${sfcAccent(task, index)}`);
  });
  sfcModels.filter((sfc) => sfc.matched).forEach((sfc) => {
    addLine(
      [sfc.source, sfc.baseNode, sfc.nodeId, sfc.baseNode, sfc.receiver],
      "topology-sfc-link",
      `--task-accent:${sfc.accent}`
    );
  });
  data.slices.forEach((_slice, index) => {
    addDeployArrow(`slice-${index}`);
  });

  const nodeMarkup = nodes
    .map((node) => {
      const style = [
        `left:${((node.x / VIEW_W) * 100).toFixed(4)}%`,
        `top:${((node.y / VIEW_H) * 100).toFixed(4)}%`,
        `width:${node.width}px`,
        `--node-diameter:${node.diameter}px`,
        `--node-offset:${(-node.diameter / 2).toFixed(1)}px`,
        `--node-color:${node.color}`,
        `--node-soft:${node.soft}`,
        `--node-ink:${node.ink}`,
        `--slice-accent:${node.accent || node.color}`,
      ].join(";");
      return `
        <div class="topology-node ${node.cls}" style="${style}">
          <div class="network-glyph circle-glyph" aria-hidden="true">${glyphMarkup(node.type, node.token)}</div>
          ${node.name ? `<div class="topology-node-name">${escapeHtml(node.name)}</div>` : ""}
          ${node.sub ? `<div class="topology-node-sub">${escapeHtml(node.sub)}</div>` : ""}
        </div>
      `;
    })
    .join("");
  const resourcePanelMarkup = `
    <div class="topology-resource-overview">
      <div class="resource-overview-title">网络资源</div>
      <div class="resource-overview-grid">
        <span>节点数</span><strong>${data.nodeCount}</strong>
        <span>基站数</span><strong>${data.baseStationCount}</strong>
        <span>目标 SNR</span><strong>${data.targetSnr.toFixed(2)} dB</strong>
        <span>总带宽</span><strong>${data.totalBandwidth.toFixed(2)}</strong>
        <span>已用带宽</span><strong>${data.usedBandwidth.toFixed(2)}</strong>
        <span>总功率</span><strong>${data.totalPower.toFixed(2)}</strong>
        <span>已用功率</span><strong>${data.usedPower.toFixed(2)}</strong>
      </div>
    </div>
  `;
  const sliceInfoMarkup = sliceInfoCards
    .map((card) => {
      const relatedTasks = actualTaskChains.filter((task) => task.matched && task.sliceIndex === card.index);
      const style = [
        `left:${((card.x / VIEW_W) * 100).toFixed(4)}%`,
        `top:${((card.y / VIEW_H) * 100).toFixed(4)}%`,
        `--slice-accent:${sliceAccent(card.index)}`,
      ].join(";");
      return `
        <details class="topology-slice-info" style="${style}">
          <summary>${escapeHtml(card.slice.name)}</summary>
          <div class="slice-info-body">
            <span>业务</span><strong>${relatedTasks.length ? `${relatedTasks.length} 个实际任务` : "暂无承载任务"}</strong>
            <span>知识库</span><strong>${escapeHtml(card.slice.kbId)}</strong>
            <span>类型</span><strong>${escapeHtml(card.slice.kbType)}</strong>
            <span>编解码器</span><strong>${escapeHtml(card.slice.codecId)}</strong>
            <span>SFC</span><strong>实际链 x${relatedTasks.length}</strong>
          </div>
        </details>
      `;
    })
    .join("");

  const matchedSfcModels = sfcModels.filter((sfc) => sfc.task.matched);
  const pendingSfcModels = sfcModels.filter((sfc) => !sfc.task.matched);
  const uniqueCodecs = Array.from(new Set(matchedSfcModels.map((sfc) => sfc.task.codecId).filter(Boolean)));
  const uniqueKbs = Array.from(new Set(matchedSfcModels.map((sfc) => sfc.task.kbId).filter(Boolean)));
  const vnfPoolMarkup = `
    <div class="topology-vnf-pool">
      <div class="vnf-pool-title">共享 VNF 池</div>
      <div class="vnf-pool-grid">
        <div class="vnf-pool-item codec">
          <span class="vnf-token">ENC</span>
          <strong>语义编解码器</strong>
          <em>${uniqueCodecs.length ? `${uniqueCodecs.length} 个实例被 SFC 复用` : "暂无实际任务复用"}</em>
        </div>
        <div class="vnf-pool-item kb">
          <span class="vnf-token">KB</span>
          <strong>编解码器知识库</strong>
          <em>${uniqueKbs.length ? `${uniqueKbs.length} 个知识库随编码/解码器挂载` : "编码器、解码器各带知识库"}</em>
        </div>
      </div>
    </div>
  `;
  const sfcPanelMarkup = `
    <details class="topology-fold topology-sfc-panel" open>
      <summary>SFC业务链 <span>${matchedSfcModels.length} 条实际承载 / ${pendingSfcModels.length} 条待调度</span></summary>
      <div class="topology-sfc-list">
        ${sfcModels.length ? sfcModels.map((sfc) => `
          <div class="topology-sfc-row ${sfc.task.matched ? "is-matched" : "is-pending"}" style="--task-accent:${sfc.accent};--slice-accent:${sfc.accent}">
            <div class="sfc-row-head">
              <span class="sfc-slice-dot"></span>
              <strong>${escapeHtml(sfc.task.id)}</strong>
              <em>${escapeHtml(sfc.service)}</em>
              <span>${escapeHtml(sfc.task.status)}</span>
            </div>
            <div class="sfc-chain" aria-label="${escapeHtml(sfc.task.id)} SFC">
              <span>${escapeHtml(sfc.sourceLabel)}</span><i></i>
              <span>基站</span><i></i>
              ${
                sfc.task.matched
                  ? `<span class="is-shared">编码器带知识库</span><i></i>
                     <span class="is-shared">解码器带知识库</span><i></i>
                     <span>${escapeHtml(sfc.receiverLabel)}</span>`
                  : `<span class="is-waiting">等待调度</span><i></i>
                     <span class="is-waiting">待匹配切片</span>`
              }
            </div>
            <div class="sfc-row-meta">
              <span>Slice ${escapeHtml(sfc.task.sliceName)}</span>
              <span>Codec ${escapeHtml(sfc.task.codecId || "待匹配")} @ ${escapeHtml(sfc.nodeLabel)}</span>
              <span>KB ${escapeHtml(sfc.task.kbId || "待匹配")} 随编解码器携带</span>
              <span>BW ${sfc.task.bandwidth.toFixed(2)}</span>
              <span>P ${sfc.task.power.toFixed(2)}</span>
              <span>SNR ${sfc.snr.toFixed(2)} dB</span>
            </div>
          </div>
        `).join("") : '<div class="topology-empty-task">暂无用户提交任务</div>'}
      </div>
    </details>
  `;
  const renderSfcLaneStep = (token, title, sub, cls = "") => `
    <div class="sfc-lane-step ${cls}">
      <span class="sfc-lane-token">${escapeHtml(token)}</span>
      <div>
        <strong>${escapeHtml(title)}</strong>
        <em>${escapeHtml(sub)}</em>
      </div>
    </div>
  `;
  const renderSfcLaneFlow = (sfc) => {
    const baseIndex = Math.max(0, sfc.index % Math.max(data.baseStationCount, 1));
    const baseLabel = data.baseStationCount > 1 ? `BS${baseIndex + 1}` : "基站";
    const matchedSteps = [
      renderSfcLaneStep("U", sfc.sourceLabel, "用户端", "is-user"),
      renderSfcLaneStep("BS", baseLabel, "无线接入", "is-base"),
      renderSfcLaneStep("ENC", "语义编码器", `${sfc.task.codecId || "codec"} / 带知识库 ${sfc.task.kbId || sfc.kbLabel}`, "is-vnf"),
      renderSfcLaneStep("DEC", "语义解码器", `${sfc.task.codecId || "codec"} / 带知识库 ${sfc.task.kbId || sfc.kbLabel}`, "is-vnf"),
      renderSfcLaneStep("BS", baseLabel, "回传出口", "is-base"),
      renderSfcLaneStep("R", sfc.receiverLabel, "接收端", "is-user"),
    ];
    const pendingSteps = [
      renderSfcLaneStep("U", sfc.sourceLabel, "用户端", "is-user"),
      renderSfcLaneStep("BS", baseLabel, "等待接入", "is-base"),
      renderSfcLaneStep("...", "等待调度", "资源未分配", "is-waiting"),
      renderSfcLaneStep("S", "待匹配切片", "尚未生成实际链路", "is-waiting"),
    ];
    return (sfc.task.matched ? matchedSteps : pendingSteps).join('<i class="sfc-lane-connector"></i>');
  };
  const sfcLanePanelMarkup = `
    <section class="topology-sfc-lanes-panel">
      <div class="sfc-lanes-head">
        <div>
          <strong>SFC链路展开视图</strong>
          <span>${matchedSfcModels.length} 条实际承载 / ${pendingSfcModels.length} 条待调度</span>
        </div>
        <em>按每个业务任务独立展示端到端服务功能链</em>
      </div>
      <div class="sfc-lanes-list">
        ${sfcModels.length ? sfcModels.map((sfc) => `
          <div class="sfc-lane-row ${sfc.task.matched ? "is-matched" : "is-pending"}" style="--task-accent:${sfc.accent};--slice-accent:${sfc.accent}">
            <div class="sfc-lane-title">
              <span class="sfc-lane-dot"></span>
              <strong>${escapeHtml(sfc.task.id)}</strong>
              <em>${escapeHtml(sfc.service)}</em>
              <span>${escapeHtml(sfc.task.status)}</span>
            </div>
            <div class="sfc-lane-flow" aria-label="${escapeHtml(sfc.task.id)} 展开链路">
              ${renderSfcLaneFlow(sfc)}
            </div>
            <div class="sfc-lane-metrics">
              <span>Slice ${escapeHtml(sfc.task.sliceName)}</span>
              <span>Codec ${escapeHtml(sfc.task.codecId || "待匹配")}</span>
              <span>KB ${escapeHtml(sfc.task.kbId || "待匹配")} 随编解码器携带</span>
              <span>BW ${sfc.task.bandwidth.toFixed(2)}</span>
              <span>P ${sfc.task.power.toFixed(2)}</span>
              <span>SNR ${sfc.snr.toFixed(2)} dB</span>
              <span>Delay ${sfc.delay.toFixed(3)} ms</span>
              <span>SS ${sfc.fidelity.toFixed(4)}</span>
              <span>S-SE ${sfc.sse.toFixed(5)}</span>
            </div>
          </div>
        `).join("") : '<div class="topology-empty-task">暂无用户提交任务</div>'}
      </div>
    </section>
  `;

  root.innerHTML = `
    <div class="topology-summary">
      <div class="topology-summary-item">
        <div class="topology-summary-label">运行策略</div>
        <div class="topology-summary-value">${escapeHtml(strategyLabel(data.strategy))}</div>
      </div>
      <div class="topology-summary-item">
        <div class="topology-summary-label">节点含义</div>
        <div class="topology-summary-value">绿=节点 / 黑=用户 / 红=基站 / KB随编解码器</div>
      </div>
      <div class="topology-summary-item">
        <div class="topology-summary-label">下发目标</div>
        <div class="topology-summary-value">${matchedSfcModels.length} 条实际SFC / ${data.nodeCount} 节点 / ${data.baseStationCount} 基站</div>
      </div>
      <div class="topology-summary-item">
        <div class="topology-summary-label">业务状态</div>
        <div class="topology-summary-value">${data.totalTasks || 0} 个任务${data.pendingTasks ? ` / 待运行 ${data.pendingTasks}` : ""}</div>
      </div>
    </div>
    <div class="topology-main-row">
    <div class="topology-canvas ${data.active ? "is-active" : "is-idle"}">
      <div class="topology-plane topology-plane-lower" aria-hidden="true"></div>
      <div class="topology-plane topology-plane-upper" aria-hidden="true"></div>
      <svg class="topology-lines" viewBox="0 0 1200 560" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <marker id="topologyArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#ef4444"></path>
          </marker>
        </defs>
        ${lineMarkup.join("\n        ")}
      </svg>

      ${nodeMarkup}
      ${resourcePanelMarkup}
      ${vnfPoolMarkup}
      ${sliceInfoMarkup}

      <details class="topology-fold topology-slice-panel">
        <summary>切片下发关系 <span>一个节点对应一个切片</span></summary>
        <div class="slice-deploy-list">${sliceDeployments}</div>
      </details>

      <details class="topology-fold topology-metric-panel">
        <summary>性能反馈 <span>Delay ${data.avgDelay.toFixed(3)} ms / SS ${data.avgFidelity.toFixed(4)}</span></summary>
        <div class="topology-scheduler-core">
          <div class="topology-core-metric">SS<strong>${data.avgFidelity.toFixed(4)}</strong></div>
          <div class="topology-core-metric">SNR<strong>${data.targetSnr.toFixed(2)}</strong></div>
          <div class="topology-core-metric">S-SE<strong>${data.avgSse.toFixed(5)}</strong></div>
        </div>
      </details>
    </div>
    <aside class="topology-side-panel">
      ${sfcPanelMarkup}
    </aside>
    </div>
    ${sfcLanePanelMarkup}
  `;
}

function renderUnifiedCompareChart(comparisons) {
  const root = byId("adminUnifiedCompare");
  if (!root) return;
  if (!comparisons || !comparisons.length) {
    root.innerHTML = '<div class="status">暂无可对比数据</div>';
    return;
  }

  const metrics = [
    { key: "avg_delay_ms", title: "平均时延", digits: 3 },
    { key: "avg_ss", title: "平均 SS", digits: 4 },
    { key: "avg_s_se", title: "平均 S-SE", digits: 5 },
  ];
  const labels = {
    semslice: "语义切片",
    netslice: "网络切片",
    random: "无切片",
    noslice: "无切片",
  };

  root.innerHTML = metrics
    .map((metric) => {
      const vals = comparisons.map((row) => Number(row[metric.key] || 0));
      const maxVal = Math.max(...vals, 1e-9);
      const bars = comparisons
        .map((row) => {
          const strategy = String(row.strategy || "").toLowerCase();
          const strategyClass = strategy === "random" ? "noslice" : strategy;
          const value = Number(row[metric.key] || 0);
          const height = Math.max(8, (value / maxVal) * 120);
          return `
            <div class="metric-bar-item" data-strategy="${strategyClass}" title="点击切换到 ${labels[strategy] || strategyClass}">
              <div class="metric-bar ${strategyClass}" style="height:${height.toFixed(1)}px"></div>
              <div class="metric-label">${labels[strategy] || strategy}</div>
              <div class="metric-value">${value.toFixed(metric.digits)}</div>
            </div>
          `;
        })
        .join("");

      return `
        <div class="metric-compare-card">
          <div class="metric-compare-title">${metric.title}</div>
          <div class="metric-compare-bars">${bars}</div>
        </div>
      `;
    })
    .join("");

  root.querySelectorAll(".metric-bar-item[data-strategy]").forEach((el) => {
    el.style.cursor = "pointer";
    el.addEventListener("click", () => {
      const strategy = el.getAttribute("data-strategy");
      const algoEl = byId("adminRunAlgorithm");
      if (algoEl && strategy) {
        algoEl.value = strategy;
      }
      applyAdminRuntimePolicy().catch((e) => setText("adminConfigStatus", e.message));
    });
  });
}

function networkPayloadFromForm() {
  return {
    total_bandwidth: Number(byId("totalBandwidth").value || 2.0),
    total_power: Number(byId("totalPower").value || 1.0),
    target_snr_db: Number(byId("targetSnrDb").value || 6.0),
    node_count: Math.max(1, Math.round(Number((byId("networkNodeCount") && byId("networkNodeCount").value) || 5))),
    base_station_count: Math.max(1, Math.round(Number((byId("baseStationCount") && byId("baseStationCount").value) || 1))),
  };
}

function slicePayloadFromForm() {
  const names = (byId("sliceNames").value || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  let knowledge = [];
  try {
    knowledge = JSON.parse(byId("kbJson").value || "[]");
  } catch (error) {
    throw new Error(`知识库配置解析失败: ${error.message}`);
  }
  return {
    slice_count: Number(byId("sliceCount").value || 3),
    slice_names: names,
    codec_count: Number(byId("codecCount").value || 3),
    codec_modality: byId("codecModality").value || "text",
    knowledge_bases: knowledge,
  };
}

function showViewByRole() {
  byId("loginView").classList.add("hidden");
  byId("loginView").style.display = "none";
  byId("appView").classList.remove("hidden");
  byId("appView").style.display = "";

  const isAdmin = state.role === "admin";
  if (isAdmin) {
    renderAdminNetworkTopology(null);
    startAdminRealtimePolling();
    stopTenantRealtimePolling();
  } else {
    stopAdminRealtimePolling();
    startTenantRealtimePolling();
  }
  byId("activeCount").classList.toggle("hidden", !isAdmin);
  byId("adminView").classList.toggle("hidden", !isAdmin);
  byId("tenantView").classList.toggle("hidden", isAdmin);
  setText("pageTitle", isAdmin ? "管理员仪表盘" : "用户任务中心");
  setText("sessionText", `当前登录：${state.user.username}`);
}

function resetToLogin() {
  state.token = null;
  state.role = null;
  state.user = null;
  state.adminResult = null;
  state.tenantResult = null;
  state.tenantStrategyRuns = {};
  state.tenantSelectedStrategy = null;
  tenantTasks.length = 0;
  tenantTaskSeq = 1;
  adminRealtimeDigest = "";
  tenantRealtimeDigest = "";
  tenantSelectedCodecTask = "";
  renderAdminNetworkTopology(null);
  renderTenantSemanticFlow(null);
  stopAdminRealtimePolling();
  stopTenantRealtimePolling();

  byId("appView").classList.add("hidden");
  byId("appView").style.display = "none";
  byId("loginView").classList.remove("hidden");
  byId("loginView").style.display = "";
  setText("loginStatus", "未登录");
}

async function refreshAuthStats() {
  try {
    const stats = await callApi("/auth/stats", null, "GET");
    setText("activeCount", `在线用户 ${stats.active_user_count || 0}`);
  } catch (_error) {
    setText("activeCount", "在线用户 -");
  }
}

async function login() {
  const payload = {
    username: byId("username").value,
    password: byId("password").value,
    system_type: byId("systemType").value,
  };
  const result = await callApi("/auth/login", payload);
  state.token = result.token;
  state.role = result.role;
  state.user = result;
  setText("loginStatus", `登录成功：${result.username}`);
  showViewByRole();
  await refreshAuthStats();

  if (state.role === "admin") {
    await loadAdminExample();
    await syncAdminConfigStatus();
    await pullAdminRealtimeTasks();
    await refreshAdminUnifiedCompare();
  } else {
    await syncTenantConfigStatus();
    await pullTenantRealtimeTasks();
  }
}

async function logout() {
  try {
    if (state.token) await callApi("/auth/logout", {}, "POST");
  } finally {
    resetToLogin();
  }
}

async function loadAdminExample() {
  try {
    const data = await callApi("/workflow/example", null, "GET");
    const network = data.network || {};
    const slicing = data.slicing || {};

    byId("totalBandwidth").value = network.total_bandwidth ?? 2.0;
    byId("totalPower").value = network.total_power ?? 1.0;
    byId("targetSnrDb").value = network.target_snr_db ?? 6.0;
    byId("networkNodeCount").value = network.node_count ?? 5;
    byId("baseStationCount").value = network.base_station_count ?? 1;

    byId("sliceCount").value = slicing.slice_count ?? 3;
    byId("sliceNames").value = (slicing.slice_names || []).join(",");
    byId("codecCount").value = slicing.codec_count ?? 3;
    byId("kbJson").value = JSON.stringify(slicing.knowledge_bases || [], null, 2);
    renderAdminNetworkTopology(null);
  } catch (_error) {
    setText("adminConfigStatus", "示例加载失败，可继续手动配置");
  }
}

async function syncAdminConfigStatus() {
  try {
    const cfg = await callApi("/system/config/status", null, "GET");
    const adminAlgoEl = byId("adminRunAlgorithm");
    if (adminAlgoEl && cfg.allocation_algorithm) {
      adminAlgoEl.value = cfg.allocation_algorithm;
    }
    if (cfg.admin_config_ready) {
      setText("adminConfigStatus", "已发布：网络与切片配置已生效");
      setText("adminSliceStatus", "切片配置已发布，用户可提交运行任务");
    } else if (cfg.network_configured || cfg.slicing_configured) {
      setText("adminConfigStatus", "部分已发布：请同时发布网络与切片");
    } else {
      setText("adminConfigStatus", "待发布：请先发布网络与切片配置");
    }
    renderAdminNetworkTopology(null);
  } catch (_error) {
    setText("adminConfigStatus", "配置状态读取失败");
  }
}

async function publishAdminConfig() {
  let recomputeOk = false;
  const publishedNetwork = await callApi("/module/network/config", networkPayloadFromForm());
  const publishedSlicing = await callApi("/module/slice/config", slicePayloadFromForm());
  renderAdminNetworkTopology({
    network_output: publishedNetwork,
    slicing_output: publishedSlicing,
  });
  const publishedSliceCount = (publishedSlicing.slices || []).length;
  setText("adminSliceStatus", `切片已下发：共 ${publishedSliceCount} 个切片实例`);
  setText("adminConfigStatus", `配置已下发：目标SNR ${Number(publishedNetwork.network.target_snr_db || 0).toFixed(1)} dB，正在按当前策略重算`);
  try {
    const rerun = await callApi("/system/admin/runtime-policy/recompute-current", {
      adaptation_method: "similarity",
    });
    state.adminResult = rerun;
    renderAdminTaskPanels(rerun);
    recomputeOk = true;
  } catch (error) {
    setText(
      "adminConfigStatus",
      `配置已下发：目标SNR ${Number(publishedNetwork.network.target_snr_db || 0).toFixed(1)} dB；当前无可重算任务，${error.message}`
    );
  }
  adminRealtimeDigest = "";
  await pullAdminRealtimeTasks();
  if (recomputeOk) {
    await syncAdminConfigStatus();
  }
  await refreshAdminUnifiedCompare();
  return;

  const network = await callApi("/module/network/config", networkPayloadFromForm());
  const slicing = await callApi("/module/slice/config", slicePayloadFromForm());
  const sliceCount = (slicing.slices || []).length;
  setText("adminSliceStatus", `切片已发布：共 ${sliceCount} 个切片实例`);
  setText("adminConfigStatus", `发布成功：目标SNR ${Number(network.network.target_snr_db || 0).toFixed(1)} dB，用户端已可运行`);
  setText("adminConfigStatus", `发布成功：目标SNR ${Number(network.network.target_snr_db || 0).toFixed(1)} dB，策略 ${runtimePolicy.allocation_algorithm}`);
  adminRealtimeDigest = "";
  await pullAdminRealtimeTasks();
  await syncAdminConfigStatus();
  await refreshAdminUnifiedCompare();
}

async function updateTargetSnrAndRecompute() {
  if (state.role !== "admin" || !state.token) return;
  const targetSnr = Number(byId("targetSnrDb").value || 6.0);
  setText("adminConfigStatus", `目标SNR已切换：${targetSnr.toFixed(1)} dB，正在自动重算...`);
  const publishedNetwork = await callApi("/module/network/config", networkPayloadFromForm());
  renderAdminNetworkTopology({
    network_output: publishedNetwork,
    slicing_output: { slices: getAdminFormSlices() },
  });
  let recomputeOk = false;
  try {
    const rerun = await callApi("/system/admin/runtime-policy/recompute-current", {
      adaptation_method: "similarity",
    });
    state.adminResult = rerun;
    renderAdminTaskPanels(rerun);
    recomputeOk = true;
  } catch (error) {
    setText(
      "adminConfigStatus",
      `目标SNR已更新：${Number(publishedNetwork.network.target_snr_db || targetSnr).toFixed(1)} dB；重算失败，${error.message}`
    );
  }
  adminRealtimeDigest = "";
  await pullAdminRealtimeTasks();
  if (recomputeOk) {
    await refreshAdminUnifiedCompare();
    setText("adminConfigStatus", `目标SNR已更新并重算：${Number(publishedNetwork.network.target_snr_db || targetSnr).toFixed(1)} dB`);
  }
}

async function applyAdminRuntimePolicy() {
  const newSelected = (byId("adminRunAlgorithm") && byId("adminRunAlgorithm").value) || "semslice";
  const policyResult = await callApi("/system/admin/runtime-policy", {
    allocation_algorithm: newSelected,
  });
  try {
    adminRealtimeDigest = "";
    await pullAdminRealtimeTasks();
    await refreshAdminUnifiedCompare();
    const ts = new Date().toLocaleTimeString();
    setText("adminConfigStatus", `策略已切换：${policyResult.allocation_algorithm} @ ${ts}`);
  } catch (error) {
    setText("adminConfigStatus", `策略切换失败：${policyResult.allocation_algorithm}，${error.message}`);
  }
  return;

  const selected = (byId("adminRunAlgorithm") && byId("adminRunAlgorithm").value) || "semslice";
  const runtimePolicy = await callApi("/system/admin/runtime-policy", {
    allocation_algorithm: selected,
  });

  try {
    adminRealtimeDigest = "";
    await pullAdminRealtimeTasks();
    await refreshAdminUnifiedCompare();
    const ts = new Date().toLocaleTimeString();
    setText("adminConfigStatus", `策略已切换并重算：${runtimePolicy.allocation_algorithm} @ ${ts}`);
  } catch (error) {
    setText("adminConfigStatus", `策略切换失败：${runtimePolicy.allocation_algorithm}，${error.message}`);
  }
}

async function refreshAdminUnifiedCompare() {
  try {
    const result = await callApi("/system/admin/compare-strategies-current", {
      adaptation_method: "similarity",
    });
    renderUnifiedCompareChart(result.comparisons || []);
    setText("adminUnifiedCompareStatus", `已更新：任务 ${result.task_count || 0} 个`);
  } catch (error) {
    setText("adminUnifiedCompareStatus", error.message);
  }
}

function buildAdminRealtimeDigest(run) {
  const metrics = (run && run.performance_output && run.performance_output.user_metrics) || [];
  return JSON.stringify(
    metrics.map((m) => [
      m.user_id,
      m.delay_ms,
      m.fidelity,
      m.snr_db,
      m.s_se,
      m.task_vocab,
      m.encoded_signal_shape,
      m.encoded_signal_preview,
      m.decoded_text,
    ])
  );
}

function buildAdminBoardDigest(rows) {
  return JSON.stringify(
    (rows || []).map((r) => [
      r.user_id,
      r.updated_at,
      r.status,
      r.allocation_algorithm,
      r.slice_id || r.slice,
      Number(r.bandwidth || 0).toFixed(6),
      Number(r.power || 0).toFixed(6),
      Number(r.target_snr_db || 0).toFixed(6),
      Number(r.node_count || 0).toFixed(0),
      Number(r.base_station_count || 0).toFixed(0),
      Number(r.delay_ms || 0).toFixed(6),
      Number(r.fidelity || 0).toFixed(6),
      Number(r.s_se || 0).toFixed(6),
      Number(r.snr_db || 0).toFixed(6),
      r.task_vocab || "",
      r.encoded_signal_shape || "",
      r.encoded_signal_preview || "",
      r.decoded_text || "",
    ])
  );
}

function renderAdminBoardRows(rows, pendingRows = []) {
  const sorted = (rows || []).slice().sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
  const totalRow = sorted.find((row) => Number(row.total_bandwidth || 0) > 0 || Number(row.total_power || 0) > 0) || {};
  const totalBandwidth = Number(totalRow.total_bandwidth || byId("totalBandwidth").value || 0);
  const totalPower = Number(totalRow.total_power || byId("totalPower").value || 0);
  const boardStrategy = normalizeStrategy((sorted[0] && sorted[0].allocation_algorithm) || byId("adminRunAlgorithm").value || "semslice");
  let used = { bandwidth: 0, power: 0 };
  if (boardStrategy === "noslice") {
    used = sorted.reduce(
      (acc, row) => ({
        bandwidth: Math.max(acc.bandwidth, Number(row.bandwidth || 0)),
        power: Math.max(acc.power, Number(row.power || 0)),
      }),
      used
    );
    used.bandwidth = Math.min(totalBandwidth, used.bandwidth * RESOURCE_SLICE_COUNT);
    used.power = Math.min(totalPower, used.power * RESOURCE_SLICE_COUNT);
  } else {
    const seenSlices = new Set();
    used = sorted.reduce(
      (acc, row) => {
        const sliceKey = row.slice_id || row.slice || row.user_id;
        if (seenSlices.has(sliceKey)) return acc;
        seenSlices.add(sliceKey);
        acc.bandwidth += Number(row.bandwidth || 0);
        acc.power += Number(row.power || 0);
        return acc;
      },
      used
    );
  }
  renderAdminResourcePies({
    network_output: { network: { total_bandwidth: totalBandwidth, total_power: totalPower } },
    allocation_output: {
      remaining_resources: {
        bandwidth: Math.max(0, totalBandwidth - used.bandwidth),
        power: Math.max(0, totalPower - used.power),
      },
    },
  });
  renderAdminNetworkTopology(null, sorted, pendingRows);

  renderTable(
    "adminTaskTable",
    sorted.map((row) => ({
      user_id: row.user_id,
      strategy: row.allocation_algorithm || "-",
      requirement: row.requirement,
      task_vocab: row.task_vocab || "-",
      sample_index: row.sample_index ?? 0,
      slice: row.slice,
      bandwidth: Number(row.bandwidth || 0).toFixed(4),
      bw_share: `${((Number(row.bandwidth || 0) / Math.max(Number(row.total_bandwidth || 0), 1e-9)) * 100).toFixed(2)}%`,
      power: Number(row.power || 0).toFixed(4),
      power_share: `${((Number(row.power || 0) / Math.max(Number(row.total_power || 0), 1e-9)) * 100).toFixed(2)}%`,
      delay_ms: Number(row.delay_ms || 0).toFixed(4),
      fidelity: Number(row.fidelity || 0).toFixed(4),
      s_se: Number(row.s_se || 0).toFixed(5),
      token_match: Number(row.token_match_rate || row.fidelity || 0).toFixed(4),
      snr_db: Number(row.snr_db || 0).toFixed(4),
      source: shortText(row.source_text),
      decoded: shortText(row.decoded_text),
      model: row.model_profile || "-",
      checkpoint: row.checkpoint_name || "-",
      updated_at: row.updated_at || "-",
    }))
  );

  renderTable(
    "adminMetricQueue",
    sorted.map((row) => ({
      user_id: row.user_id,
      slice_id: row.slice_id || "-",
      delay_ms: Number(row.delay_ms || 0).toFixed(4),
      fidelity: Number(row.fidelity || 0).toFixed(4),
      s_se: Number(row.s_se || 0).toFixed(5),
      token_match: Number(row.token_match_rate || row.fidelity || 0).toFixed(4),
      snr_db: Number(row.snr_db || 0).toFixed(4),
      bandwidth: Number(row.bandwidth || 0).toFixed(4),
      power: Number(row.power || 0).toFixed(4),
      decoded: shortText(row.decoded_text),
      updated_at: row.updated_at || "-",
    }))
  );
}

function renderAdminPendingQueueRows(rows) {
  const pending = (rows || []).slice().sort((a, b) => String(b.submitted_at || "").localeCompare(String(a.submitted_at || "")));
  renderTable(
    "adminMetricQueue",
    pending.map((row) => ({
      user_id: row.user_id || "-",
      requirement: row.requirement_type || "-",
      task_vocab: row.task_vocab || "-",
      status: row.status || "待运行",
      submitted_at: row.submitted_at || "-",
    }))
  );
}

async function pullAdminRealtimeTasks() {
  if (state.role !== "admin" || !state.token) return;
  try {
    await refreshAuthStats();
    const snapshot = await callApi("/state", null, "GET");
    const selectedStrategy = normalizeStrategy(
      (byId("adminRunAlgorithm") && byId("adminRunAlgorithm").value) || snapshot.allocation_algorithm || "semslice"
    );
    const strategyBoards = snapshot.strategy_boards || {};
    const board = strategyBoards[selectedStrategy] || snapshot.admin_task_board || [];
    const pending = snapshot.pending_tasks || [];

    if (board.length) {
      const digest = buildAdminBoardDigest(board);
      if (digest !== adminRealtimeDigest) {
        adminRealtimeDigest = digest;
        renderAdminBoardRows(board, pending);
        await refreshAdminUnifiedCompare();
      }
      if (pending.length) {
        renderAdminPendingQueueRows(pending);
      }
      setText("adminRealtimeStatus", `实时同步中：累计任务 ${board.length}，待运行 ${pending.length}`);
      return;
    }

    if (pending.length) {
      renderAdminResourcePies(null);
      renderAdminNetworkTopology(null, null, pending);
      renderTable(
        "adminTaskTable",
        pending.map((row) => ({
          user_id: row.user_id || "-",
          requirement: row.requirement_type || "-",
          task_vocab: row.task_vocab || "-",
          status: row.status || "待运行",
          submitted_at: row.submitted_at || "-",
        }))
      );
      renderAdminPendingQueueRows(pending);
      setText("adminRealtimeStatus", `待运行任务 ${pending.length}，等待管理员执行`);
      return;
    }

    const strategyRuns = snapshot.strategy_runs || {};
    const run = strategyRuns[selectedStrategy] || snapshot.last_new_run;
    if (!run || !run.business_output || !run.business_output.users || !run.business_output.users.length) {
      renderAdminResourcePies(null);
      renderAdminNetworkTopology(null);
      setText("adminRealtimeStatus", "等待用户提交任务");
      return;
    }

    const digest = buildAdminRealtimeDigest(run);
    if (digest !== adminRealtimeDigest) {
      adminRealtimeDigest = digest;
      renderAdminTaskPanels(run);
      await refreshAdminUnifiedCompare();
    }
    setText("adminRealtimeStatus", `实时同步中：最新任务数 ${run.business_output.users.length}`);
  } catch (_error) {
    setText("adminRealtimeStatus", "实时同步失败");
  }
}

function buildTenantResultFromSnapshot(snapshot) {
  const strategyRuns = (snapshot && snapshot.strategy_runs) || {};
  state.tenantStrategyRuns = strategyRuns;
  const selected = syncTenantStrategySelector(strategyRuns, (snapshot && snapshot.allocation_algorithm) || "semslice");
  const run = strategyRuns[selected] || (snapshot && snapshot.last_new_run) || null;
  if (!run || !run.business_output || !run.business_output.users) return null;
  return run;
}

function syncTenantStrategySelector(strategyRuns = {}, preferredStrategy = "semslice") {
  const select = byId("tenantRunAlgorithm");
  const available = STRATEGY_ORDER.filter((key) => strategyRuns && strategyRuns[key]);
  const preferred = normalizeStrategy(preferredStrategy);
  const requested = normalizeStrategy(state.tenantSelectedStrategy || preferred);
  let selected = requested;

  if (available.length && !available.includes(selected)) {
    selected = available.includes(preferred) ? preferred : available[0];
  }

  if (select) {
    Array.from(select.options).forEach((option) => {
      option.disabled = available.length > 0 && !available.includes(option.value);
    });
    select.value = selected;
  }

  setText(
    "tenantStrategyStatus",
    available.length
      ? `当前展示：${strategyLabel(selected)}`
      : "提交任务后可切换查看三种策略结果"
  );
  return selected;
}

function renderTenantSelectedStrategy() {
  const selected = syncTenantStrategySelector(state.tenantStrategyRuns, state.tenantSelectedStrategy || "semslice");
  const result = state.tenantStrategyRuns[selected] || state.tenantResult;
  if (!result) {
    setText("tenantStrategyStatus", "暂无该策略运行数据，请先提交任务");
    return;
  }

  state.tenantResult = result;
  renderTenantPanels(result);
  tenantRealtimeDigest = buildTenantRealtimeDigest(result);
}

function renderTenantCodecResult(metrics = [], result = null) {
  const select = byId("tenantCodecTask");
  const sourceEl = byId("tenantSourceText");
  const encodedEl = byId("tenantEncodedText");
  const decodedEl = byId("tenantDecodedText");
  if (!select || !sourceEl || !encodedEl || !decodedEl) {
    renderTenantSemanticFlow(null, result);
    return;
  }

  const taskIds = new Set(tenantTasks.map((task) => String(task.task_id)));
  const rows = metrics.filter((metric) => taskIds.has(String(metric.user_id)));
  const existing = new Set(Array.from(select.options).map((option) => option.value));
  const next = new Set(rows.map((metric) => String(metric.user_id)));
  const changed = existing.size !== next.size || Array.from(next).some((id) => !existing.has(id));

  if (changed) {
    select.innerHTML = rows
      .map((metric) => `<option value="${escapeHtml(metric.user_id)}">${escapeHtml(metric.user_id)}</option>`)
      .join("");
  }

  if (rows.length && !next.has(tenantSelectedCodecTask)) {
    tenantSelectedCodecTask = rows[0].user_id;
  }
  if (rows.length) {
    select.value = tenantSelectedCodecTask;
    select.disabled = false;
  } else {
    select.innerHTML = "";
    select.disabled = true;
    tenantSelectedCodecTask = "";
  }

  const selectedMetric = rows.find((metric) => String(metric.user_id) === String(tenantSelectedCodecTask));
  sourceEl.textContent = selectedMetric && selectedMetric.source_text ? selectedMetric.source_text : "暂无数据";
  encodedEl.textContent = formatEncodedPreview(selectedMetric);
  decodedEl.textContent = selectedMetric && selectedMetric.decoded_text ? selectedMetric.decoded_text : "暂无数据";
  renderTenantSemanticFlow(selectedMetric, result);
}

function mergeTenantTasksFromResult(result) {
  const users = (result && result.business_output && result.business_output.users) || [];
  const adapts = (result && result.adaptation_output && result.adaptation_output.relations) || [];
  const metrics = (result && result.performance_output && result.performance_output.user_metrics) || [];
  if (!users.length) return;

  const sliceMap = Object.fromEntries(adapts.map((row) => [row.user_id, row.matched_slice_name]));
  const metricMap = Object.fromEntries(metrics.map((row) => [row.user_id, row]));
  const taskMap = Object.fromEntries(tenantTasks.map((task) => [task.task_id, task]));
  let maxSeq = tenantTaskSeq - 1;

  users.forEach((user) => {
    const taskId = String(user.user_id);
    const existing = taskMap[taskId];
    const nextTask = existing || {
      task_id: taskId,
      domain_type: "generic",
      status: TASK_STATUS_RUNNING,
      slice_name: "-",
    };
    nextTask.requirement_type = user.requirement_type || nextTask.requirement_type || "high_fidelity";
    nextTask.payload_symbols = Number(user.payload_symbols || nextTask.payload_symbols || 12);
    nextTask.distance_m = Number(user.distance_m || nextTask.distance_m || 2600);
    nextTask.task_pkl = user.task_pkl || nextTask.task_pkl || "test_data_en.pkl";
    nextTask.task_vocab = user.task_vocab || nextTask.task_vocab || "vocab_en.json";
    nextTask.sample_index = Number(user.sample_index || nextTask.sample_index || 0);
    nextTask.status = TASK_STATUS_RUNNING;
    nextTask.slice_name = sliceMap[taskId] || nextTask.slice_name || "-";
    const metric = metricMap[taskId] || {};
    if (metricMap[taskId]) {
      nextTask.codec_vocab = metric.task_vocab || user.task_vocab || nextTask.task_vocab || "vocab_en.json";
      nextTask.source_text = metric.source_text || "";
      nextTask.encoded_signal_shape = metric.encoded_signal_shape || "";
      nextTask.encoded_signal_preview = metric.encoded_signal_preview || "";
      nextTask.decoded_text = metric.decoded_text || "";
    }
    if (!existing) {
      tenantTasks.push(nextTask);
      taskMap[taskId] = nextTask;
    }
    const match = /^task-(\d+)$/.exec(taskId);
    if (match) {
      maxSeq = Math.max(maxSeq, Number(match[1]));
    }
  });
  tenantTaskSeq = Math.max(tenantTaskSeq, maxSeq + 1);
}

function buildTenantRealtimeDigest(result) {
  const metrics = (result && result.performance_output && result.performance_output.user_metrics) || [];
  const selected = (byId("tenantRunAlgorithm") && byId("tenantRunAlgorithm").value) || "";
  return JSON.stringify(
    [
      selected,
      metrics.map((m) => [
        m.user_id,
        m.delay_ms,
        m.fidelity,
        m.snr_db,
        m.s_se,
        m.task_vocab,
        m.encoded_signal_shape,
        m.encoded_signal_preview,
        m.decoded_text,
      ]),
    ]
  );
}

async function pullTenantRealtimeTasks() {
  if (state.role !== "user" || !state.token) return;
  try {
    const snapshot = await callApi("/state", null, "GET");
    const tenantResult = buildTenantResultFromSnapshot(snapshot);
    if (!tenantResult) return;
    const digest = buildTenantRealtimeDigest(tenantResult);
    if (digest === tenantRealtimeDigest) return;
    tenantRealtimeDigest = digest;
    state.tenantResult = tenantResult;
    mergeTenantTasksFromResult(tenantResult);
    renderTenantPanels(tenantResult);
    setText("tenantTaskStatus", `已同步最近运行结果：${(tenantResult.business_output.users || []).length} 个任务`);
  } catch (_error) {
    // keep current tenant view when realtime sync fails
  }
}

function startAdminRealtimePolling() {
  stopAdminRealtimePolling();
  pullAdminRealtimeTasks().catch(() => {});
  adminRealtimeTimer = setInterval(() => {
    pullAdminRealtimeTasks().catch(() => {});
  }, 3000);
}

function startTenantRealtimePolling() {
  stopTenantRealtimePolling();
  pullTenantRealtimeTasks().catch(() => {});
  tenantRealtimeTimer = setInterval(() => {
    pullTenantRealtimeTasks().catch(() => {});
  }, 3000);
}

function renderAdminTaskPanels(result) {
  const adapts = (result.adaptation_output && result.adaptation_output.relations) || [];
  const allocs = (result.allocation_output && result.allocation_output.allocations) || [];
  const metrics = (result.performance_output && result.performance_output.user_metrics) || [];
  const users = (result.business_output && result.business_output.users) || [];
  const network = (result.network_output && result.network_output.network) || {};
  const totalBandwidth = Number(network.total_bandwidth || 0);
  const totalPower = Number(network.total_power || 0);
  renderAdminResourcePies(result);
  renderAdminNetworkTopology(result);

  const allocMap = Object.fromEntries(allocs.map((row) => [row.user_id, row]));
  const metricMap = Object.fromEntries(metrics.map((row) => [row.user_id, row]));
  const userMap = Object.fromEntries(users.map((row) => [row.user_id, row]));

  const rows = adapts.map((row) => {
    const alloc = allocMap[row.user_id] || {};
    const metric = metricMap[row.user_id] || {};
    const business = userMap[row.user_id] || {};
    return {
      user_id: row.user_id,
      strategy: (byId("adminRunAlgorithm") && byId("adminRunAlgorithm").value) || "-",
      requirement: row.requirement_type,
      task_vocab: metric.task_vocab || business.task_vocab || "-",
      sample_index: business.sample_index ?? 0,
      slice: row.matched_slice_name,
      bandwidth: Number(alloc.bandwidth || 0).toFixed(4),
      bw_share: `${((Number(alloc.bandwidth || 0) / Math.max(totalBandwidth, 1e-9)) * 100).toFixed(2)}%`,
      power: Number(alloc.power || 0).toFixed(4),
      power_share: `${((Number(alloc.power || 0) / Math.max(totalPower, 1e-9)) * 100).toFixed(2)}%`,
      delay_ms: Number(metric.delay_ms || 0).toFixed(4),
      fidelity: Number(metric.fidelity || 0).toFixed(4),
      s_se: Number(metric.s_se || 0).toFixed(5),
      token_match: Number(metric.token_match_rate || metric.fidelity || 0).toFixed(4),
      snr_db: Number(metric.snr_db || 0).toFixed(4),
      source: shortText(metric.source_text),
      encoded: shortText(metric.encoded_signal_preview),
      decoded: shortText(metric.decoded_text),
      model: metric.model_profile || "-",
      checkpoint: metric.checkpoint_name || "-",
    };
  });

  renderTable("adminTaskTable", rows);

  const queueRows = metrics.map((m) => ({
    user_id: m.user_id,
    slice_id: m.slice_id,
    delay_ms: Number(m.delay_ms || 0).toFixed(4),
    fidelity: Number(m.fidelity || 0).toFixed(4),
    s_se: Number(m.s_se || 0).toFixed(5),
    token_match: Number(m.token_match_rate || m.fidelity || 0).toFixed(4),
    snr_db: Number(m.snr_db || 0).toFixed(4),
    bandwidth: Number(m.bandwidth || 0).toFixed(4),
    bw_share: `${((Number(m.bandwidth || 0) / Math.max(totalBandwidth, 1e-9)) * 100).toFixed(2)}%`,
    power: Number(m.power || 0).toFixed(4),
    power_share: `${((Number(m.power || 0) / Math.max(totalPower, 1e-9)) * 100).toFixed(2)}%`,
    encoded: shortText(m.encoded_signal_preview),
    decoded: shortText(m.decoded_text),
  }));
  renderTable("adminMetricQueue", queueRows);
}

function renderTenantTaskTable() {
  const rows = tenantTasks.map((task) => ({
    task_id: task.task_id,
    requirement: task.requirement_type,
    domain: task.domain_type,
    payload_symbols: task.payload_symbols,
    distance_m: task.distance_m,
    status: task.status,
    slice: task.slice_name || "-",
  }));
  renderTable("tenantTaskTable", rows);
}

function addTenantTask() {
  const task = {
    task_id: `task-${tenantTaskSeq++}`,
    requirement_type: byId("tenantReq").value,
    domain_type: "generic",
    payload_symbols: Number(byId("tenantPayload").value || 12),
    distance_m: Number(byId("tenantDistance").value || 2600),
    status: "未提交",
    slice_name: "-",
  };
  tenantTasks.push(task);
  renderTenantTaskTable();
  setText("tenantTaskStatus", `已添加任务 ${task.task_id}，当前总任务 ${tenantTasks.length}`);
}

function tenantSubmitBusinessPayload(tasksToSubmit = null) {
  const submitted =
    tasksToSubmit && tasksToSubmit.length
      ? tasksToSubmit
      : tenantTasks.filter((task) => task.status !== "已运行");
  if (!submitted.length) {
    throw new Error("没有可提交的新任务，请先添加任务");
  }

  return {
    user_count: submitted.length,
    modality: "text",
    default_requirement_type: "high_fidelity",
    default_domain_type: "generic",
    users: submitted.map((task) => ({
      user_id: task.task_id,
      modality: "text",
      requirement_type: task.requirement_type,
      domain_type: task.domain_type,
      payload_symbols: task.payload_symbols,
      distance_m: task.distance_m,
      base_similarity: task.domain_type === "animal" ? 0.74 : task.domain_type === "music" ? 0.71 : 0.69,
    })),
  };
}

function renderTenantPanels(result) {
  mergeTenantTasksFromResult(result);
  const allocs = (result.allocation_output && result.allocation_output.allocations) || [];
  const metrics = (result.performance_output && result.performance_output.user_metrics) || [];
  const adapts = (result.adaptation_output && result.adaptation_output.relations) || [];

  const sliceMap = Object.fromEntries(adapts.map((row) => [row.user_id, row.matched_slice_name]));
  const metricMap = Object.fromEntries(metrics.map((row) => [row.user_id, row]));
  tenantTasks.forEach((task) => {
    if (sliceMap[task.task_id]) task.slice_name = sliceMap[task.task_id];
  });
  renderTenantTaskTable();

  renderTable(
    "tenantAllocTable",
    allocs.map((row) => ({
      task_id: row.user_id,
      slice_id: row.slice_id,
      bandwidth: Number(row.bandwidth || 0).toFixed(4),
      power: Number(row.power || 0).toFixed(4),
      s_se: Number((metricMap[row.user_id] && metricMap[row.user_id].s_se) || 0).toFixed(5),
      token_match: Number((metricMap[row.user_id] && metricMap[row.user_id].token_match_rate) || 0).toFixed(4),
      source: shortText(metricMap[row.user_id] && metricMap[row.user_id].source_text),
      encoded: shortText(metricMap[row.user_id] && metricMap[row.user_id].encoded_signal_preview),
      decoded: shortText(metricMap[row.user_id] && metricMap[row.user_id].decoded_text),
    }))
  );
  renderTenantCodecResult(metrics, result);

  renderBars(
    "tenantDelayBars",
    metrics.map((m) => ({ label: m.user_id, value: Number(m.delay_ms || 0) })),
    "value"
  );
  renderBars(
    "tenantFidelityBars",
    metrics.map((m) => ({ label: m.user_id, value: Number(m.fidelity || 0) })),
    "value",
    1
  );
}

async function submitTenantTasks() {
  if (!tenantTasks.length) {
    throw new Error("请先添加任务");
  }
  const tasksToSubmit = tenantTasks.filter((task) => task.status !== "已运行");
  if (!tasksToSubmit.length) {
    throw new Error("没有可提交的新任务，请先添加任务");
  }
  tasksToSubmit.forEach((task) => {
    task.status = "已提交";
  });
  renderTenantTaskTable();

  const result = await callApi("/system/user/submit", tenantSubmitBusinessPayload(tasksToSubmit));
  const runResult = result.run_result || result.result || null;

  if (runResult) {
    state.tenantResult = runResult;
    mergeTenantTasksFromResult(runResult);
    const submittedSet = new Set(tasksToSubmit.map((task) => task.task_id));
    tenantTasks.forEach((task) => {
      if (submittedSet.has(task.task_id)) {
        task.status = "已运行";
      }
    });
    renderTenantPanels(runResult);
    tenantRealtimeDigest = buildTenantRealtimeDigest(runResult);

    const core =
      result.core_metrics ||
      (runResult.performance_output && runResult.performance_output.core_metrics) ||
      {};
    setText(
      "tenantTaskStatus",
              `提交并实时运行完成：${result.submitted_count || 0} 个，平均时延 ${Number(core.avg_delay_ms || 0).toFixed(4)}，平均保真度 ${Number(core.avg_fidelity || 0).toFixed(4)}`
    );
    return;
  }

  setText("tenantTaskStatus", `提交成功：本次 ${result.submitted_count || 0} 个，待运行总数 ${result.pending_total || 0}`);
}

function ensureTenantDatasetSelectors() {
  if (byId("tenantPkl")) return;
  const tenantReqEl = byId("tenantReq");
  if (!tenantReqEl) return;
  const formGrid = tenantReqEl.closest(".form-grid");
  if (!formGrid) return;

  const pklRow = document.createElement("div");
  pklRow.className = "form-row";
  pklRow.innerHTML =
    '<label>任务 PKL</label><select id="tenantPkl"><option value="test_data_en.pkl">test_data_en.pkl</option><option value="test_data-en90%.pkl">test_data-en90%.pkl</option><option value="test_data-en80%.pkl">test_data-en80%.pkl</option></select>';

  const sampleRow = document.createElement("div");
  sampleRow.className = "form-row";
  sampleRow.innerHTML = '<label>样本序号</label><input id="tenantSampleIndex" type="number" min="0" step="1" value="0" />';

  formGrid.appendChild(pklRow);
  formGrid.appendChild(sampleRow);
}

async function fetchSystemConfigStatus() {
  return callApi("/system/config/status", null, "GET");
}

async function syncTenantConfigStatus() {
  try {
    const cfg = await fetchSystemConfigStatus();
    if (cfg.admin_config_ready) {
      setText("tenantTaskStatus", "管理员配置已下发，可提交任务");
    } else {
      setText("tenantTaskStatus", "管理员尚未下发网络与切片配置，暂不可提交任务");
    }
    return cfg;
  } catch (_error) {
    setText("tenantTaskStatus", "配置状态读取失败，请稍后重试");
    return null;
  }
}

async function ensureTenantConfigReady() {
  const cfg = await fetchSystemConfigStatus();
  if (!cfg.admin_config_ready) {
    throw new Error("管理员尚未下发网络与切片配置，暂不可提交任务");
  }
}

function resolveTaskSimilarity(task) {
  return VOCAB_BASE_SIM_MAP[task.task_vocab] || 0.72;
}

function displayTaskStatus(status) {
  if (status === TASK_STATUS_PENDING) return "未提交";
  if (status === TASK_STATUS_SUBMITTED) return "已提交";
  if (status === TASK_STATUS_RUNNING) return "已运行";
  return status || "-";
}

function renderTenantTaskTable() {
  const rows = tenantTasks.map((task) => ({
    task_id: task.task_id,
    requirement: task.requirement_type,
    task_vocab: task.codec_vocab || task.task_vocab || "-",
    sample_index: task.sample_index ?? 0,
    payload_symbols: task.payload_symbols,
    distance_m: task.distance_m,
    task_pkl: task.task_pkl || "-",
    status: displayTaskStatus(task.status),
    slice: task.slice_name || "-",
  }));
  renderTable("tenantTaskTable", rows);
}

function addTenantTask() {
  const pklEl = byId("tenantPkl");
  const sampleEl = byId("tenantSampleIndex");
  const taskPkl = pklEl ? pklEl.value : "test_data_en.pkl";
  const task = {
    task_id: `task-${tenantTaskSeq++}`,
    requirement_type: byId("tenantReq").value,
    domain_type: "generic",
    payload_symbols: Number(byId("tenantPayload").value || 12),
    distance_m: Number(byId("tenantDistance").value || 2600),
    task_pkl: taskPkl,
    task_vocab: PKL_VOCAB_MAP[taskPkl] || "vocab_en.json",
    sample_index: sampleEl ? Number(sampleEl.value || 0) : 0,
    status: TASK_STATUS_PENDING,
    slice_name: "-",
  };
  tenantTasks.push(task);
  renderTenantTaskTable();
  setText("tenantTaskStatus", `已添加任务 ${task.task_id}，当前总任务 ${tenantTasks.length}`);
}

function tenantSubmitBusinessPayload(tasksToSubmit = null) {
  const submitted =
    tasksToSubmit && tasksToSubmit.length
      ? tasksToSubmit
      : tenantTasks.filter((task) => task.status !== TASK_STATUS_RUNNING);
  if (!submitted.length) {
    throw new Error("没有可提交的新任务，请先添加任务");
  }

  return {
    user_count: submitted.length,
    modality: "text",
    default_requirement_type: "high_fidelity",
    default_domain_type: "generic",
    users: submitted.map((task) => ({
      user_id: task.task_id,
      modality: "text",
      requirement_type: task.requirement_type,
      domain_type: "generic",
      payload_symbols: task.payload_symbols,
      distance_m: task.distance_m,
      base_similarity: resolveTaskSimilarity(task),
      task_pkl: task.task_pkl,
      task_vocab: task.task_vocab,
      sample_index: task.sample_index,
    })),
  };
}

async function submitTenantTasks() {
  if (!tenantTasks.length) {
    throw new Error("请先添加任务");
  }
  await ensureTenantConfigReady();

  const tasksToSubmit = tenantTasks.filter((task) => task.status !== TASK_STATUS_RUNNING);
  if (!tasksToSubmit.length) {
    throw new Error("没有可提交的新任务，请先添加任务");
  }

  const statusBackup = new Map(tasksToSubmit.map((task) => [task.task_id, task.status]));
  tasksToSubmit.forEach((task) => {
    task.status = TASK_STATUS_SUBMITTED;
  });
  renderTenantTaskTable();

  let result = null;
  try {
    result = await callApi("/system/user/submit", tenantSubmitBusinessPayload(tasksToSubmit));
  } catch (error) {
    tasksToSubmit.forEach((task) => {
      task.status = statusBackup.get(task.task_id) || TASK_STATUS_PENDING;
    });
    renderTenantTaskTable();
    throw error;
  }
  const runResult = result.run_result || result.result || null;

  if (runResult) {
    let displayResult = runResult;
    try {
      const snapshot = await callApi("/state", null, "GET");
      displayResult = buildTenantResultFromSnapshot(snapshot) || runResult;
    } catch (_error) {
      state.tenantStrategyRuns = {};
      syncTenantStrategySelector({}, "semslice");
    }

    state.tenantResult = displayResult;
    mergeTenantTasksFromResult(displayResult);
    const submittedSet = new Set(tasksToSubmit.map((task) => task.task_id));
    tenantTasks.forEach((task) => {
      if (submittedSet.has(task.task_id)) {
        task.status = TASK_STATUS_RUNNING;
      }
    });
    renderTenantPanels(displayResult);
    tenantRealtimeDigest = buildTenantRealtimeDigest(displayResult);

    const core =
      result.core_metrics ||
      (displayResult.performance_output && displayResult.performance_output.core_metrics) ||
      {};
    setText(
      "tenantTaskStatus",
              `提交并实时运行完成：${result.submitted_count || 0} 个，平均时延 ${Number(core.avg_delay_ms || 0).toFixed(4)}，平均保真度 ${Number(core.avg_fidelity || 0).toFixed(4)}`
    );
    return;
  }

  setText("tenantTaskStatus", `提交成功：本次 ${result.submitted_count || 0} 个，待运行总数 ${result.pending_total || 0}`);
}

function bindEvents() {
  byId("loginBtn").addEventListener("click", () => login().catch((e) => setText("loginStatus", e.message)));
  byId("logoutBtn").addEventListener("click", () => logout().catch(() => resetToLogin()));

  byId("systemType").addEventListener("change", (event) => {
    if (event.target.value === "admin") {
      byId("username").value = "admin";
      byId("password").value = "admin123";
    } else {
      byId("username").value = "user1";
      byId("password").value = "user123";
    }
  });

  byId("adminPublishBtn").addEventListener("click", () => publishAdminConfig().catch((e) => setText("adminConfigStatus", e.message)));
  const targetSnrEl = byId("targetSnrDb");
  if (targetSnrEl) {
    targetSnrEl.addEventListener("change", () => {
      updateTargetSnrAndRecompute().catch((e) => setText("adminConfigStatus", e.message));
    });
  }
  ["sliceCount", "sliceNames", "kbJson", "totalBandwidth", "totalPower", "networkNodeCount", "baseStationCount"].forEach((id) => {
    const el = byId(id);
    if (!el) return;
    el.addEventListener("input", () => renderAdminNetworkTopology(null));
    el.addEventListener("change", () => renderAdminNetworkTopology(null));
  });
  const adminAlgoEl = byId("adminRunAlgorithm");
  if (adminAlgoEl) {
    const applyPolicyFromSelector = () => {
      setText("adminConfigStatus", "策略切换中...");
      applyAdminRuntimePolicy().catch((e) => setText("adminConfigStatus", e.message));
    };
    adminAlgoEl.addEventListener("change", applyPolicyFromSelector);
    adminAlgoEl.addEventListener("input", applyPolicyFromSelector);
  }
  ensureTenantDatasetSelectors();
  const tenantAlgoEl = byId("tenantRunAlgorithm");
  if (tenantAlgoEl) {
    tenantAlgoEl.addEventListener("change", () => {
      state.tenantSelectedStrategy = normalizeStrategy(tenantAlgoEl.value);
      renderTenantSelectedStrategy();
    });
  }
  const tenantCodecTaskEl = byId("tenantCodecTask");
  if (tenantCodecTaskEl) {
    tenantCodecTaskEl.addEventListener("change", () => {
      tenantSelectedCodecTask = tenantCodecTaskEl.value;
      const metrics = (state.tenantResult && state.tenantResult.performance_output && state.tenantResult.performance_output.user_metrics) || [];
      renderTenantCodecResult(metrics, state.tenantResult);
    });
  }
  byId("addTaskBtn").addEventListener("click", () => {
    try {
      addTenantTask();
    } catch (error) {
      setText("tenantTaskStatus", error.message);
    }
  });
  byId("submitTaskBtn").addEventListener("click", () => submitTenantTasks().catch((e) => setText("tenantTaskStatus", e.message)));
}

bindEvents();
resetToLogin();
