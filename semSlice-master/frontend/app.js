const state = {
  token: null,
  role: null,
  user: null,
  businessOutput: null,
  networkOutput: null,
  slicingOutput: null,
  adaptationOutput: null,
  allocationOutput: null,
  performanceOutput: null,
};

const outputBox = document.getElementById("outputBox");
const metricCards = document.getElementById("metricCards");
const fidelityChart = document.getElementById("fidelityChart");
const delayChart = document.getElementById("delayChart");
const remainingPieChart = document.getElementById("remainingPieChart");
const resourceBreakdown = document.getElementById("resourceBreakdown");
const remainingPieLegend = document.getElementById("remainingPieLegend");

const compareScenario = document.getElementById("compareScenario");
const compareVector = document.getElementById("compareVector");
const legacyDelayChart = document.getElementById("legacyDelayChart");
const legacySSChart = document.getElementById("legacySSChart");
const legacySSEChart = document.getElementById("legacySSEChart");
const globalStatus = document.getElementById("globalStatus");
const sidebarRole = document.getElementById("sidebarRole");
const sidebarUser = document.getElementById("sidebarUser");

let activePanelId = "panel-auth";

function apiBase() {
  return document.getElementById("apiBase").value.replace(/\/$/, "");
}

function logOutput(title, data) {
  if (!outputBox) return;
  outputBox.textContent = `${title}\n${JSON.stringify(data, null, 2)}`;
}

function setStatus(id, text) {
  const node = document.getElementById(id);
  if (!node) return;
  node.textContent = text;
}

function setGlobalStatus(text, tone = "idle") {
  if (!globalStatus) return;
  globalStatus.textContent = text;
  globalStatus.dataset.tone = tone;
}

function activatePanel(panelId) {
  activePanelId = panelId;
  document.querySelectorAll("[data-panel]").forEach((panel) => {
    panel.classList.toggle("panel-hidden", panel.id !== panelId);
  });
  document.querySelectorAll(".nav-btn[data-target]").forEach((button) => {
    button.classList.toggle("active", button.dataset.target === panelId);
  });
}

function bindNavigation() {
  const navButtons = document.querySelectorAll(".nav-btn[data-target]");
  navButtons.forEach((button) => {
    button.addEventListener("click", () => activatePanel(button.dataset.target));
  });
  activatePanel(activePanelId);
}

function parseJsonInput(raw, fallback) {
  if (!raw || !raw.trim()) {
    return fallback;
  }
  return JSON.parse(raw);
}

async function callApi(path, body, method = "POST") {
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
    const text = await response.text();
    throw new Error(`HTTP ${response.status}: ${text}`);
  }
  return response.json();
}

function currentBusinessPayload() {
  let users = [];
  try {
    users = parseJsonInput(document.getElementById("usersJson").value, []);
  } catch (error) {
    throw new Error(`用户列表 JSON 解析失败: ${error.message}`);
  }

  return {
    user_count: Number(document.getElementById("userCount").value || 1),
    modality: "text",
    default_requirement_type: document.getElementById("defaultRequirement").value,
    default_domain_type: document.getElementById("defaultDomain").value,
    tenant_id: document.getElementById("tenantId").value || "tenant-1",
    users,
  };
}

function currentNetworkPayload() {
  return {
    cpu_capacity: Number(document.getElementById("cpuCapacity").value || 100),
    compute_energy_threshold: Number(document.getElementById("energyThreshold").value || 500),
    total_bandwidth: Number(document.getElementById("totalBandwidth").value || 2),
    total_power: Number(document.getElementById("totalPower").value || 1),
    channel_scenario: document.getElementById("channelScenario").value,
  };
}

