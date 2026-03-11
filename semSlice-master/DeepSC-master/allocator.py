import numpy as np
import math
from typing import List
from schemas import NetworkConfig, MatchResult, AllocationResult, StrategyType, ServiceRequest


class ResourceAllocator:
    def __init__(self, network_config: NetworkConfig):
        self.net_conf = network_config
        self.d = 3000
        self.n0 = 10 ** (-114.45 / 10) * 1e-3

    def _calculate_snr(self, p, b):
        if b <= 0: return -100
        # 融合前端环境基准底噪
        env_penalty = 10 ** ((10.0 - self.net_conf.snr_db) / 10.0)
        actual_n0 = self.n0 * env_penalty
        SNR_linear = p / (b * 1e6 * (self.d ** 2) * actual_n0)
        return 10 * np.log10(SNR_linear) if SNR_linear > 0 else -100

        # 🌟 替换掉你原来的这个方法，让它支持接收 req_type 参数
    def _calculate_delay(self, b, snr_db, strategy="semantic", req_type="high_fidelity"):
        if b <= 0: return 9999
        C = b * 1e6 * math.log2(1 + 10 ** (snr_db / 10))
        if C == 0: return 9999

        if strategy == "semantic":
            # 🎯 意图驱动下的动态负载
            if req_type == "high_fidelity":
                L_eff = 5000  # 数据量极大 (高清影像)，吃带宽
                processing_delay = 0.005  # 深度大模型，处理耗时 5ms
            elif req_type == "low_latency":
                L_eff = 100  # 极简控制指令，符号极少
                processing_delay = 0.001  # 轻量级小模型，处理耗时 1ms
            else:
                L_eff = 1000
                processing_delay = 0.002
        elif strategy == "network":
            # 传统网络没有语义压缩，比特流原样传输
            if req_type == "high_fidelity":
                L_eff = 50000
            else:
                L_eff = 5000
            processing_delay = 0.0001  # 没有深度学习，传统解码几乎无处理时延
        else:
            L_eff = 10000
            processing_delay = 0.0002

        k_symbol = 10
        # 总时延 = 物理传输时延 + 模型推理时延
        transmit_delay = (k_symbol * L_eff) / C
        return transmit_delay + processing_delay
    def _estimate_similarity_proxy(self, snr_db):
        center, scale = 2.0, 0.5
        similarity = 1 / (1 + np.exp(-scale * (snr_db - center)))
        return max(0.0, min(1.0, similarity))

    def execute_allocation(self, matched_tasks, strategy, services):
        if not matched_tasks: return []
        if strategy == "none":
            return self._allocation_equal(matched_tasks)
        target = "semantic" if strategy == "semantic" else "rate"
        return self._run_pso(matched_tasks, services, target)

    def _run_pso(self, matched_tasks, services, target):
        num_tasks = len(matched_tasks)
        dim = 2 * num_tasks
        pop_size = 30
        iterations = 50

        # 初始随机分布稍微给小一点，鼓励系统从“省吃俭用”开始探索
        X = np.random.uniform(0.2, 3.0, (pop_size, dim))
        V = np.zeros((pop_size, dim))
        P_best, G_best = X.copy(), np.zeros(dim)
        P_fit, G_fit = np.full(pop_size, -1e15), -1e15

        for gen in range(iterations):
            prog = gen / iterations
            c1 = 1.5 + np.sin(math.pi / 2 * (1 - 2 * prog))
            c2 = 1.5 + np.sin(math.pi / 2 * (2 * prog - 1))
            w = 1.6 - 1.2 * prog

            for i in range(pop_size):
                # ==========================================
                # 🌟 核心修改 1：边界控制与“按需限制”
                # ==========================================
                # 保证最低生存底线
                X[i, :num_tasks] = np.clip(X[i, :num_tasks], 0.2, self.net_conf.total_power)
                X[i, num_tasks:] = np.clip(X[i, num_tasks:], 0.5, self.net_conf.total_bandwidth)

                # 只有当总和超出基站物理上限时，才进行强制按比例缩减；
                # 如果没超出（有剩余），就保留原样，允许有资源闲置！
                if np.sum(X[i, :num_tasks]) > self.net_conf.total_power:
                    X[i, :num_tasks] = (X[i, :num_tasks] / np.sum(X[i, :num_tasks])) * self.net_conf.total_power
                if np.sum(X[i, num_tasks:]) > self.net_conf.total_bandwidth:
                    X[i, num_tasks:] = (X[i, num_tasks:] / np.sum(X[i, num_tasks:])) * self.net_conf.total_bandwidth

                fit = 0
                min_sim = 1.0

                for idx in range(num_tasks):
                    p = X[i, idx]
                    b = X[i, idx + num_tasks]
                    snr = self._calculate_snr(p, b)

                    task = matched_tasks[idx]
                    svc = next((s for s in services if s.service_id == task.service_id), None)
                    req_type = svc.requirement_type if svc else "high_fidelity"

                    if target == "semantic":
                        sim = self._estimate_similarity_proxy(snr)
                        delay = self._calculate_delay(b, snr, "semantic", req_type)

                        if sim < min_sim: min_sim = sim

                        # ==========================================
                        # 🌟 核心修改 2：引入“绿色节能惩罚”
                        # ==========================================
                        if req_type == "low_latency":
                            # 只要时延极低，轻微惩罚功率浪费 (- p * 1.5)
                            fit += (sim * 20.0) - (delay * 80.0) - (p * 1.5) - (b * 0.5)
                        elif req_type == "high_fidelity":
                            # 相似度高是首要的，但在相似度满足的情况下，功率用得越多扣分越多！
                            fit += (sim * 50.0) - (delay * 5.0) - (p * 2.0) - (b * 0.5)
                        else:
                            fit += (sim * 20.0) - (delay * 5.0) - (p * 1.0)
                    else:
                        fit += b * 1e6 * math.log2(1 + 10 ** (snr / 10))

                if target == "semantic" and min_sim < 0.5:
                    fit -= 5000.0 * (0.5 - min_sim)

                if fit > P_fit[i]:
                    P_fit[i] = fit
                    P_best[i] = X[i].copy()
                if fit > G_fit:
                    G_fit = fit
                    G_best = X[i].copy()

            V = w * V + c1 * np.random.rand() * (P_best - X) + c2 * np.random.rand() * (G_best - X)
            X = X + V

            # 输出层：彻底去掉强制 100% 缩减！
        final_p = G_best[:num_tasks]
        final_b = G_best[num_tasks:]

        final_p = np.maximum(final_p, 0.2)
        final_b = np.maximum(final_b, 0.5)

        # 2. 物理天花板绝对锁死：如果发完保底发现把基站掏空了（超标），必须强行按比例压缩，打破保底！
        if np.sum(final_p) > self.net_conf.total_power:
            final_p = (final_p / np.sum(final_p)) * self.net_conf.total_power
        if np.sum(final_b) > self.net_conf.total_bandwidth:
            final_b = (final_b / np.sum(final_b)) * self.net_conf.total_bandwidth


        results = []
        for idx, t in enumerate(matched_tasks):
            p = float(final_p[idx])
            b = float(final_b[idx])
            snr = self._calculate_snr(p, b)

            svc = next((s for s in services if s.service_id == t.service_id), None)
            req_type = svc.requirement_type if svc else "high_fidelity"

            delay = self._calculate_delay(b, snr, target, req_type)
            sim_base = self._estimate_similarity_proxy(snr)
            final_sim = sim_base * (t.similarity_score / 100.0)

            results.append(AllocationResult(
                mode=StrategyType.SEMANTIC if target == "semantic" else StrategyType.NETWORK,
                service_id=t.service_id, slice_id=t.slice_id,
                assigned_power=round(p, 4), assigned_bandwidth=round(b, 4),
                estimated_delay=round(delay * 1000, 2),
                estimated_energy=round(p * delay, 4),
                estimated_s_se=round(final_sim / 10, 4),
                similarity_score=round(final_sim * 100, 2)
            ))
        return results

    def _allocation_equal(self, tasks):
        n = len(tasks)
        p_avg = self.net_conf.total_power / n
        b_avg = self.net_conf.total_bandwidth / n
        res = []
        for t in tasks:
            snr = self._calculate_snr(p_avg, b_avg)
            delay = self._calculate_delay(b_avg, snr, "none")
            sim = 1 / (1 + np.exp(-0.5 * (snr - 8.0)))
            res.append(AllocationResult(
                mode=StrategyType.NONE, service_id=t.service_id, slice_id="Pool",
                assigned_power=p_avg, assigned_bandwidth=b_avg,
                estimated_delay=round(delay * 1000, 2), estimated_energy=round(p_avg * delay, 4),
                estimated_s_se=round(sim / 10, 4), similarity_score=round(sim * 15, 2)
            ))
        return res