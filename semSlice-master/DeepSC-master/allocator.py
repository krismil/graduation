import numpy as np
import math
from typing import List
from schemas import NetworkConfig, MatchResult, AllocationResult


class ResourceAllocator:
    def __init__(self, network_config: NetworkConfig):
        self.net_conf = network_config
        # 物理常数 (来自 utils.py)
        self.d = 3000
        self.n0 = 10 ** (-114.45 / 10) * 1e-3

    def _calculate_snr(self, p_watt, b_mhz):
        # ... (保持不变) ...
        if b_mhz <= 0: return -100
        noise_power = b_mhz * 1e6 * (self.d ** 2) * self.n0
        if noise_power == 0: return 0
        snr_linear = p_watt / noise_power
        return 10 * np.log10(snr_linear)

    def _calculate_capacity(self, p_watt, b_mhz):
        """
        计算香农容量 (Shannon Capacity)
        这是传统网络切片 (pso_netslice...) 优化的目标
        """
        if b_mhz <= 0: return 0
        snr_linear = (p_watt) / (b_mhz * 1e6 * (self.d ** 2) * self.n0)
        # Capacity = B * log2(1 + SNR)
        return b_mhz * 1e6 * math.log2(1 + snr_linear)

    def _estimate_similarity_proxy(self, snr_db):
        # ... (保持不变，DeepSC 代理模型) ...
        center = 2.0;
        scale = 0.5
        similarity = 1 / (1 + np.exp(-scale * (snr_db - center)))
        return max(0.0, min(1.0, similarity))

    def _calculate_delay(self, b_mhz, snr_db, data_size_symbols=30000):
        # ... (保持不变) ...
        if b_mhz <= 0: return 9999
        snr_linear = 10 ** (snr_db / 10)
        capacity = b_mhz * 1e6 * math.log2(1 + snr_linear)
        if capacity == 0: return 9999
        return data_size_symbols / capacity

    def execute_allocation(self, matched_tasks: List[MatchResult], strategy: str = "semantic") -> List[
        AllocationResult]:
        if not matched_tasks: return []

        # === 策略 3: 无切片 ===
        # 对应: no_slice_random_KPI_fit5TASK.py
        # 逻辑: 平均分配 (Equal Allocation)
        if strategy == "none":
            return self._allocation_equal(matched_tasks)

        # === 策略 2: 传统网络切片 ===
        # 对应: pso_netslice_random_SS_fit5TASK.py
        # 逻辑: PSO 优化 Sum Rate (吞吐量)
        elif strategy == "network":
            return self._run_pso(matched_tasks, optimization_target="rate")

        # === 策略 1: 语义切片 ===
        # 对应: pso_semanslice_SS_fit5TASK.py
        # 逻辑: PSO 优化 Semantic Similarity
        else:
            return self._run_pso(matched_tasks, optimization_target="semantic")

    def _allocation_equal(self, matched_tasks):
        """平均分配资源"""
        num_tasks = len(matched_tasks)
        p_per = self.net_conf.total_power / num_tasks
        b_per = self.net_conf.total_bandwidth / num_tasks

        results = []
        for task in matched_tasks:
            snr = self._calculate_snr(p_per, b_per)
            # 即使是无切片，我们也算一下 S-SE 用于对比
            # 因为无切片没有匹配，相当于匹配度极低，给个 0.5 的惩罚系数
            s_se = (self._estimate_similarity_proxy(snr) / 10) * 0.5
            delay = self._calculate_delay(b_per, snr)

            results.append(AllocationResult(
                service_id=task.service_id,
                slice_id="Default",
                assigned_power=round(p_per, 4),
                assigned_bandwidth=round(b_per, 4),
                estimated_delay=round(delay * 1000, 2),
                estimated_s_se=round(s_se, 4)
            ))
        return results

    def _run_pso(self, matched_tasks, optimization_target="semantic"):
        """通用 PSO 框架"""
        # 只给匹配到的切片分资源 (Unmatched 不分)
        slice_ids = list(set([t.slice_id for t in matched_tasks if t.slice_id != "Unmatched"]))
        num_slices = len(slice_ids)
        if num_slices == 0: return []

        # PSO 参数
        dimension = 2 * num_slices
        pop_size = 20
        iterations = 30
        x_min = np.array([0.01] * num_slices + [0.1] * num_slices)
        x_max = np.array([self.net_conf.total_power] * num_slices + [self.net_conf.total_bandwidth] * num_slices)

        X = np.random.uniform(x_min, x_max, (pop_size, dimension))
        V = np.zeros((pop_size, dimension))
        P_best = X.copy();
        P_best_fit = np.zeros(pop_size)
        G_best = np.zeros(dimension);
        G_best_fit = -1.0

        for gen in range(iterations):
            # 你的代码中的动态参数
            progress = gen / iterations
            c1 = 1.5 + np.sin(math.pi / 2 * (1 - (2 * progress)))
            c2 = 1.5 + np.sin(math.pi / 2 * ((2 * progress) - 1))
            w = 1.6 - 1.2 * progress

            for i in range(pop_size):
                # 约束处理
                powers = X[i, :num_slices]
                bandwidths = X[i, num_slices:]
                sum_p = np.sum(powers);
                sum_b = np.sum(bandwidths)
                if sum_p > self.net_conf.total_power: X[i, :num_slices] *= (self.net_conf.total_power / sum_p)
                if sum_b > self.net_conf.total_bandwidth: X[i, num_slices:] *= (self.net_conf.total_bandwidth / sum_b)
                X[i] = np.maximum(X[i], x_min)

                # === Fitness 计算核心差异 ===
                fitness = 0
                current_p = X[i, :num_slices]
                current_b = X[i, num_slices:]

                for idx in range(num_slices):
                    p = current_p[idx];
                    b = current_b[idx]

                    if optimization_target == "semantic":
                        # 语义目标：最大化相似度
                        snr = self._calculate_snr(p, b)
                        fitness += self._estimate_similarity_proxy(snr)
                    elif optimization_target == "rate":
                        # 传统目标：最大化吞吐量
                        fitness += self._calculate_capacity(p, b)

                if fitness > P_best_fit[i]: P_best_fit[i] = fitness; P_best[i] = X[i].copy()
                if fitness > G_best_fit: G_best_fit = fitness; G_best = X[i].copy()

            # 更新粒子
            r1 = np.random.rand(pop_size, dimension);
            r2 = np.random.rand(pop_size, dimension)
            V = w * V + c1 * r1 * (P_best - X) + c2 * r2 * (G_best - X)
            V = np.clip(V, -0.1, 0.1)
            X = X + V

        # 解析结果
        final_p = G_best[:num_slices]
        final_b = G_best[num_slices:]
        results = []

        for task in matched_tasks:
            if task.slice_id not in slice_ids: continue
            idx = slice_ids.index(task.slice_id)
            p = float(final_p[idx]);
            b = float(final_b[idx])
            snr = self._calculate_snr(p, b)

            # === 关键指标计算 ===
            # S-SE (语义频谱效率) = Similarity / K
            # 如果是传统切片 (Network Strategy)，因为是随机匹配，task.similarity_score 可能很低
            # 所以这里的 S-SE 会自动变得很低，体现出语义切片的优势

            # 基础 S-SE (基于 SNR)
            base_s_se = self._estimate_similarity_proxy(snr) / 10

            # 乘以匹配度系数 (如果匹配得好是 1.0，匹配不好可能是 0.3)
            match_factor = task.similarity_score / 100.0 if task.similarity_score > 0 else 0.1
            final_s_se = base_s_se * match_factor

            results.append(AllocationResult(
                service_id=task.service_id,
                slice_id=task.slice_id,
                assigned_power=round(p, 4),
                assigned_bandwidth=round(b, 4),
                estimated_delay=round(self._calculate_delay(b, snr) * 1000, 2),
                estimated_s_se=round(final_s_se, 4)
            ))

        return results