function currentSlicePayload() {
  const names = (document.getElementById("sliceNames").value || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
  let knowledgeBases = [];
  try {
    knowledgeBases = parseJsonInput(document.getElementById("kbJson").value, []);
  } catch (error) {
    throw new Error(`知识库 JSON 解析失败: ${error.message}`);
  }

  return {
    slice_count: Number(document.getElementById("sliceCount").value || 1),
    slice_names: names,
    codec_count: Number(document.getElementById("codecCount").value || 1),
    codec_modality: "text",
    knowledge_bases: knowledgeBases,
  };
}

function adaptationMethod() {
  return document.getElementById("adaptMethod").value;
}

function allocationAlgorithm() {
  return document.getElementById("allocAlgorithm").value;
}

function allocationBackend() {
  const element = document.getElementById("allocationBackend");
  return element ? element.value : "online_pso";
}

function legacyStrategy() {
  const element = document.getElementById("legacyStrategy");
  return element ? element.value : "semslice";
}

function legacyScenario() {
  const element = document.getElementById("legacyScenario");
  return element ? element.value : "fitSNR";
}

function legacyIterations() {
  const element = document.getElementById("legacyIterations");
  return element ? Number(element.value || 2) : 2;
}

function legacyParticles() {
  const element = document.getElementById("legacyParticles");
  return element ? Number(element.value || 2) : 2;
}


function parseCompareVector(raw) {
  const fallback = [0.2, 0.3, 0.5, 0.6, 0.8, 0.6];
  if (!raw || !raw.trim()) {
    return fallback;
  }
  const values = raw
    .split(",")
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item));
  return values.length >= 6 ? values.slice(0, 6) : fallback;
}

function renderLegacyCompareSummary(comparisons) {
  const rows = (comparisons || []).map((item) => ({
    strategy: item.strategy,
    avg_delay_ms: item.avg_delay_ms === null || item.avg_delay_ms === undefined ? "-" : Number(item.avg_delay_ms).toFixed(4),
    avg_ss: item.avg_ss === null || item.avg_ss === undefined ? "-" : Number(item.avg_ss).toFixed(4),
    avg_s_se: item.avg_s_se === null || item.avg_s_se === undefined ? "-" : Number(item.avg_s_se).toFixed(6),
    score_sum: item.score_sum === null || item.score_sum === undefined ? "-" : Number(item.score_sum).toFixed(4),
    status: item.error ? `失败: ${item.error}` : "成功",
  }));
  renderTable("legacyCompareSummary", rows);
}

function renderLegacyAverageCharts(comparisons) {
  const ok = (comparisons || []).filter((item) => !item.error);

  const delayRows = ok.map((item) => ({ label: item.strategy, value: Number(item.avg_delay_ms || 0) }));
  const ssRows = ok.map((item) => ({ label: item.strategy, value: Number(item.avg_ss || 0) }));
  const sseRows = ok.map((item) => ({ label: item.strategy, value: Number(item.avg_s_se || 0) }));

  renderBars(legacyDelayChart, delayRows, "value");
  renderBars(legacySSChart, ssRows, "value", 1);
  renderBars(legacySSEChart, sseRows, "value", 1);
}

function renderLegacyDelayTaskTable(comparisons) {
  const taskMap = {};
  (comparisons || []).forEach((item) => {
    if (item.error || !item.points) {
      return;
    }
    item.points.forEach((point) => {
      const taskId = Number(point.task_id);
      if (!taskMap[taskId]) {
        taskMap[taskId] = { task_id: taskId };
      }
      taskMap[taskId][item.strategy] = Number(point.delay_ms || 0).toFixed(4);
    });
  });

  const rows = Object.keys(taskMap)
    .map((key) => Number(key))
    .sort((a, b) => a - b)
    .map((taskId) => {
      const row = taskMap[taskId];
      return {
        task_id: row.task_id,
        semslice_delay_ms: row.semslice || "-",
        netslice_delay_ms: row.netslice || "-",
        random_delay_ms: row.random || "-",
      };
    });

  renderTable("legacyDelayTaskTable", rows);
}

async function runLegacyCompare() {
  const scenario = compareScenario ? compareScenario.value : "fitSNR";
  const resourceVector = parseCompareVector(compareVector ? compareVector.value : "");
  const result = await callApi("/analysis/legacy/strategy-compare", {
    scenario,
    resource_vector: resourceVector,
  });

  const okCount = (result.comparisons || []).filter((item) => !item.error).length;
  setStatus("legacyCompareStatus", `对比场景 ${result.scenario}，成功策略 ${okCount}/3`);

  renderLegacyCompareSummary(result.comparisons);
  renderLegacyAverageCharts(result.comparisons);
  renderLegacyDelayTaskTable(result.comparisons);
  setGlobalStatus("三策略对比完成", "ok");
  activatePanel("panel-compare");

  logOutput("源仓库三策略对比输出", result);
}

