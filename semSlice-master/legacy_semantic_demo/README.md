# Legacy Semantic Demo

这个文件夹是一个最小 demo，用来展示旧实验里的语义通信主链路，并把三类策略放在一起对比：

```text
任务提交 -> 策略选择切片/模型 -> 读取该切片功率/带宽
-> P/B计算SNR与传输时延
-> 语义编码 -> 信道编码 -> AWGN信道 -> 信道解码 -> 语义解码
-> 高保真/低时延任务门限判断
```

它只演示编解码过程，不加载 BERT，也不计算 BERT 语义相似度。

## 运行

从仓库根目录运行：

```bash
cd graduation/semSlice-master
python legacy_semantic_demo/semantic_roundtrip_demo.py --device cpu
```

默认参数已经调成容易看出三种策略差异：

```text
--task en80
--slice-power 0.02 0.05 0.10
--slice-bandwidth 0.90 0.70 0.40
--netslice-policy fixed
--noslice-model en90
```

这样默认会形成：

```text
SemSlice -> slice-3 / en80%
NetSlice -> slice-1 / enorigin
NoSlice  -> slice-2 / en90%
```

可选任务：

```bash
python legacy_semantic_demo/semantic_roundtrip_demo.py --task full
python legacy_semantic_demo/semantic_roundtrip_demo.py --task en90
python legacy_semantic_demo/semantic_roundtrip_demo.py --task en80
```

`--task` 模拟任务提交里的业务词表类型。脚本会对同一句输入同时跑三种策略：

```text
SemSlice -> 根据词表重合度 sem_NSSAI 选择切片
NetSlice -> 忽略语义匹配，按传统/固定规则选择切片
NoSlice  -> 不做切片匹配，使用一个共享默认模型
```

SemSlice 的选择规则：

```text
>=95%       -> slice-1 / deepsc-AWGN-enorigin_layer3
85%~95%     -> slice-2 / deepsc-AWGN-en90%_layer3
75%~85%     -> slice-3 / deepsc-AWGN-en80%_layer3
```

NetSlice 默认使用 `fixed`，也就是固定选传统网络切片里的 slice-1，方便和 SemSlice 拉开差异：

```bash
python legacy_semantic_demo/semantic_roundtrip_demo.py --task en90 --netslice-policy stable-random
python legacy_semantic_demo/semantic_roundtrip_demo.py --task en90 --netslice-policy round-robin
python legacy_semantic_demo/semantic_roundtrip_demo.py --task en90 --netslice-policy fixed
```

NoSlice 默认使用 `en90` 模型作为共享模型，方便和另外两条策略拉开差异；也可以指定：

```bash
python legacy_semantic_demo/semantic_roundtrip_demo.py --task en80 --noslice-model full
python legacy_semantic_demo/semantic_roundtrip_demo.py --task en80 --noslice-model en90
python legacy_semantic_demo/semantic_roundtrip_demo.py --task en80 --noslice-model en80
```

旧实验资源链路参数：

```bash
python legacy_semantic_demo/semantic_roundtrip_demo.py \
  --slice-power 0.02 0.05 0.10 \
  --slice-bandwidth 0.90 0.70 0.40 \
  --total-power 1 \
  --total-bandwidth 2 \
  --distance-m 3000 \
  --noise-dbm -114.45
```

脚本现在不再直接输入 `--snr-db`。它会按旧实验公式计算：

```text
SNR = P / (B*10^6*d^2*N0)
C = B*10^6*log2(1+SNR)
delay = K*L/C
```

其中 `--semantic-symbols` 对应旧实验的 `K`，默认 `10`；`--symbol-length` 对应 `L`，默认 `30`。

任务门限也按旧实验方式保留：

```bash
python legacy_semantic_demo/semantic_roundtrip_demo.py --requirement-type high-fidelity --sim-threshold 0.6
python legacy_semantic_demo/semantic_roundtrip_demo.py --requirement-type low-latency --delay-threshold 0.13
```

因为这个 demo 不加载 BERT，高保真门限里的相似度暂时用 `TokenMatch` 代替，只用于对比编解码前后差异。

## 输出

脚本会打印：

- 提交任务信息；
- 词表匹配度；
- 每个切片的功率、带宽、SNR、信道容量和传输时延；
- 三种策略各自选中的切片和 checkpoint；
- DeepSC 编码、信道传输、解码各阶段 tensor 形状；
- 原始句子；
- SemSlice / NetSlice / NoSlice 各自的解码句子；
- 任务是否通过高保真/低时延门限；
- `TokenMatch`：不用 BERT 的轻量词 id 位置匹配率，只用于 demo 对比。

默认直接使用 `DeepSC-master/` 下现有的模型和数据文件，不依赖旧脚本里的 `europarl/` 或 `checkpoints/1201/` 目录结构。
