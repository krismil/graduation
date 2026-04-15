const state = {
  token: null,
  role: null,
  user: null,
  adminResult: null,
  tenantResult: null,
};

const tenantTasks = [];
let tenantTaskSeq = 1;
let adminRealtimeTimer = null;
let adminRealtimeDigest = "";
let tenantRealtimeTimer = null;
let tenantRealtimeDigest = "";
const TASK_STATUS_PENDING = "PENDING";
const TASK_STATUS_SUBMITTED = "SUBMITTED";
const TASK_STATUS_RUNNING = "RUNNING";
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

function normalizeStrategy(raw) {
  const value = String(raw || "semslice").toLowerCase().trim();
  if (value === "random" || value === "no_slice") return "noslice";
  if (value === "semantic" || value === "semantic_slice" || value === "pso") return "semslice";
  if (value === "weighted" || value === "latency_first") return "netslice";
  return value === "semslice" || value === "netslice" || value === "noslice" ? value : "semslice";
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
  const head = keys.map((k) => `<th>${k}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${keys.map((k) => `<td>${row[k] ?? "-"}</td>`).join("")}</tr>`)
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

function renderUnifiedCompareChart(comparisons) {
  const root = byId("adminUnifiedCompare");
  if (!root) return;
  if (!comparisons || !comparisons.length) {
    root.innerHTML = '<div class="status">暂无可对比数据</div>';
    return;
  }

  const metrics = [
    { key: "avg_delay_ms", title: "平均时延 (ms)", digits: 3 },
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
    cpu_capacity: Number(byId("cpuCapacity").value || 120),
    compute_energy_threshold: Number(byId("energyThreshold").value || 650),
    total_bandwidth: Number(byId("totalBandwidth").value || 2.4),
    total_power: Number(byId("totalPower").value || 1.2),
    channel_scenario: byId("channelScenario").value,
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
  setText("sessionText", `当前登录：${state.user.username}（${state.role}）`);
}

function resetToLogin() {
  state.token = null;
  state.role = null;
  state.user = null;
  state.adminResult = null;
  state.tenantResult = null;
  tenantTasks.length = 0;
  tenantTaskSeq = 1;
  adminRealtimeDigest = "";
  tenantRealtimeDigest = "";
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

    byId("cpuCapacity").value = network.cpu_capacity ?? 120;
    byId("energyThreshold").value = network.compute_energy_threshold ?? 650;
    byId("totalBandwidth").value = network.total_bandwidth ?? 2.4;
    byId("totalPower").value = network.total_power ?? 1.2;
    byId("channelScenario").value = network.channel_scenario || "snr_6";

    byId("sliceCount").value = slicing.slice_count ?? 3;
    byId("sliceNames").value = (slicing.slice_names || []).join(",");
    byId("codecCount").value = slicing.codec_count ?? 3;
    byId("kbJson").value = JSON.stringify(slicing.knowledge_bases || [], null, 2);
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
  } catch (_error) {
    setText("adminConfigStatus", "配置状态读取失败");
  }
}

async function publishAdminConfig() {
  let recomputeOk = false;
  const publishedNetwork = await callApi("/module/network/config", networkPayloadFromForm());
  const publishedSlicing = await callApi("/module/slice/config", slicePayloadFromForm());
  const publishedSliceCount = (publishedSlicing.slices || []).length;
  setText("adminSliceStatus", `切片已下发：共 ${publishedSliceCount} 个切片实例`);
  setText("adminConfigStatus", `配置已下发：场景 ${publishedNetwork.network.channel_scenario}，正在按当前策略重算`);
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
      `配置已下发：场景 ${publishedNetwork.network.channel_scenario}；当前无可重算任务（${error.message}）`
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
  setText("adminConfigStatus", `发布成功：场景 ${network.network.channel_scenario}，用户端已可运行`);
  setText("adminConfigStatus", `发布成功：场景 ${network.network.channel_scenario}，策略 ${runtimePolicy.allocation_algorithm}`);
  adminRealtimeDigest = "";
  await pullAdminRealtimeTasks();
  await syncAdminConfigStatus();
  await refreshAdminUnifiedCompare();
}

async function updateChannelScenarioAndRecompute() {
  if (state.role !== "admin" || !state.token) return;
  const selectedScenario = byId("channelScenario").value || "snr_6";
  setText("adminConfigStatus", `信道已切换：${selectedScenario}，正在自动重算...`);
  const publishedNetwork = await callApi("/module/network/config", networkPayloadFromForm());
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
      `信道已更新：${publishedNetwork.network.channel_scenario}；重算失败（${error.message}）`
    );
  }
  adminRealtimeDigest = "";
  await pullAdminRealtimeTasks();
  if (recomputeOk) {
    await refreshAdminUnifiedCompare();
    setText("adminConfigStatus", `信道已更新并重算：${publishedNetwork.network.channel_scenario}`);
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
    setText("adminConfigStatus", `策略已切换（仅更新显示）：${policyResult.allocation_algorithm} @ ${ts}`);
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
  return JSON.stringify(metrics.map((m) => [m.user_id, m.delay_ms, m.fidelity, m.snr_db]));
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
      Number(r.compute || 0).toFixed(6),
      Number(r.delay_ms || 0).toFixed(6),
      Number(r.fidelity || 0).toFixed(6),
      Number(r.snr_db || 0).toFixed(6),
    ])
  );
}