function ensureRemainingPieNodes() {
  let chart = document.getElementById("remainingPieChart");
  let legend = document.getElementById("remainingPieLegend");
  if (chart && legend) {
    return { chart, legend };
  }

  const anchor = document.getElementById("allocationTable");
  const panelParent = anchor ? anchor.parentElement : null;
  if (!panelParent) {
    return { chart: null, legend: null };
  }

  let panel = panelParent.querySelector(".pie-panel");
  if (!panel) {
    const title = document.createElement("h3");
    title.textContent = "当前剩余资源";
    panel = document.createElement("div");
    panel.className = "pie-panel";
    anchor.insertAdjacentElement("afterend", title);
    title.insertAdjacentElement("afterend", panel);
  }

  chart = document.getElementById("remainingPieChart");
  legend = document.getElementById("remainingPieLegend");

  if (!chart) {
    chart = document.createElement("div");
    chart.id = "remainingPieChart";
    chart.className = "remaining-pie";
    panel.appendChild(chart);
  }
  if (!legend) {
    legend = document.createElement("div");
    legend.id = "remainingPieLegend";
    legend.className = "remaining-legend";
    panel.appendChild(legend);
  }

  return { chart, legend };
}

function renderRemainingPie(result) {
  const nodes = ensureRemainingPieNodes();
  const chart = nodes.chart;
  const legendRoot = nodes.legend;
  if (!chart || !legendRoot) {
    return;
  }

  const used = result.used_resources || {};
  const remain = result.remaining_resources || {};
  const items = [
    { key: "bandwidth", label: "带宽", color: "#0f766e" },
    { key: "power", label: "功率", color: "#14b8a6" },
    { key: "compute", label: "计算", color: "#0ea5e9" },
    { key: "energy", label: "能耗预算", color: "#22c55e" },
  ];

  const rows = items.map((item) => {
    const usedValue = Number(used[item.key] || 0);
    const remainValue = Number(remain[item.key] || 0);
    const totalValue = usedValue + remainValue;
    const ratio = totalValue > 0 ? remainValue / totalValue : 0;
    return {
      ...item,
      remainValue,
      ratio,
    };
  });

  const ratioSum = rows.reduce((sum, row) => sum + row.ratio, 0);
  const normalized = ratioSum > 0
    ? rows.map((row) => ({ ...row, weight: row.ratio / ratioSum }))
    : rows.map((row) => ({ ...row, weight: 0.25 }));

  let start = 0;
  const segments = normalized
    .map((row) => {
      const end = start + row.weight * 360;
      const part = `${row.color} ${start.toFixed(2)}deg ${end.toFixed(2)}deg`;
      start = end;
      return part;
    })
    .join(", ");

  chart.innerHTML = `<div class="pie-circle" style="background: conic-gradient(${segments});"></div>`;

  const legend = normalized
    .map((row) => `<div class="legend-item"><span class="legend-dot" style="background:${row.color}"></span><span>${row.label}：${row.remainValue.toFixed(5)}（剩余率 ${(row.ratio * 100).toFixed(2)}%）</span></div>`)
    .join("");
  legendRoot.innerHTML = legend;
}

function renderRoleView() {
  const isAdmin = state.role === "admin";
  document.querySelectorAll(".admin-only").forEach((section) => {
    section.classList.toggle("hidden", !isAdmin);
  });

  if (sidebarRole) {
    if (!state.role) sidebarRole.textContent = "访客模式";
    else sidebarRole.textContent = isAdmin ? "管理员系统" : "租户系统";
  }
  if (sidebarUser) {
    sidebarUser.textContent = state.user ? `${state.user.username}` : "未登录";
  }
}

