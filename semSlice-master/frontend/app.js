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
            <div class="metric-bar-item">
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
  } else {
    stopAdminRealtimePolling();
  }
  byId("activeCount").classList.toggle("hidden", !isAdmin);
  byId("adminView").classList.toggle("hidden", !isAdmin);
  byId("tenantView").classList.toggle("hidden", isAdmin);
  setText("pageTitle", isAdmin ? "管理员仪表盘" : "租户任务中心");
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
  stopAdminRealtimePolling();

  byId("appView").classList.add("hidden");
  byId("appView").style.display = "none";
  byId("loginView").classList.remove("hidden");
  byId("loginView").style.display = "";
  setText("loginStatus", "未登录");
}

async function refreshAuthStats() {
  try {
    const stats = await callApi("/auth/stats", null, "GET");
    setText("activeCount", `在线租户 ${stats.active_tenant_count || 0}`);
  } catch (_error) {
    setText("activeCount", "在线租户 -");
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
    byId("channelScenario").value = network.channel_scenario || "factory_indoor";

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
    if (cfg.admin_config_ready) {
      setText("adminConfigStatus", "已发布：网络与切片配置已生效");
      setText("adminSliceStatus", "切片配置已发布，租户可提交运行任务");
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
  const network = await callApi("/module/network/config", networkPayloadFromForm());
  const slicing = await callApi("/module/slice/config", slicePayloadFromForm());
  const sliceCount = (slicing.slices || []).length;
  setText("adminSliceStatus", `切片已发布：共 ${sliceCount} 个切片实例`);
  setText("adminConfigStatus", `发布成功：场景 ${network.network.channel_scenario}，租户端已可运行`);
  await syncAdminConfigStatus();
}

async function runAdminQueuedTasks() {
  const result = await callApi("/system/admin/run-submitted", {
    adaptation_method: "similarity",
    allocation_algorithm: byId("adminRunAlgorithm").value,
  });
  state.adminResult = result;
  renderAdminTaskPanels(result);
  const used = (result.allocation_output && result.allocation_output.used_resources) || {};
  const total = (result.network_output && result.network_output.network) || {};
  setText(
    "adminRunStatus",
    `运行完成：处理任务 ${result.business_output.users.length} 个；带宽 ${Number(used.bandwidth || 0).toFixed(3)}/${Number(total.total_bandwidth || 0).toFixed(3)}，功率 ${Number(used.power || 0).toFixed(3)}/${Number(total.total_power || 0).toFixed(3)}`
  );
  await refreshAdminUnifiedCompare();
  await pullAdminRealtimeTasks();
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
  return JSON.stringify((rows || []).map((r) => [r.tenant_id, r.user_id, r.updated_at, r.status]));
}

function renderAdminBoardRows(rows) {
  const sorted = (rows || []).slice().sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));

  renderTable(
    "adminTaskTable",
    sorted.map((row) => ({
      tenant_id: row.tenant_id,
      user_id: row.user_id,
      requirement: row.requirement,
      domain: row.domain,
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
      tenant_id: row.tenant_id,
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
      tenant_id: row.tenant_id || "-",
      user_id: row.user_id || "-",
      requirement: row.requirement_type || "-",
      domain: row.domain_type || "-",
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
    const board = snapshot.admin_task_board || [];
    const pending = snapshot.pending_tasks || [];

    if (board.length) {
      const digest = buildAdminBoardDigest(board);
      if (digest !== adminRealtimeDigest) {
        adminRealtimeDigest = digest;
        renderAdminBoardRows(board);
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
          tenant_id: row.tenant_id || "-",
          user_id: row.user_id || "-",
          requirement: row.requirement_type || "-",
          domain: row.domain_type || "-",
          status: row.status || "待运行",
          submitted_at: row.submitted_at || "-",
        }))
      );
      renderAdminPendingQueueRows(pending);
      setText("adminRealtimeStatus", `待运行任务 ${pending.length}，等待管理员执行`);
      return;
    }

    const run = snapshot.last_new_run;
    if (!run || !run.business_output || !run.business_output.users || !run.business_output.users.length) {
      setText("adminRealtimeStatus", "等待租户提交任务");
      return;
    }

    const digest = buildAdminRealtimeDigest(run);
    if (digest !== adminRealtimeDigest) {
      adminRealtimeDigest = digest;
      renderAdminTaskPanels(run);
    }
    setText("adminRealtimeStatus", `实时同步中：最新任务数 ${run.business_output.users.length}`);
  } catch (_error) {
    setText("adminRealtimeStatus", "实时同步失败");
  }
}

function startAdminRealtimePolling() {
  stopAdminRealtimePolling();
  pullAdminRealtimeTasks().catch(() => {});
  adminRealtimeTimer = setInterval(() => {
    pullAdminRealtimeTasks().catch(() => {});
  }, 3000);
}

function renderAdminTaskPanels(result) {
  const adapts = (result.adaptation_output && result.adaptation_output.relations) || [];
  const allocs = (result.allocation_output && result.allocation_output.allocations) || [];
  const metrics = (result.performance_output && result.performance_output.user_metrics) || [];
  const network = (result.network_output && result.network_output.network) || {};
  const totalBandwidth = Number(network.total_bandwidth || 0);
  const totalPower = Number(network.total_power || 0);
  const totalCompute = Number(network.cpu_capacity || 0);

  const allocMap = Object.fromEntries(allocs.map((row) => [row.user_id, row]));
  const metricMap = Object.fromEntries(metrics.map((row) => [row.user_id, row]));

  const rows = adapts.map((row) => {
    const alloc = allocMap[row.user_id] || {};
    const metric = metricMap[row.user_id] || {};
    return {
      user_id: row.user_id,
      tenant_id: row.tenant_id,
      requirement: row.requirement_type,
      domain: row.domain_type,
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
    domain_type: byId("tenantDomain").value,
    payload_symbols: Number(byId("tenantPayload").value || 12),
    distance_m: Number(byId("tenantDistance").value || 2600),
    status: "未提交",
    slice_name: "-",
  };
  tenantTasks.push(task);
  renderTenantTaskTable();
  setText("tenantTaskStatus", `已添加任务 ${task.task_id}，当前总任务 ${tenantTasks.length}`);
}

function tenantSubmitBusinessPayload() {
  const submitted = tenantTasks.filter((task) => task.status === "已提交");
  if (!submitted.length) {
    throw new Error("请先添加任务并提交");
  }

  return {
    user_count: submitted.length,
    modality: "text",
    default_requirement_type: "high_fidelity",
    default_domain_type: "animal",
    tenant_id: state.user.tenant_id || "tenant-1",
    users: submitted.map((task) => ({
      user_id: task.task_id,
      tenant_id: state.user.tenant_id || "tenant-1",
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
  tenantTasks.forEach((task) => {
    if (task.status === "未提交") task.status = "已提交";
  });

  const result = await callApi("/system/tenant/submit", tenantSubmitBusinessPayload());
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
      byId("username").value = "tenant1";
      byId("password").value = "tenant123";
    }
  });

  byId("adminPublishBtn").addEventListener("click", () => publishAdminConfig().catch((e) => setText("adminConfigStatus", e.message)));
  byId("adminRunQueuedBtn").addEventListener("click", () => runAdminQueuedTasks().catch((e) => setText("adminRunStatus", e.message)));
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
