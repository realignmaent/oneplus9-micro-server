# 一加 9 移动家庭微服务器项目开发与运维规范 (OnePlus 9 Micro-Server Rules)

本规则适用于本工作区的所有会话与任务，涉及一加 9 手机服务端的操作、部署与调试必须严格遵循以下基线与规程。

---

## 一、 物理设备与环境基线 (Hardware & OS Baseline)

1. **设备规格**：一加 9 国行版（LE2110，高通骁龙 888 8核 CPU，12GB LPDDR5 RAM，256GB UFS 3.1 ROM）。
2. **系统形态**：免 Root (No-Root) 模式，ColorOS / Android 13 原厂固件，前台锁存 Termux (`termux-wake-lock`)。
3. **容器架构**：双层结构 —— Termux (Android 宿主环境) + PRoot Debian 12 (bookworm) ARM64 原生环境。
4. **网络基线**：局域网静态分配 IP 为 `192.168.31.172`，ADB 物理识别号为 `<OP9_ADB_SERIAL>`。

---

## 二、 核心通信通道与运维铁律 (Communication & Execution Rules)

1. **SSH 直连通道绝对优先 (Golden Path)**：
   * Termux 宿主已内置 OpenSSH 服务，监听端口 `8022`，并已录入 PC 端 SSH 公钥。
   * **命令执行铁律**：严禁无故使用 `adb shell input text` 模拟敲击，**所有命令一律通过 SSH 原生管道执行**：
     `ssh -p 8022 192.168.31.172 "<命令>"`
   * 需进入 Debian 容器执行时：
     `ssh -p 8022 192.168.31.172 "proot-distro login debian -- bash -c '<容器内命令>'"`

2. **PRoot 后台常驻保活铁律 (PRoot Keepalive Policy)**：
   * ⚠️ **致命坑点**：PRoot 从单次会话退出时会触发 `--kill-on-exit`，若直接在 Debian 内 `nohup ... &`，断开连接后进程必定被强杀。
   * 💡 **正确做法**：所有需要长期后台常驻的服务，**必须在 Termux 宿主层** 使用 nohup 启动 PRoot：
     ```bash
     nohup proot-distro login debian -- bash -c '<启动命令>' > <日志路径> 2>&1 &
     ```

3. **ADB 应急维护兜底**：
   * 仅在网络断开或 SSH 服务故障时启用 ADB 通道。
   * 若 ADB 识别丢失，优先执行重启重载：`adb kill-server; adb start-server; adb devices`。
   * 若手机锁屏阻断 Activity，先执行屏幕解锁：`adb shell "input keyevent 224; input swipe 540 1800 540 500 300"`。

---

## 三、 微服务端口拓扑矩阵 (Service Port Topology)

| 服务名称 | 监听端口 | 运行时与技术栈 | 部署目录 / 配置文件 | 作用与功能 |
| :--- | :--- | :--- | :--- | :--- |
| **WorkBuddy 管理端** | **:7864** | Python 3.11 FastAPI + Uvicorn | `/opt/workbuddy-manager/.env` | Web 控制台，托管 `web/out/` 静态前端，管理账号池与定时任务 |
| **wb2api 网关核心** | **:7863** | Go 1.22.5 ARM64 原生可执行文件 | `/opt/workbuddy-manager/upstream` | 企微 Token 鉴权，OpenAI 兼容反代（纯内存/Noop Redis 模式） |
| **青龙自动化面板** | **:5700** | Node.js Express + UmiJS | `/ql` | 定时任务平台，注入了 `phone_addon.js` 全景性能看板与状态胶囊 |
| **实时硬件遥测看板** | **:5701** | 原生 Python 3 `dashboard.py` | `/ql/data/scripts/dashboard.py` | 零依赖秒级采集 `/sys` 温度、内存、频率，写出 `phone_metrics.json` |
| **端侧大模型 API** | **:8080** | llama-server ARM 原生 | `/ql/data/models/` | 加载 `qwen2.5-3b-instruct-q4_k_m.gguf` 进行本地脱机推理 |
| **Termux SSH** | **:8022** | OpenSSH | `~/.ssh/authorized_keys` | 手机远程管理终端通道 |

---

## 四、 数据持久化与开机自愈机制 (Data & Self-Healing)

1. **统一自愈守护中心**：
   * 手机守护脚本收敛于：`/data/data/com.termux/files/home/start_qinglong_daemon.sh`。
   * 该脚本由 Termux crond 巡检或开机拉起，自动守护青龙、大模型、性能看板、wb2api 与 workbuddy 管理端 5 大服务进程。
2. **数据无损迁移原则**：
   * Web 前端严禁在手机端重复 npm 安装与构建，直接使用预编译产物 `web/out/` 由后端静态挂载。
   * SQLite 数据库（`manager.db`）、账号凭据（`upstream/auths/*.json`）和密码哈希（`users.json`）在 Windows 与 Linux 之间完全二进制通用，平移即可无缝复用。
   * 环境变量中的监听 IP 必须统一配置为 `0.0.0.0`，杜绝仅绑定 `127.0.0.1` 导致局域网无法访问。
