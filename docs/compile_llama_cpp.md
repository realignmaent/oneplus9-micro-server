# 高通骁龙 888 (ARMv8.2-A) 极致优化编译 llama.cpp 实战指南

在一加 9（Snapdragon 888, Cortex-X1 + A78 + A55）的 Termux PRoot Debian 容器中编译 `llama.cpp`，能发挥高通 Kryo 680 CPU 的硬件级向量化加速能力。

## 1. 核心编译特性支持
* **架构目标**：`-march=armv8.2-a+fp16+dotprod`
* **硬件指令集**：
  * **FP16 硬件半精度浮点**：大幅压缩权重计算周期与带宽开销。
  * **DotProd (点积加速指令)**：加速 8-bit/4-bit 整数内积运算。

## 2. 关键避坑：解决 Termux Bionic 与 Debian Glibc 冲突
若直接在 Debian PRoot 中编译，CMake 可能会错误探测到宿主 Termux 的 Bionic C 库（位于 `/data/data/com.termux/files/usr/include`），缺少 GLIBC 基础宏（如 `__GLIBC_PREREQ`），导致 `math.h` 报错崩溃。

**终极解决命令**：
```bash
cmake -B build \
  -DCMAKE_BUILD_TYPE=Release \
  -DGGML_NATIVE=OFF \
  -DCMAKE_C_FLAGS="-march=armv8.2-a+fp16+dotprod -O3" \
  -DCMAKE_CXX_FLAGS="-march=armv8.2-a+fp16+dotprod -O3" \
  -DCMAKE_IGNORE_PATH="/data/data/com.termux;/data"

cmake --build build --config Release -j 4
```

## 3. 安装生成物
```bash
cp build/bin/llama-server /usr/local/bin/
cp build/bin/llama-cli /usr/local/bin/
```
编译产物支持标准 OpenAI 协议（`/v1/chat/completions` 与 `/v1/models`）。
