# IPC Benchmark: 进程间通信性能对比

使用 MPI 测试不同 IPC (进程间通信) 方案在**两种使用场景**下的性能对比工具。

## 项目结构

```
.
├── src/ipc_benchmark/
│   ├── base.py              # 抽象基类
│   ├── utils.py             # 序列化工具
│   ├── lmdb_backend.py      # LMDB 实现
│   ├── shm_backend.py       # SharedMemory 实现
│   ├── zmq_backend.py       # ZeroMQ 实现
│   └── mpi_backend.py       # MPI-Native 实现
├── benchmark_mpi.py         # MPI 测试主程序
├── analyze_results.py       # 结果分析
├── pixi.toml                # Pixi 环境配置
└── README.md                # 本文档
```

## 快速开始

```bash
# 安装依赖
pixi install

# 运行完整 benchmark (两种场景 + 所有后端)
pixi run bench              # 1 writer + 3 readers

# 快速测试
pixi run bench-small        # 1 writer + 1 reader

# 大规模测试
pixi run bench-large        # 1 writer + 7 readers

# 分析结果
pixi run analyze
```

## Benchmark 架构

本项目对比 **4种IPC后端** 在 **2种使用场景** 下的性能表现。

### 测试场景

#### 场景1: 共享存储模式 (`--scenario shared`)

**模式**: Writer 写入 1 次数据 → 多个 Readers 各自读取 N 次

- **特点**: 并发访问同一份数据,类似"发布-订阅"模式的静态版本
- **优势后端**: LMDB, SharedMemory (共享存储架构,写一次即可)
- **劣势后端**: ZeroMQ, MPI-Native (消息传递架构,需重复发送)
- **适用场景**:
  - 配置文件共享
  - 只读数据集(机器学习模型、参考数据)
  - 多进程并发读同一资源

#### 场景2: 流式传输模式 (`--scenario streaming`)

**模式**: Writer 连续发送 N 条消息 → Readers 依次消费 N 条消息

- **特点**: 一对一消息传递,每条消息独立传输
- **优势后端**: ZeroMQ, MPI-Native (消息传递架构原生支持)
- **劣势后端**: LMDB, SharedMemory (需重复写覆盖,效率低)
- **适用场景**:
  - 实时数据流处理
  - 任务队列 / 工作分发
  - 管道式数据处理链

### 测试后端

| Backend | 架构类型 | 核心特性 | 外部依赖 |
|---------|---------|---------|---------|
| **LMDB** | 共享存储 | 持久化存储, ACID 事务 | ✓ python-lmdb |
| **SharedMemory** | 共享存储 | Python 标准库, 零拷贝 | ✗ 无 |
| **ZeroMQ** | 消息传递 | 灵活通信模式, 高吞吐 | ✓ pyzmq |
| **MPI-Native** | 消息传递 | 跨节点通信, 集体操作 | ✓ mpi4py, openmpi |

## 使用方法

### 完整测试 (推荐)

```bash
# 默认: 4 进程 (1 writer + 3 readers), 两种场景, 所有后端
pixi run bench
```

### 按场景测试

```bash
# 仅测试共享存储场景
pixi run bench-shared

# 仅测试流式传输场景
pixi run bench-streaming
```

### 按后端测试

```bash
# 测试单个后端的两种场景表现
pixi run bench-lmdb
pixi run bench-shm
pixi run bench-zmq
pixi run bench-mpi
```

### 自定义测试

```bash
# 指定场景 + 后端 + 参数
pixi run mpiexec -n 4 python benchmark_mpi.py \
  --scenario streaming \
  --backend zmq \
  --data-size 10000 \
  --iterations 100
```

**参数说明:**
- `--scenario`: 测试场景 (`shared` | `streaming` | `both`)
- `--backend`: 后端选择 (`lmdb` | `shm` | `zmq` | `mpi` | `all`)
- `--data-size`: 字典大小(entries 数量), 默认 10000
- `--iterations`: 读取迭代次数 / 消息数量, 默认 100

## Benchmark 结果示例

测试环境: **1 writer + 1 reader** (2个MPI进程), 100次迭代, 10000 entries

### 场景1: 共享存储模式

| Backend | 写入时间 | 平均读取 | 总读取数 | 说明 |
|---------|---------|---------|----------|------|
| **LMDB** | 0.16ms | 0.01ms | 100 | ✓ 最优: 写1次,读100次 |
| **SharedMemory** | 0.23ms | 0.02ms | 100 | ✓ 最优: 写1次,读100次 |
| **ZeroMQ** | 6.03ms | 0.10ms | 100 | ⚠️ 需发送100条消息 |
| **MPI-Native** | 4.52ms | 0.04ms | 100 | ⚠️ 需100次 bcast |

