# IPC Benchmark: 进程间通信性能对比

使用 MPI 测试不同 IPC (进程间通信) 方案的性能对比工具。


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

# 运行 benchmark
pixi run bench              # 标准测试（1 writer + 3 readers）
pixi run bench-small        # 小规模（1 writer + 1 reader）
pixi run bench-large        # 大规模（1 writer + 7 readers）

# 分析结果
pixi run analyze
```

## Benchmark 结果

测试环境: **1 writer + 1 reader** (2个MPI进程), 100次读取迭代, 10000 entries

### 性能对比

| Backend | 写入时间 | 单次读取 | 架构特点 |
|---------|---------|---------|---------|
| **LMDB** | 5.13ms | 5.89ms | 持久化存储 |
| **SharedMemory** | 20.08ms | 5.97ms | 标准库，零拷贝 |
| **ZeroMQ** | 570.85ms | 5.74ms | 消息传递 |
| **MPI-Native** | 577.34ms | 5.76ms | MPI 集体通信 |

### 核心发现

#### 读取性能：所有方案相近（< 5%）
- 反序列化是主要瓶颈
- 传输机制差异可忽略不计

#### 写入性能：架构差异显著

**共享存储模型（LMDB、SharedMemory）**
- 写一次，多次读取
- 写入速度不受 reader 数量/迭代次数影响
- ✅ 适合多 reader 并发场景

**消息传递模型（ZeroMQ、MPI）**
- 每次读取需单独发送消息
- 写入时间 = reader数量 × 迭代次数 × 单条消息时间
- ✅ 适合单 reader 流式传输

## 使用建议

**根据功能需求选择：**

| Backend | 推荐场景 | 关键特性 |
|---------|---------|---------|
| **LMDB** | 需要持久化 | 唯一支持持久化，ACID 事务 |
| **SharedMemory** | 无外部依赖 | Python 标准库，多 reader 高效 |
| **MPI-Native** | HPC/分布式 | 跨节点通信，已有 MPI 环境 |
| **ZeroMQ** | 流式传输 | 灵活通信模式，单 reader 场景 |

## 故障排除

```bash
# 清理残留文件
pixi run clean

# 测试 MPI 环境
pixi run mpiexec --version
```