function renderTable(targetId, rows) {
  const target = document.getElementById(targetId);
  if (!target) {
    console.warn(`[renderTable] target not found: ${targetId}`);
    return;
  }
  if (!rows || !rows.length) {
    target.innerHTML = '<div class="status">暂无数据</div>';
    return;
  }

  const keys = Object.keys(rows[0]);
  const head = keys.map((key) => `<th>${key}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${keys.map((key) => `<td>${row[key]}</td>`).join("")}</tr>`)
    .join("");

  target.innerHTML = `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function renderBars(root, rows, valueKey, maxValue = null) {
  if (!root) return;
  root.innerHTML = "";
  if (!rows || !rows.length) {
    root.textContent = "暂无数据";
    return;
  }
  const max = maxValue || Math.max(...rows.map((row) => Number(row[valueKey])), 1);
  rows.forEach((row) => {
    const value = Number(row[valueKey] || 0);
    const pct = Math.max(0, Math.min(100, (value / max) * 100));
    const label = row.label || row.user_id || row.step || "item";
    const bar = document.createElement("div");
    bar.className = "bar-row";
    bar.innerHTML = `
      <div>${label}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
      <div>${value.toFixed(4)}</div>
    `;
    root.appendChild(bar);
  });
}

function renderMetrics(metrics) {
  if (!metricCards) return;
  metricCards.innerHTML = "";
  Object.keys(metrics || {}).forEach((key) => {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `<div class="name">${key}</div><div class="value">${metrics[key]}</div>`;
    metricCards.appendChild(card);
  });
}

function renderResourceBreakdown(result) {
  if (!resourceBreakdown) {
    return;
  }
  const used = result.used_resources || {};
  const remain = result.remaining_resources || {};
  const rows = [
    { item: "带宽", used: used.bandwidth || 0, remaining: remain.bandwidth || 0 },
    { item: "功率", used: used.power || 0, remaining: remain.power || 0 },
    { item: "计算", used: used.compute || 0, remaining: remain.compute || 0 },
    { item: "能耗预算", used: used.energy || 0, remaining: remain.energy || 0 },
  ];

  const head = "<tr><th>资源项</th><th>已使用</th><th>剩余</th></tr>";
  const body = rows
    .map((row) => `<tr><td>${row.item}</td><td>${Number(row.used).toFixed(5)}</td><td>${Number(row.remaining).toFixed(5)}</td></tr>`)
    .join("");

  resourceBreakdown.innerHTML = `<div class="table-wrap"><table><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
}

async function login() {
  const payload = {
    username: document.getElementById("username").value,
    password: document.getElementById("password").value,
    system_type: document.getElementById("systemType").value,
  };
  const result = await callApi("/auth/login", payload);
  state.token = result.token;
  state.role = result.role;
  state.user = result;
  renderRoleView();
  setStatus("loginStatus", `已登录：${result.username}（${result.role}）`);
  setGlobalStatus(`当前会话：${result.username}`, "ok");
  activatePanel("panel-business");
  logOutput("登录成功", result);
}

async function logout() {
  if (state.token) {
    await callApi("/auth/logout", {}, "POST");
  }
  state.token = null;
  state.role = null;
  state.user = null;
  renderRoleView();
  setStatus("loginStatus", "未登录");
  setGlobalStatus("系统待配置", "idle");
  activatePanel("panel-auth");
  logOutput("已退出登录", { success: true });
}

async function loadExample() {
  const data = await callApi("/workflow/example", null, "GET");

  document.getElementById("userCount").value = data.business.user_count;
  document.getElementById("tenantId").value = data.business.tenant_id;
  document.getElementById("defaultRequirement").value = data.business.default_requirement_type;
  document.getElementById("defaultDomain").value = data.business.default_domain_type;

  document.getElementById("cpuCapacity").value = data.network.cpu_capacity;
  document.getElementById("energyThreshold").value = data.network.compute_energy_threshold;
  document.getElementById("totalBandwidth").value = data.network.total_bandwidth;
  document.getElementById("totalPower").value = data.network.total_power;
  document.getElementById("channelScenario").value = data.network.channel_scenario;

  document.getElementById("sliceCount").value = data.slicing.slice_count;
  document.getElementById("sliceNames").value = data.slicing.slice_names.join(",");
  document.getElementById("codecCount").value = data.slicing.codec_count;
  document.getElementById("kbJson").value = JSON.stringify(data.slicing.knowledge_bases, null, 2);

  if (data.allocation_algorithm) {
    document.getElementById("allocAlgorithm").value = data.allocation_algorithm;
  }
  if (data.allocation_backend && document.getElementById("allocationBackend")) {
    document.getElementById("allocationBackend").value = data.allocation_backend;
  }
  if (data.legacy_strategy && document.getElementById("legacyStrategy")) {
    document.getElementById("legacyStrategy").value = data.legacy_strategy;
  }
  if (data.legacy_scenario && document.getElementById("legacyScenario")) {
    document.getElementById("legacyScenario").value = data.legacy_scenario;
  }

  logOutput("示例已加载", data);
}

async function runBusinessConfig() {
  const result = await callApi("/module/business/config", currentBusinessPayload());
  state.businessOutput = result;
  setStatus("businessSummary", `业务用户数：${result.summary.user_count}，模态：${result.summary.modality}`);
  document.getElementById("usersJson").value = JSON.stringify(result.users, null, 2);
  setGlobalStatus("\u4e1a\u52a1\u914d\u7f6e\u5b8c\u6210", "ok");
  activatePanel("panel-network");
  logOutput("业务配置输出", result);
}

