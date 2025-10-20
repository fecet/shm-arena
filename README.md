# IPC Benchmark: 进程间共享字典性能对比

使用MPI测试不同进程间共享字典方案的性能对比工具。

## 方案对比

本项目测试以下三种IPC方案:

### 1. LMDB
- **原理**: 基于文件的内存映射数据库
- **优势**: 持久化存储, ACID特性, 适合读多写少场景
- **劣势**: 需要序列化, 有文件系统开销

### 2. SharedMemory
- **原理**: Python 3.8+的原生共享内存 (multiprocessing.shared_memory)
- **优势**: 零拷贝, 直接内存访问, 性能高
- **劣势**: 需要手动管理内存布局和同步

### 3. ZeroMQ
- **原理**: 高性能消息队列, 使用IPC传输
- **优势**: 灵活的通信模式, 支持多种拓扑
- **劣势**: 仍需序列化, 有额外的拷贝开销

## 项目结构

```
.
├── src/ipc_benchmark/
│   ├── __init__.py
│   ├── base.py              # 抽象基类
│   ├── utils.py             # 工具函数(序列化等)
│   ├── lmdb_backend.py      # LMDB实现
│   ├── shm_backend.py       # SharedMemory实现
│   └── zmq_backend.py       # ZeroMQ实现
├── benchmark_mpi.py         # MPI测试主程序
├── analyze_results.py       # 结果分析和可视化
├── pixi.toml                # Pixi环境配置
└── README_BENCHMARK.md      # 本文档
```

## 安装依赖

本项目使用Pixi管理环境:

```bash
# 安装和更新依赖
pixi install

# 进入Pixi环境
pixi shell
```

主要依赖:
- `mpi4py`: MPI Python绑定
- `python-lmdb`: LMDB Python绑定
- `pyzmq`: ZeroMQ Python绑定
- `matplotlib`, `pandas`: 结果分析和可视化

## 运行测试

### 基本用法

使用MPI运行测试, 需要至少2个进程(1个writer + 1个或多个readers):

```bash
# 使用4个进程(1 writer + 3 readers)
pixi run mpiexec -n 4 python benchmark_mpi.py
```

### 自定义进程数

```bash
# 使用8个进程(1 writer + 7 readers)
pixi run mpiexec -n 8 python benchmark_mpi.py

# 使用2个进程(最小配置)
pixi run mpiexec -n 2 python benchmark_mpi.py
```

测试会自动:
1. 使用不同大小的字典(10, 100, 1000, 10000个条目)
2. 对每个backend分别测试
3. Rank 0作为writer写入数据
4. Rank 1+作为readers并发读取数据
5. 测量写入时间、读取时间、吞吐量
6. 保存结果到 `benchmark_results.json`

## 分析结果

运行完测试后, 使用分析脚本生成可视化:

```bash
pixi run python analyze_results.py
```

这会生成:
- `benchmark_plots/write_performance.png` - 写入性能对比图
- `benchmark_plots/read_performance.png` - 读取性能对比图
- `benchmark_plots/throughput.png` - 吞吐量对比图
- `benchmark_plots/write_summary.csv` - 写入性能数据
- `benchmark_plots/read_summary.csv` - 读取性能数据

## 性能指标说明

### 写入性能
- **Write Time**: 一次写入操作的总时间(秒)
- 测试场景: 单个writer进程写入完整字典

### 读取性能
- **Avg Read Time**: 单次读取操作的平均时间(秒)
- **Throughput**: 每秒读取操作数(ops/sec)
- 测试场景: 多个reader进程并发读取, 每个进程执行100次读取

### 数据大小
测试使用以下字典大小:
- **Small**: 10个条目
- **Medium**: 100个条目
- **Large**: 1000个条目
- **Very Large**: 10000个条目

每个条目包含嵌套字典, 实际数据量约为条目数 × 100字节。

## 测试环境要求

- **操作系统**: Linux (OpenMPI在Linux上性能最佳)
- **Python**: 3.12+
- **内存**: 建议至少2GB可用内存
- **CPU**: 多核CPU可更好展现并发性能

## 使用建议

### 选择SharedMemory当:
- 需要最高性能
- 数据不需要持久化
- 进程在同一节点上

### 选择LMDB当:
- 需要持久化存储
- 读多写少
- 需要ACID保证

### 选择ZeroMQ当:
- 需要灵活的通信模式
- 可能跨节点通信
- 需要解耦进程

## 扩展和自定义

### 添加新的Backend

1. 继承 `IPCBackend` 基类:

```python
from ipc_benchmark.base import IPCBackend

class MyBackend(IPCBackend):
    def initialize(self, name: str, is_writer: bool) -> None:
        pass

    def write(self, data: dict) -> None:
        pass

    def read(self) -> dict | None:
        pass

    def cleanup(self) -> None:
        pass

    def get_name(self) -> str:
        return "MyBackend"
```

2. 在 `benchmark_mpi.py` 中注册:

```python
backends = [
    LMDBBackend(),
    SharedMemoryBackend(),
    MyBackend(),  # 添加你的backend
]
```

### 自定义测试参数

编辑 `benchmark_mpi.py` 中的配置:

```python
# 修改字典大小
data_sizes = [10, 100, 1000, 10000, 100000]

# 修改读取迭代次数
iterations = 500
```

## 故障排除

### 共享内存残留

如果测试中断, 可能留下共享内存片段:

```bash
# 查看共享内存
ls /dev/shm/

# 清理残留(小心使用!)
rm /dev/shm/bench_*
```

### LMDB数据库残留

```bash
# 清理临时LMDB数据库
rm -rf /tmp/lmdb_bench_*
```

### MPI错误

确保OpenMPI正确安装:

```bash
# 测试MPI
pixi run mpiexec --version

# 简单测试
pixi run mpiexec -n 2 hostname
```

## 许可和贡献

本项目为性能测试工具, 欢迎贡献新的IPC方案或改进现有实现。