function renderAdminBoardRows(rows) {
  const sorted = (rows || []).slice().sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));

  renderTable(
    "adminTaskTable",
    sorted.map((row) => ({
      user_id: row.user_id,
      strategy: row.allocation_algorithm || "-",
      requirement: row.requirement,
      task_vocab: row.task_vocab || "-",
      slice: row.slice,
      bandwidth: Number(row.bandwidth || 0).toFixed(4),
      bw_share: `${((Number(row.bandwidth || 0) / Math.max(Number(row.total_bandwidth || 0), 1e-9)) * 100).toFixed(2)}%`,
      power: Number(row.power || 0).toFixed(4),
      power_share: `${((Number(row.power || 0) / Math.max(Number(row.total_power || 0), 1e-9)) * 100).toFixed(2)}%`,
      compute: Number(row.compute || 0).toFixed(4),
      compute_share: `${((Number(row.compute || 0) / Math.max(Number(row.total_compute || 0), 1e-9)) * 100).toFixed(2)}%`,
      delay_ms: Number(row.delay_ms || 0).toFixed(4),
      fidelity: Number(row.fidelity || 0).toFixed(4),
      snr_db: Number(row.snr_db || 0).toFixed(4),
      status: row.status || "-",
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
      snr_db: Number(row.snr_db || 0).toFixed(4),
      bandwidth: Number(row.bandwidth || 0).toFixed(4),
      power: Number(row.power || 0).toFixed(4),
      compute: Number(row.compute || 0).toFixed(4),
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
        renderAdminBoardRows(board);
        await refreshAdminUnifiedCompare();
      }
      if (pending.length) {
        renderAdminPendingQueueRows(pending);
      }
      setText("adminRealtimeStatus", `实时同步中：累计任务 ${board.length}，待运行 ${pending.length}`);
      return;
    }

    if (pending.length) {
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
  const selected = normalizeStrategy((snapshot && snapshot.allocation_algorithm) || "semslice");
  const run = strategyRuns[selected] || (snapshot && snapshot.last_new_run) || null;
  if (!run || !run.business_output || !run.business_output.users) return null;
  return run;
}

function mergeTenantTasksFromResult(result) {
  const users = (result && result.business_output && result.business_output.users) || [];
  const adapts = (result && result.adaptation_output && result.adaptation_output.relations) || [];
  if (!users.length) return;

  const sliceMap = Object.fromEntries(adapts.map((row) => [row.user_id, row.matched_slice_name]));
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
    nextTask.status = TASK_STATUS_RUNNING;
    nextTask.slice_name = sliceMap[taskId] || nextTask.slice_name || "-";
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
  return JSON.stringify(metrics.map((m) => [m.user_id, m.delay_ms, m.fidelity, m.snr_db]));
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
  const totalCompute = Number(network.cpu_capacity || 0);

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
      task_vocab: business.task_vocab || "-",
      slice: row.matched_slice_name,
      bandwidth: Number(alloc.bandwidth || 0).toFixed(4),
      bw_share: `${((Number(alloc.bandwidth || 0) / Math.max(totalBandwidth, 1e-9)) * 100).toFixed(2)}%`,
      power: Number(alloc.power || 0).toFixed(4),
      power_share: `${((Number(alloc.power || 0) / Math.max(totalPower, 1e-9)) * 100).toFixed(2)}%`,
      compute: Number(alloc.compute || 0).toFixed(4),
      compute_share: `${((Number(alloc.compute || 0) / Math.max(totalCompute, 1e-9)) * 100).toFixed(2)}%`,
      delay_ms: Number(metric.delay_ms || 0).toFixed(4),
      fidelity: Number(metric.fidelity || 0).toFixed(4),
      snr_db: Number(metric.snr_db || 0).toFixed(4),
      status: metric.pass ? "通过" : "未通过",
    };
  });

  renderTable("adminTaskTable", rows);

  const queueRows = metrics.map((m) => ({
    user_id: m.user_id,
    slice_id: m.slice_id,
    delay_ms: Number(m.delay_ms || 0).toFixed(4),
    fidelity: Number(m.fidelity || 0).toFixed(4),
    snr_db: Number(m.snr_db || 0).toFixed(4),
    bandwidth: Number(m.bandwidth || 0).toFixed(4),
    bw_share: `${((Number(m.bandwidth || 0) / Math.max(totalBandwidth, 1e-9)) * 100).toFixed(2)}%`,
    power: Number(m.power || 0).toFixed(4),
    power_share: `${((Number(m.power || 0) / Math.max(totalPower, 1e-9)) * 100).toFixed(2)}%`,
    compute: Number(m.compute || 0).toFixed(4),
    compute_share: `${((Number(m.compute || 0) / Math.max(totalCompute, 1e-9)) * 100).toFixed(2)}%`,
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
      compute: Number(row.compute || 0).toFixed(4),
      energy_cost: Number(row.energy_cost || 0).toFixed(4),
    }))
  );

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
  if (byId("tenantPkl") && byId("tenantVocab")) return;
  const tenantReqEl = byId("tenantReq");
  if (!tenantReqEl) return;
  const formGrid = tenantReqEl.closest(".form-grid");
  if (!formGrid) return;

  const pklRow = document.createElement("div");
  pklRow.className = "form-row";
  pklRow.innerHTML =
    '<label>任务 PKL</label><select id="tenantPkl"><option value="test_data_en.pkl">test_data_en.pkl</option><option value="test_data-en90%.pkl">test_data-en90%.pkl</option><option value="test_data-en80%.pkl">test_data-en80%.pkl</option></select>';

  const vocabRow = document.createElement("div");
  vocabRow.className = "form-row";
  vocabRow.innerHTML =
    '<label>词表 JSON</label><select id="tenantVocab"><option value="vocab_en.json">vocab_en.json</option><option value="vocab_en90%.json">vocab_en90%.json</option><option value="vocab_en80%.json">vocab_en80%.json</option></select>';

  formGrid.appendChild(pklRow);
  formGrid.appendChild(vocabRow);
}

