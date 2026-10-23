# 更新日志

本文件记录一加 9 移动家庭微服务器（Termux + PRoot Debian）本轮落地的能力变更，
按能力归类，不按提交顺序；每条后面的端口/文件对应仓库内实际实现。

## 公网与朋友访问通道

- **双反代安全融合网关 `:8081`**（`tools/public_ai_gateway.py`）：把 QoderGateway(`:5050`)
  与 WorkBuddy/wb2api(`:7863`) 聚合成单一 OpenAI 兼容出口，对外只暴露
  `/v1`、`/v1/messages`、`/qoder/v1`、`/wb/v1`，管理台路径（`/console`、`/ui`）不经公网。
- **Bearer Token 虚拟化鉴权**（`tools/gateway_tokens.py`）：朋友侧 Key 为 `pgw_` 前缀，
  库里只存 SHA-256 哈希 + 前缀，支持签发 / 轮换 / 吊销 / 到期 / `last_used` 与 IP 审计；
  Owner 侧 `qg_live_` 为静态 Key。无有效 Key 一律 401，兼作防扫描门禁。
- **静态 Key 迁移工具**（`tools/upgrade_db_tokens.py`）：把历史硬编码 Key 迁入哈希 Token 库。
- **Cloudflare 快速隧道**（`tools/start_public_ai.sh` / `tools/stop_public_ai.sh`）：
  从 cloudflared 日志轮询提取 `*.trycloudflare.com` 公网域名并落盘，供控制台与朋友页动态读取。
- **温控熔断与限流**：CPU 超阈值拒绝转发（`MAX_TEMP_CELSIUS`，默认 45℃），
  按 IP 记录失败次数并临时封禁，抵御公网爆破与爬虫。
- **凭据注入方式变更（本轮）**：网关代码内的真实 Key 不再入库，改由环境变量
  `GATEWAY_QODER_KEY` / `GATEWAY_WB_KEY` / `GATEWAY_STATIC_KEYS` 注入；
  仓库副本是逻辑快照，直接部署前必须先设好这三个变量。

## 端侧大模型与陪伴人格

- **模型矩阵切换为 DeepSeek-R1-1.5B**（`deepseek-r1-1.5b-q4_k_m.gguf`，`:8080`）：
  llama-server 默认暴露别名 `DeepSeek-R1-1.5B`，并保留 `deepseek-r1-1.5b`、`qwen2.5-3b`
  向下兼容，避免旧客户端断链。
- **官方 WebUI 全反代 + SSE 流式**：反代 llama-server 原生界面，保留左侧历史边栏、
  Token 吞吐统计、消息操作栏，并注入遥测角标。
- **陪伴人格调优**：23 岁同龄人格提示词收敛，禁用低龄化昵称；通知卡片视觉与 crontab 路径修正。

## 控制台与硬件遥测

- **实时硬件遥测看板 `:5701`**（`tools/dashboard.py`、`scripts/dashboard.py`）：
  零依赖秒级采集 `/sys` 温度、内存、CPU 频率与电量，写出 `phone_metrics.json`。
- **Supervisor 式进程生命周期**：控制台可直接查看各服务进程、日志与内存树，并支持启停操作
  （`/api/service/action`、`/api/service/logs`）。
- **免 Root 电量检测与多通道告警**：低电量时按陪伴人格触发提醒。
- **朋友页 `/friend`**：按请求 Host 动态生成 7 个服务入口（DevCheck、青龙、WorkBuddy、
  Qoder、llama、wb2api、公网网关），公网网关地址实时读取 `~/public_url.txt`，不硬编码。

## 规范与运维基线

- `AGENTS.md` / `.agents/rules/oneplus9_micro_server.md`：固化设备与系统基线、SSH 优先的
  命令执行铁律、PRoot 后台保活规则、端口拓扑矩阵与开机自愈约定。
- **设备标识不入库**：ADB 序列号从文档与诊断脚本（`tools/do_optimize.py`、
  `tools/scan_processes.py`、`tools/collect_watch_companion.ps1`）中移除，统一改由
  环境变量 `OP9_ADB_SERIAL` 注入。

## 调研归档

- `docs/watch_w301cn_dashboard_research.md`：W301CN 手表在无 Root 前提下新增原生看板的
  可行性结论——被 `run-as` 不可调试、`WatchFaceFileProvider` 未导出、
  `WatchFaceDeviceProvider` 需 `com.oppo.permission.safe.IOT` 三处硬限制锁死；
  配套采集脚本 `tools/collect_watch_companion.ps1`，证据目录 `artifacts/watch-w301cn/` 已加入忽略。

## 运行监控（2026-10-23）

- **健康总览条**（`:5701` 微服务卡片上方）：在线数、累计重启次数、公网探活结果与时间、异常服务名单。
- **每服务重启计数**：状态变更写入 `metrics_history.db` 的 `service_events` 表，控制台自身重启后不清零；卡片上显示“重启 N”。
- **24h 趋势图**：每 30s 采样 CPU 温度 / 1m 负载 / 已用内存，保留 7 天；`/api/history?hours=N` 返回降采样数据，右上角 ECharts 折线展示。
- **外部可用性探活**（`tools/health_probe.py`，cron 每 5 分钟）：探测 8 个本地端口 + 隧道公网 `/health`，结果写 `~/logs/health_probe.json` 供控制台读取；失败走多通道告警并做 30 分钟节流。
- **守护补强**：`start_qinglong_daemon.sh` 增加 cloudflared 存活检查（进程缺失、或公网 `/health` 连续两次失败则重启并刷新 `public_url.txt`）；crontab 补 `*/2` 守护心跳与 `*/5` 探活任务。

## 已知待跟进

1. 快速隧道 URL 每次重启都会变化，`public_url.txt` 与控制台/朋友页会自动更新，但客户端手填的地址不会；要稳定入口仍需 Cloudflare 命名隧道 + 自有域名。
2. 手机端实跑的 `public_ai_gateway.py` 仍是硬编码 Key 的历史副本，与仓库快照存在这一处差异。
3. 一加 9 上 Tailscale 已被卸载，朋友侧 Tailscale 通道（含 `100.x` 地址与对应证书 SAN）不可用，需重装登录并重新签发带新 SAN 的叶子证书。
4. 历史上已推送过 PushPlus / WxPusher 凭据，代码现已改为只读环境变量，但**旧凭据需在对应后台轮换**才算真正失效。
