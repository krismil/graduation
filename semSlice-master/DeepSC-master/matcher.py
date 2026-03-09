import json
import os
import random  # 需要用到随机
from typing import List, Dict, Set
from schemas import ServiceRequest, SliceProfile, MatchResult


class SemanticSliceMatcher:
    def __init__(self, domain_vocab_map: Dict[str, str]):
        self.domain_vocab_map = domain_vocab_map
        self.vocab_cache: Dict[str, Set[str]] = {}

    def _get_vocab_tokens(self, file_path: str) -> Set[str]:
        # ... (保持原有的读取代码不变) ...
        if not file_path: return set()
        if file_path in self.vocab_cache: return self.vocab_cache[file_path]
        if not os.path.exists(file_path): return set()
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                tokens = set(data.get("token_to_idx", {}).keys())
                self.vocab_cache[file_path] = tokens
                return tokens
        except:
            return set()

    def _calculate_overlap(self, service_tokens: Set[str], slice_tokens: Set[str]) -> float:
        # ... (保持原有逻辑不变) ...
        if not service_tokens: return 0.0
        common_keys = service_tokens & slice_tokens
        return 100 * len(common_keys) / len(service_tokens)

    def match_services(self, services: List[ServiceRequest], slices: List[SliceProfile], strategy: str = "semantic") -> \
    List[MatchResult]:
        results = []

        # === 策略 3: 无切片 (No Slicing) ===
        # 对应逻辑: no_slice_random_SS.py
        # 所有业务都不进行切片匹配，统一归为一个默认组
        if strategy == "none":
            for service in services:
                results.append(MatchResult(
                    service_id=service.service_id,
                    slice_id="No_Slice_Default",  # 虚拟ID
                    matched_domain="General",
                    similarity_score=0.0,  # 无切片不谈匹配度
                    status="default_assigned"
                ))
            return results

        # === 策略 2: 传统网络切片 (Network Slicing) ===
        # 对应逻辑: net_slice_random_SS.py
        # 逻辑：Random allocation (随机分配)
        if strategy == "network":
            if not slices: return []
            for i, service in enumerate(services):
                # 随机选择一个切片 (为了演示效果稳定，这里用了轮询，你也可以用 random.choice)
                assigned_slice = slices[i % len(slices)]

                # 虽然是随机分配，但我们还是计算一下“由于乱分导致的真实相似度”
                # 这样前端才能画图展示：传统切片因为分错了，所以相似度很低
                s_tokens = self._get_vocab_tokens(self.domain_vocab_map.get(service.domain))
                sl_tokens = self._get_vocab_tokens(assigned_slice.vocab_path)
                real_score = self._calculate_overlap(s_tokens, sl_tokens)

                results.append(MatchResult(
                    service_id=service.service_id,
                    slice_id=assigned_slice.slice_id,
                    matched_domain=assigned_slice.slice_name,
                    similarity_score=round(real_score, 2),
                    status="randomly_assigned"
                ))
            return results

        # === 策略 1: 语义切片 (Semantic Slicing) ===
        # 对应逻辑: sem_slice_SS.py
        # 逻辑：Best Match (基于知识库相似度最高匹配)
        for service in services:
            best_slice_id = "Unmatched"
            best_score = -1.0
            best_domain_match = "None"

            s_tokens = self._get_vocab_tokens(self.domain_vocab_map.get(service.domain))

            for sl in slices:
                sl_tokens = self._get_vocab_tokens(sl.vocab_path)
                score = self._calculate_overlap(s_tokens, sl_tokens)
                if score > best_score:
                    best_score = score
                    best_slice_id = sl.slice_id
                    best_domain_match = sl.slice_name

            results.append(MatchResult(
                service_id=service.service_id,
                slice_id=best_slice_id,
                matched_domain=best_domain_match,
                similarity_score=round(best_score, 2),
                status="matched"
            ))

        return results