async function runNetworkConfig() {
  const result = await callApi("/module/network/config", currentNetworkPayload());
  state.networkOutput = result;
  setStatus("networkSummary", `场景：${result.network.channel_scenario}，噪声：${result.network.noise_dbm} dBm`);
  setGlobalStatus("\u7f51\u7edc\u914d\u7f6e\u5b8c\u6210", "ok");
  activatePanel("panel-slice");
  logOutput("网络配置输出", result);
}

async function runSliceConfig() {
  const result = await callApi("/module/slice/config", currentSlicePayload());
  state.slicingOutput = result;
  setStatus("sliceSummary", `生成切片：${result.slices.length}，编解码器：${result.codecs.length}`);
  setGlobalStatus("\u5207\u7247\u914d\u7f6e\u5b8c\u6210", "ok");
  activatePanel("panel-adapt");
  logOutput("切片配置输出", result);
}

async function runAdaptation() {
  if (!state.businessOutput) {
    await runBusinessConfig();
  }
  if (!state.slicingOutput) {
    if (state.role === "admin") {
      await runSliceConfig();
    } else {
      throw new Error("租户请先让管理员配置切片，或先执行一次系统运行");
    }
  }

  const result = await callApi("/module/adaptation", {
    users: state.businessOutput.users,
    slices: state.slicingOutput.slices,
    method: adaptationMethod(),
  });
  state.adaptationOutput = result;
  renderTable("adaptTable", result.relations);
  setGlobalStatus("\u4e1a\u52a1\u9002\u914d\u5b8c\u6210", "ok");
  activatePanel("panel-resource");
  logOutput("切片与业务适配输出", result);
}

async function runAllocation() {
  if (!state.adaptationOutput) {
    await runAdaptation();
  }

  const network = state.networkOutput
    ? {
        cpu_capacity: state.networkOutput.network.cpu_capacity,
        compute_energy_threshold: state.networkOutput.network.compute_energy_threshold,
        total_bandwidth: state.networkOutput.network.total_bandwidth,
        total_power: state.networkOutput.network.total_power,
        channel_scenario: state.networkOutput.network.channel_scenario,
      }
    : currentNetworkPayload();

  const result = await callApi("/module/resources/allocate", {
    users: state.businessOutput.users,
    relations: state.adaptationOutput.relations,
    network,
    algorithm: allocationAlgorithm(),
    allocation_backend: allocationBackend(),
    legacy_strategy: legacyStrategy(),
    legacy_scenario: legacyScenario(),
    legacy_iterations: legacyIterations(),
    legacy_particles: legacyParticles(),
  });

  state.allocationOutput = result;
  setStatus(
    "resourceSummary",
    `剩余带宽 ${result.remaining_resources.bandwidth}，剩余功率 ${result.remaining_resources.power}，剩余计算 ${result.remaining_resources.compute}，剩余能耗预算 ${result.remaining_resources.energy}`
  );
  renderResourceBreakdown(result);
  renderTable("allocationTable", result.allocations);
  renderRemainingPie(result);
  setGlobalStatus("\u8d44\u6e90\u5206\u914d\u5b8c\u6210", "ok");
  activatePanel("panel-resource");
  logOutput("资源分配输出", result);
}

async function runPerformance() {
  if (!state.allocationOutput) {
    await runAllocation();
  }

  const network = state.networkOutput
    ? {
        cpu_capacity: state.networkOutput.network.cpu_capacity,
        compute_energy_threshold: state.networkOutput.network.compute_energy_threshold,
        total_bandwidth: state.networkOutput.network.total_bandwidth,
        total_power: state.networkOutput.network.total_power,
        channel_scenario: state.networkOutput.network.channel_scenario,
      }
    : currentNetworkPayload();

  const result = await callApi("/module/performance/evaluate", {
    users: state.businessOutput.users,
    allocations: state.allocationOutput.allocations,
    network,
  });

  state.performanceOutput = result;
  renderMetrics(result.core_metrics);
  renderBars(fidelityChart, result.charts.fidelity_by_user, "value", 1);
  renderBars(delayChart, result.charts.delay_by_user, "value");
  setGlobalStatus("\u6027\u80fd\u8bc4\u4f30\u5b8c\u6210", "ok");
  activatePanel("panel-performance");
  logOutput("性能评估输出", result);
}