**关键发现**:
- **共享存储型后端占优**: LMDB 和 SharedMemory 写入时间极短（< 0.3ms）
- **消息传递型较慢**: ZeroMQ 和 MPI 需要重复发送，写入时间高出 20-30 倍
- **读取性能差异小**: 所有后端读取时间在同一量级（0.01-0.10ms）

### 场景2: 流式传输模式

| Backend | 写入时间 | 平均读取 | 总读取数 | 吞吐量 |
|---------|---------|---------|----------|--------|
| **LMDB** | 1.30ms | 0.01ms | 100 | ✓ 94,797 msg/s |
| **SharedMemory** | 1.24ms | 0.01ms | 100 | ✓ 76,376 msg/s |
| **ZeroMQ** | 5.56ms | 0.11ms | 100 | 8,871 msg/s |
| **MPI-Native** | 4.54ms | 0.07ms | 100 | 14,066 msg/s |

**关键发现**:
- **共享存储型意外领先**: LMDB 和 SharedMemory 在流式场景下吞吐量最高
- **写入时间相近**: 所有后端写入时间在 1-6ms 范围内
- **吞吐量差异显著**: 共享内存方案比消息传递快 5-10 倍（本测试配置下）

## 选择建议

### 根据使用场景选择

**需要持久化存储?** → **LMDB**
- 唯一支持数据持久化
- ACID 事务保证
- 适合需要断电恢复的场景

**多进程并发读同一数据?** → **SharedMemory**
- 零外部依赖 (Python 标准库)
- 写一次,多进程高效并发读
- 适合配置共享、数据集加载

**连续消息流处理?** → **ZeroMQ**
- 灵活的通信模式 (PUB/SUB, PUSH/PULL 等)
- 单进程间或跨网络都支持
- 适合实时数据流、任务队列

**HPC / 分布式计算?** → **MPI-Native**
- 跨节点通信支持
- 丰富的集体操作 (broadcast, reduce 等)
- 适合已有 MPI 环境的科学计算

### 性能优先级

**共享存储场景**: LMDB ≈ SharedMemory >> MPI-Native > ZeroMQ
**流式传输场景**: LMDB > SharedMemory >> MPI-Native > ZeroMQ

**注意**:
- 在小规模测试（2进程）中，共享内存方案在两种场景下均表现优异
- 消息传递方案的优势可能在大规模多进程（>10 readers）场景下体现
- 实际性能受数据大小、进程数量、网络拓扑等因素影响，建议根据实际场景测试

## 分析结果

运行 benchmark 后:

```bash
# 生成图表和详细分析
pixi run analyze
```

输出:
- `benchmark_results.json`: 原始数据
- `benchmark_plots/`: 可视化图表
  - `write_shared.png` / `write_streaming.png`: 写入性能对比
  - `read_shared.png` / `read_streaming.png`: 读取性能对比
  - `throughput_streaming.png`: 流式场景吞吐量对比
- `summary_*.csv`: 按场景分组的详细统计

## 故障排除

```bash
# 清理所有测试残留文件
pixi run clean

# 测试 MPI 环境
pixi run mpiexec --version

# 检查 Python 依赖
pixi run python -c "import lmdb, zmq, mpi4py; print('All deps OK')"
```

## 设计原则

1. **统一接口**: 所有后端实现相同的 `IPCBackend` 接口
2. **公平对比**: 使用相同的序列化方法 (pickle)
3. **场景区分**: 区分共享存储 vs 流式传输的适用场景
4. **真实模拟**: 基于 MPI 的多进程测试环境

## 技术细节

### 序列化

所有后端使用统一的 `pickle` 序列化,确保公平对比:

```python
def serialize(data: dict) -> bytes:
    return pickle.dumps(data)

def deserialize(data: bytes) -> dict:
    return pickle.loads(data)
```

### 同步机制

使用 MPI Barrier 确保进程间正确同步:

```python
comm.Barrier()  # 所有进程到达此点后才继续
```

### 场景实现差异

**共享存储场景**:
- **LMDB/SharedMemory**: Writer 写1次 → Readers 重复读同一份数据
- **ZeroMQ**: Writer 发送 N × M 条消息 (M = reader 数量) → 每个 Reader 消费 N 条
- **MPI-Native**: Writer 存储数据后参与 N 次 broadcast → Readers 参与 N 次 broadcast 接收

**流式传输场景**:
- **LMDB/SharedMemory**: Writer 写 N 次(覆盖) → Readers 读 N 次
- **ZeroMQ**: Writer 发送 N × M 条消息 (M = reader 数量) → 每个 Reader 消费 N 条
- **MPI-Native**: Writer 执行 N 次 broadcast → Readers 参与 N 次 broadcast 接收

**关键区别**:
- MPI broadcast 是**集体操作**，所有进程必须同时参与
- ZeroMQ 使用 PUSH/PULL 模式，消息在 readers 间**轮流分配**
- MPI broadcast 将**相同数据**发送给所有 readers

## 贡献

欢迎提交 Issue 和 Pull Request!

## 许可证

MIT License