function syncTenantPklVocab() {
  const pklEl = byId("tenantPkl");
  const vocabEl = byId("tenantVocab");
  if (!pklEl || !vocabEl) return;
  vocabEl.value = PKL_VOCAB_MAP[pklEl.value] || "vocab_en.json";
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
    task_vocab: task.task_vocab || "-",
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
  const vocabEl = byId("tenantVocab");
  const task = {
    task_id: `task-${tenantTaskSeq++}`,
    requirement_type: byId("tenantReq").value,
    domain_type: "generic",
    payload_symbols: Number(byId("tenantPayload").value || 12),
    distance_m: Number(byId("tenantDistance").value || 2600),
    task_pkl: pklEl ? pklEl.value : "test_data_en.pkl",
    task_vocab: vocabEl ? vocabEl.value : "vocab_en.json",
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
    state.tenantResult = runResult;
    mergeTenantTasksFromResult(runResult);
    const submittedSet = new Set(tasksToSubmit.map((task) => task.task_id));
    tenantTasks.forEach((task) => {
      if (submittedSet.has(task.task_id)) {
        task.status = TASK_STATUS_RUNNING;
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
  const channelScenarioEl = byId("channelScenario");
  if (channelScenarioEl) {
    channelScenarioEl.addEventListener("change", () => {
      updateChannelScenarioAndRecompute().catch((e) => setText("adminConfigStatus", e.message));
    });
  }
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
  const tenantPklEl = byId("tenantPkl");
  if (tenantPklEl) {
    tenantPklEl.addEventListener("change", syncTenantPklVocab);
    syncTenantPklVocab();
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