async function runSystem() {
  const payload = {
    business: currentBusinessPayload(),
    network: currentNetworkPayload(),
    slicing: currentSlicePayload(),
    adaptation_method: adaptationMethod(),
    allocation_algorithm: allocationAlgorithm(),
    allocation_backend: allocationBackend(),
    legacy_strategy: legacyStrategy(),
    legacy_scenario: legacyScenario(),
    legacy_iterations: legacyIterations(),
    legacy_particles: legacyParticles(),
  };

  const endpoint = state.role === "admin" ? "/system/admin/run" : "/system/tenant/run";
  const result = await callApi(endpoint, payload);

  state.businessOutput = result.business_output;
  state.networkOutput = result.network_output;
  state.slicingOutput = result.slicing_output;
  state.adaptationOutput = result.adaptation_output;
  state.allocationOutput = result.allocation_output;
  state.performanceOutput = result.performance_output;

  renderTable("adaptTable", result.adaptation_output.relations);
  renderTable("allocationTable", result.allocation_output.allocations);
  renderMetrics(result.performance_output.core_metrics);
  renderBars(fidelityChart, result.performance_output.charts.fidelity_by_user, "value", 1);
  renderBars(delayChart, result.performance_output.charts.delay_by_user, "value");
  renderRemainingPie(result.allocation_output);
  renderResourceBreakdown(result.allocation_output);

  setStatus("businessSummary", `业务用户数：${result.business_output.summary.user_count}`);
  setStatus(
    "resourceSummary",
    `剩余带宽 ${result.allocation_output.remaining_resources.bandwidth}，剩余功率 ${result.allocation_output.remaining_resources.power}，剩余计算 ${result.allocation_output.remaining_resources.compute}，剩余能耗预算 ${result.allocation_output.remaining_resources.energy}`
  );
  setGlobalStatus("\u7cfb\u7edf\u8fd0\u884c\u5b8c\u6210", "ok");
  activatePanel("panel-performance");

  logOutput("系统一键运行输出", result);
}

function bindEvents() {
  document.getElementById("loginBtn").addEventListener("click", () => login().catch((e) => alert(e.message)));
  document.getElementById("logoutBtn").addEventListener("click", () => logout().catch((e) => alert(e.message)));
  document.getElementById("loadExampleBtn").addEventListener("click", () => loadExample().catch((e) => alert(e.message)));

  document.getElementById("buildBusinessBtn").addEventListener("click", () => runBusinessConfig().catch((e) => alert(e.message)));
  document.getElementById("buildNetworkBtn").addEventListener("click", () => runNetworkConfig().catch((e) => alert(e.message)));
  document.getElementById("buildSliceBtn").addEventListener("click", () => runSliceConfig().catch((e) => alert(e.message)));
  document.getElementById("runAdaptBtn").addEventListener("click", () => runAdaptation().catch((e) => alert(e.message)));
  document.getElementById("runAllocateBtn").addEventListener("click", () => runAllocation().catch((e) => alert(e.message)));
  document.getElementById("runPerformanceBtn").addEventListener("click", () => runPerformance().catch((e) => alert(e.message)));
  document.getElementById("runSystemBtn").addEventListener("click", () => runSystem().catch((e) => alert(e.message)));
  const quickRunBtn = document.getElementById("quickRunBtn");
  if (quickRunBtn) {
    quickRunBtn.addEventListener("click", () => runSystem().catch((e) => alert(e.message)));
  }

  const runLegacyCompareBtn = document.getElementById("runLegacyCompareBtn");
  if (runLegacyCompareBtn) {
    runLegacyCompareBtn.addEventListener("click", () => runLegacyCompare().catch((e) => alert(e.message)));
  }
  document.getElementById("systemType").addEventListener("change", (event) => {
    if (event.target.value === "admin") {
      document.getElementById("username").value = "admin";
      document.getElementById("password").value = "admin123";
    } else {
      document.getElementById("username").value = "tenant1";
      document.getElementById("password").value = "tenant123";
    }
  });
}

bindNavigation();
bindEvents();
renderRoleView();
setGlobalStatus("系统待配置", "idle");
loadExample().catch(() => {
  logOutput("提示", { message: "可手动输入配置后执行" });
});








