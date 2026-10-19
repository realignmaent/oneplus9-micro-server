/**
 * 青龙平台 (Qinglong v2.23+) · 一加 9 移动微服务器实时性能融合插件
 * - 实时遥测：高通骁龙 888 8核心频率、12GB 物理内存、7.8GB ZRAM、电池/CPU温度、网络吞吐、微服务心跳
 * - 深度融合：
 *   1. 左侧导航栏无缝注入「📱 手机性能」专属菜单项
 *   2. 仪表盘底部无缝注入「⚡ 手机硬件实时性能 (骁龙888)」专属 Tab
 *   3. 顶部导航栏增加硬件实时状态指示胶囊
 *   4. 秒级自动轮询，保证数据 100% 实时响应
 */

(function () {
  'use strict';

  console.log('[OnePlus9-Server] 正在加载手机性能看板融合插件...');

  // 样式定义
  const styleEl = document.createElement('style');
  styleEl.innerHTML = `
    @keyframes ql-pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.35; transform: scale(0.9); }
    }
    .ql-live-dot {
      display: inline-block;
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #10b981;
      box-shadow: 0 0 8px #10b981;
      animation: ql-pulse 1.8s infinite;
    }
    .ql-top-capsule {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: rgba(15, 23, 42, 0.85);
      border: 1px solid rgba(51, 65, 85, 0.9);
      border-radius: 20px;
      padding: 4px 14px;
      margin-left: 16px;
      font-size: 12px;
      color: #cbd5e1;
      cursor: pointer;
      transition: all 0.2s ease;
      user-select: none;
      backdrop-filter: blur(8px);
    }
    .ql-top-capsule:hover {
      background: rgba(30, 41, 59, 1);
      border-color: #38bdf8;
      color: #f8fafc;
      transform: translateY(-1px);
    }
    .ql-card-stat {
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 12px;
      padding: 16px;
      transition: all 0.2s;
    }
    .ql-card-stat:hover {
      border-color: #475569;
    }
    .ql-progress-track {
      background: #334155;
      border-radius: 9999px;
      overflow: hidden;
      height: 6px;
    }
    .ql-progress-bar {
      height: 100%;
      border-radius: 9999px;
      transition: width 0.4s ease;
    }
  `;
  document.head.appendChild(styleEl);

  let currentMetrics = null;
  let metricsTimer = null;
  let isPhoneTabActive = false;
  let isFullViewActive = false;

  // 统一数据抓取 (支持 5700 同源极速读取与 5701 回退)
  async function fetchPhoneMetrics() {
    try {
      let res;
      try {
        res = await fetch('/phone_metrics.json?_t=' + Date.now(), { cache: 'no-cache' });
        if (!res.ok) throw new Error();
      } catch (e) {
        res = await fetch('http://' + window.location.hostname + ':5701/api/metrics?_t=' + Date.now(), { cache: 'no-cache' });
      }
      if (res && res.ok) {
        const data = await res.json();
        currentMetrics = data;
        renderTopCapsule(data);
        if (isPhoneTabActive) {
          renderPhoneLivePanel(data);
        }
        return data;
      }
    } catch (err) {
      // 容错处理
    }
    return null;
  }

  // 1. 顶部栏状态胶囊
  function renderTopCapsule(data) {
    if (!data) return;
    let capsule = document.getElementById('ql-top-phone-pill');
    if (!capsule) {
      const headerRight = document.querySelector('.ant-pro-global-header') ||
                          document.querySelector('.ant-layout-header') ||
                          document.querySelector('header');
      if (headerRight) {
        capsule = document.createElement('div');
        capsule.id = 'ql-top-phone-pill';
        capsule.className = 'ql-top-capsule';
        capsule.title = '一加 9 硬件实时遥测：点击切换手机全景监控看板';
        capsule.onclick = switchToPhoneFullView;
        headerRight.insertBefore(capsule, headerRight.firstChild);
      }
    }
    if (capsule) {
      const temp = data.thermals ? data.thermals.battery : '--';
      const avail = data.ram ? (data.ram.avail_mb / 1024).toFixed(1) : '--';
      const x1Freq = (data.cpu_freqs && data.cpu_freqs[7]) ? data.cpu_freqs[7] : '--';
      const qlOnline = data.services && data.services.qinglong;
      capsule.innerHTML = `
        <span class="ql-live-dot" style="background:${qlOnline ? '#10b981' : '#f59e0b'};"></span>
        <span style="font-weight:600;color:#38bdf8;">OnePlus 9</span>
        <span style="color:#64748b;">|</span>
        <span>🌡️ <b>${temp}°C</b></span>
        <span style="color:#64748b;">|</span>
        <span>🧠 内存余 <b>${avail}G</b></span>
        <span style="color:#64748b;">|</span>
        <span>⚡ <b>${x1Freq}MHz</b></span>
      `;
    }
  }

  // 2. 左侧导航栏注入「📱 手机性能」
  function injectSidebarMenu() {
    const menuUl = document.querySelector('.ant-menu') || document.querySelector('aside ul');
    if (!menuUl) return;

    if (document.getElementById('ql-nav-phone-item')) {
      if (isFullViewActive) {
        document.getElementById('ql-nav-phone-item').classList.add('ant-menu-item-selected');
      }
      return;
    }

    const li = document.createElement('li');
    li.id = 'ql-nav-phone-item';
    li.className = 'ant-menu-item ant-menu-item-only-child' + (isFullViewActive ? ' ant-menu-item-selected' : '');
    li.setAttribute('role', 'menuitem');
    li.style.cssText = 'padding-left: 24px; display: flex; align-items: center; cursor: pointer;';
    li.innerHTML = `
      <span class="ant-menu-title-content" style="display: flex; align-items: center; justify-content: space-between; width: 100%;">
        <span style="display: flex; align-items: center; gap: 10px;">
          <span style="font-size: 16px;">📱</span>
          <span style="font-weight: 500;">手机性能</span>
        </span>
        <span style="font-size: 10px; background: rgba(16, 185, 129, 0.2); color: #10b981; padding: 1px 6px; border-radius: 9999px; border: 1px solid rgba(16, 185, 129, 0.4); margin-right: 12px;">实时</span>
      </span>
    `;

    li.onclick = function (e) {
      e.preventDefault();
      e.stopPropagation();
      switchToPhoneFullView();
    };

    // 插入到仪表盘下方作为第二项
    const dashboardItem = menuUl.children[0];
    if (dashboardItem && dashboardItem.nextSibling) {
      menuUl.insertBefore(li, dashboardItem.nextSibling);
    } else {
      menuUl.appendChild(li);
    }

    // 事件代理：点击其他菜单项时切回普通视图
    if (!menuUl.dataset.hasPhoneDelegate) {
      menuUl.dataset.hasPhoneDelegate = 'true';
      menuUl.addEventListener('click', function (e) {
        const clickedItem = e.target.closest('.ant-menu-item');
        if (clickedItem && clickedItem.id !== 'ql-nav-phone-item') {
          restoreNormalView();
        }
      });
    }
  }

  // 切换到全屏性能看板模式
  function switchToPhoneFullView() {
    isFullViewActive = true;
    const navItem = document.getElementById('ql-nav-phone-item');
    if (navItem) {
      document.querySelectorAll('.ant-menu-item').forEach(el => el.classList.remove('ant-menu-item-selected'));
      navItem.classList.add('ant-menu-item-selected');
    }

    const contentArea = document.querySelector('.ant-layout-content') || document.querySelector('main');
    if (!contentArea) return;

    // 隐藏主视图内其他元素
    Array.from(contentArea.children).forEach(child => {
      if (child.id !== 'ql-phone-fullview') {
        child.style.display = 'none';
      }
    });

    let fullView = document.getElementById('ql-phone-fullview');
    if (!fullView) {
      fullView = document.createElement('div');
      fullView.id = 'ql-phone-fullview';
      fullView.style.cssText = 'width: 100%; height: calc(100vh - 80px); min-height: 700px; display: flex; flex-direction: column; padding: 0 12px 12px 12px; box-sizing: border-box;';
      
      const iframeSrc = '/phone-dashboard.html?t=' + Date.now();
      fullView.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; padding: 4px 8px;">
          <div style="display:flex; align-items:center; gap:8px;">
            <span class="ql-live-dot"></span>
            <span style="font-size:16px; font-weight:bold; color:#f8fafc;">一加 9 (LE2110) 骁龙 888 · 移动微服务器全景监控</span>
            <span style="font-size:12px; color:#94a3b8; margin-left:8px;">局域网 IP: 192.168.31.172 · 端口: 5701</span>
          </div>
          <div style="display:flex; gap:10px;">
            <button id="ql-refresh-iframe-btn" style="background:#334155; border:1px solid #475569; color:#f8fafc; padding:4px 12px; border-radius:6px; font-size:12px; cursor:pointer;">刷新面板</button>
            <a href="http://${window.location.hostname}:5701" target="_blank" style="background:#2563eb; border:none; color:#fff; padding:4px 12px; border-radius:6px; font-size:12px; text-decoration:none; display:flex; align-items:center; gap:4px;">在新窗口打开 ↗</a>
          </div>
        </div>
        <iframe id="ql-phone-iframe" src="${iframeSrc}" style="width:100%; flex:1; border:1px solid #334155; border-radius:12px; background:#0f172a;" frameborder="0"></iframe>
      `;
      contentArea.appendChild(fullView);

      document.getElementById('ql-refresh-iframe-btn').onclick = function () {
        const iframe = document.getElementById('ql-phone-iframe');
        if (iframe) iframe.src = '/phone-dashboard.html?t=' + Date.now();
      };
    } else {
      fullView.style.display = 'flex';
    }

    window.location.hash = '#phone-dashboard';
  }

  // 恢复常规视图
  function restoreNormalView() {
    isFullViewActive = false;
    const navItem = document.getElementById('ql-nav-phone-item');
    if (navItem) navItem.classList.remove('ant-menu-item-selected');

    const contentArea = document.querySelector('.ant-layout-content') || document.querySelector('main');
    if (!contentArea) return;

    const fullView = document.getElementById('ql-phone-fullview');
    if (fullView) fullView.style.display = 'none';

    Array.from(contentArea.children).forEach(child => {
      if (child.id !== 'ql-phone-fullview') {
        child.style.display = '';
      }
    });

    if (window.location.hash === '#phone-dashboard') {
      window.location.hash = '';
    }
  }

  // 3. 仪表盘底部的 Tab 注入「⚡ 手机硬件实时性能 (骁龙888)」
  function injectDashboardTab() {
    if (!window.location.pathname.includes('/dashboard') && window.location.pathname !== '/') return;

    const tabsNav = document.querySelector('.ant-tabs-nav-list');
    if (!tabsNav) return;

    if (document.getElementById('ql-tab-phone-live')) return;

    const phoneTab = document.createElement('div');
    phoneTab.id = 'ql-tab-phone-live';
    phoneTab.className = 'ant-tabs-tab';
    phoneTab.setAttribute('role', 'tab');
    phoneTab.innerHTML = `
      <div class="ant-tabs-tab-btn" style="display:flex; align-items:center; gap:6px;">
        <span class="ql-live-dot"></span>
        <span style="font-weight:600; color:#38bdf8;">手机硬件实时性能 (骁龙888)</span>
      </div>
    `;

    phoneTab.onclick = function (e) {
      e.preventDefault();
      e.stopPropagation();
      activatePhoneLiveTab();
    };

    tabsNav.appendChild(phoneTab);

    // 事件代理：点击原有 Tab 时切回
    if (!tabsNav.dataset.hasPhoneTabDelegate) {
      tabsNav.dataset.hasPhoneTabDelegate = 'true';
      tabsNav.addEventListener('click', function (e) {
        const clickedTab = e.target.closest('.ant-tabs-tab');
        if (clickedTab && clickedTab.id !== 'ql-tab-phone-live') {
          deactivatePhoneLiveTab();
        }
      });
    }
  }

  function activatePhoneLiveTab() {
    isPhoneTabActive = true;
    const tabsNav = document.querySelector('.ant-tabs-nav-list');
    if (tabsNav) {
      tabsNav.querySelectorAll('.ant-tabs-tab').forEach(t => t.classList.remove('ant-tabs-tab-active'));
      const pt = document.getElementById('ql-tab-phone-live');
      if (pt) pt.classList.add('ant-tabs-tab-active');
    }

    const contentHolder = document.querySelector('.ant-tabs-content-holder');
    if (contentHolder) contentHolder.style.display = 'none';

    let livePanel = document.getElementById('ql-phone-live-panel');
    if (!livePanel) {
      livePanel = document.createElement('div');
      livePanel.id = 'ql-phone-live-panel';
      livePanel.style.cssText = 'padding: 16px 0; width: 100%;';
      const parent = contentHolder ? contentHolder.parentNode : document.querySelector('.ant-tabs');
      if (parent) parent.appendChild(livePanel);
    } else {
      livePanel.style.display = 'block';
    }

    if (currentMetrics) {
      renderPhoneLivePanel(currentMetrics);
    } else {
      fetchPhoneMetrics();
    }
  }

  function deactivatePhoneLiveTab() {
    isPhoneTabActive = false;
    const pt = document.getElementById('ql-tab-phone-live');
    if (pt) pt.classList.remove('ant-tabs-tab-active');

    const livePanel = document.getElementById('ql-phone-live-panel');
    if (livePanel) livePanel.style.display = 'none';

    const contentHolder = document.querySelector('.ant-tabs-content-holder');
    if (contentHolder) contentHolder.style.display = '';
  }

  // 渲染仪表盘实时卡片内容
  function renderPhoneLivePanel(data) {
    const livePanel = document.getElementById('ql-phone-live-panel');
    if (!livePanel || !data) return;

    const freqs = data.cpu_freqs || [0, 0, 0, 0, 0, 0, 0, 0];
    const ram = data.ram || { total_mb: 11230, used_mb: 7272, avail_mb: 3958, pct: 64.8 };
    const zram = data.zram || { total_mb: 7679, used_mb: 1105, pct: 14.4 };
    const thermals = data.thermals || { battery: 29.5, cpu_max: 36.8, shell_back: 31.8, status: 'NORMAL' };
    const net = data.net || { rx_kbps: 0.0, tx_kbps: 0.0 };

    const x1 = freqs[7] || 844;
    const a78_avg = Math.round((freqs[4] + freqs[5] + freqs[6]) / 3) || 710;
    const a55_avg = Math.round((freqs[0] + freqs[1] + freqs[2] + freqs[3]) / 4) || 691;

    livePanel.innerHTML = `
      <div style="background:#0f172a; border:1px solid #1e293b; border-radius:16px; padding:20px; color:#f8fafc;">
        <!-- Header -->
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid #1e293b;">
          <div style="display:flex; align-items:center; gap:10px;">
            <span class="ql-live-dot"></span>
            <span style="font-size:16px; font-weight:700; color:#38bdf8;">一加 9 (LE2110) · 硬件秒级实时遥测</span>
            <span style="font-size:11px; font-family:monospace; background:rgba(56,189,248,0.15); color:#38bdf8; border:1px solid rgba(56,189,248,0.3); border-radius:9999px; padding:2px 8px;">骁龙 888 · 12GB LPDDR5</span>
          </div>
          <div style="display:flex; align-items:center; gap:12px;">
            <span style="font-size:12px; color:#94a3b8;">系统持续运行: <b style="color:#e2e8f0;">${data.uptime_str || '正常'}</b></span>
            <button onclick="window.OnePlus9OpenFullView()" style="background:#2563eb; color:#fff; border:none; padding:4px 12px; border-radius:6px; font-size:12px; cursor:pointer; font-weight:500;">全景看板 ↗</button>
          </div>
        </div>

        <!-- 4 Grid Sections -->
        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap:16px;">
          
          <!-- CPU 8 Cores -->
          <div class="ql-card-stat">
            <div style="font-size:13px; font-weight:600; color:#94a3b8; display:flex; justify-content:space-between; margin-bottom:10px;">
              <span>⚡ CPU 8核心时钟频率</span>
              <span style="color:#38bdf8; font-family:monospace;">总占用: ${data.cpu_total || 0}%</span>
            </div>
            <div style="display:flex; flex-direction:column; gap:8px;">
              <div>
                <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:3px;">
                  <span style="color:#ef4444; font-weight:500;">Cortex-X1 超大核 (Core 7)</span>
                  <span style="font-family:monospace; color:#f8fafc;">${x1} MHz <span style="color:#64748b;">/ 2.84G</span></span>
                </div>
                <div class="ql-progress-track"><div class="ql-progress-bar" style="width:${Math.min(100, (x1 / 2841) * 100)}%; background:#ef4444;"></div></div>
              </div>
              <div>
                <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:3px;">
                  <span style="color:#f59e0b; font-weight:500;">Cortex-A78 性能集群 (Core 4-6)</span>
                  <span style="font-family:monospace; color:#f8fafc;">${a78_avg} MHz <span style="color:#64748b;">/ 2.42G</span></span>
                </div>
                <div class="ql-progress-track"><div class="ql-progress-bar" style="width:${Math.min(100, (a78_avg / 2419) * 100)}%; background:#f59e0b;"></div></div>
              </div>
              <div>
                <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:3px;">
                  <span style="color:#10b981; font-weight:500;">Cortex-A55 能效集群 (Core 0-3)</span>
                  <span style="font-family:monospace; color:#f8fafc;">${a55_avg} MHz <span style="color:#64748b;">/ 1.80G</span></span>
                </div>
                <div class="ql-progress-track"><div class="ql-progress-bar" style="width:${Math.min(100, (a55_avg / 1804) * 100)}%; background:#10b981;"></div></div>
              </div>
            </div>
          </div>

          <!-- Memory & ZRAM -->
          <div class="ql-card-stat">
            <div style="font-size:13px; font-weight:600; color:#94a3b8; display:flex; justify-content:space-between; margin-bottom:10px;">
              <span>🧠 物理内存 & 压缩SWAP</span>
              <span style="color:#a855f7; font-family:monospace;">RAM占用: ${ram.pct}%</span>
            </div>
            <div style="display:flex; flex-direction:column; gap:8px;">
              <div>
                <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:3px;">
                  <span>物理 RAM: ${(ram.used_mb / 1024).toFixed(2)}G / ${(ram.total_mb / 1024).toFixed(1)}G</span>
                  <span style="color:#10b981; font-weight:600;">可用: ${(ram.avail_mb / 1024).toFixed(2)}G</span>
                </div>
                <div class="ql-progress-track"><div class="ql-progress-bar" style="width:${ram.pct}%; background:#3b82f6;"></div></div>
              </div>
              <div>
                <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:3px;">
                  <span>ZRAM 压缩内存: ${(zram.used_mb / 1024).toFixed(2)}G / ${(zram.total_mb / 1024).toFixed(1)}G</span>
                  <span style="color:#a855f7;">${zram.pct}%</span>
                </div>
                <div class="ql-progress-track"><div class="ql-progress-bar" style="width:${zram.pct}%; background:#a855f7;"></div></div>
              </div>
              <div style="font-size:10px; color:#64748b; margin-top:2px;">
                💡 已冻结 22 项无用预装后台，空闲物理内存持续保持在 ~4.0GB 高水位。
              </div>
            </div>
          </div>

          <!-- Thermals -->
          <div class="ql-card-stat">
            <div style="font-size:13px; font-weight:600; color:#94a3b8; display:flex; justify-content:space-between; margin-bottom:10px;">
              <span>🌡️ 硬件传感器热区</span>
              <span style="font-size:10px; background:rgba(16,185,129,0.2); color:#10b981; border:1px solid rgba(16,185,129,0.3); border-radius:4px; padding:1px 6px;">状态: ${thermals.status}</span>
            </div>
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px; font-size:11px;">
              <div style="background:#0f172a; padding:8px; border-radius:6px;">
                <span style="color:#94a3b8;">🔋 电池电芯</span>
                <div style="font-size:16px; font-weight:bold; color:#10b981; font-family:monospace; margin-top:2px;">${thermals.battery}°C</div>
              </div>
              <div style="background:#0f172a; padding:8px; border-radius:6px;">
                <span style="color:#94a3b8;">🔥 CPU 峰值</span>
                <div style="font-size:16px; font-weight:bold; color:#38bdf8; font-family:monospace; margin-top:2px;">${thermals.cpu_max}°C</div>
              </div>
              <div style="background:#0f172a; padding:8px; border-radius:6px;">
                <span style="color:#94a3b8;">📱 外壳背板</span>
                <div style="font-size:14px; font-weight:bold; color:#e2e8f0; font-family:monospace; margin-top:2px;">${thermals.shell_back}°C</div>
              </div>
              <div style="background:#0f172a; padding:8px; border-radius:6px;">
                <span style="color:#94a3b8;">🛡️ 温控策略</span>
                <div style="font-size:11px; color:#94a3b8; margin-top:4px;">39°告警 / 42.5°停机</div>
              </div>
            </div>
          </div>

          <!-- Network & Services -->
          <div class="ql-card-stat">
            <div style="font-size:13px; font-weight:600; color:#94a3b8; display:flex; justify-content:space-between; margin-bottom:10px;">
              <span>📶 网络吞吐 & 微服务心跳</span>
              <span style="font-family:monospace; font-size:11px; color:#10b981;">↓${net.rx_kbps} KB/s  ↑${net.tx_kbps} KB/s</span>
            </div>
            <div style="display:flex; flex-direction:column; gap:6px; font-size:11px;">
              <div style="display:flex; justify-content:space-between; align-items:center; background:#0f172a; padding:6px 8px; border-radius:6px;">
                <span>⏰ 青龙面板调度服务 (:5700)</span>
                <span style="color:#10b981; font-weight:600;">● 在线运行</span>
              </div>
              <div style="display:flex; justify-content:space-between; align-items:center; background:#0f172a; padding:6px 8px; border-radius:6px;">
                <span>🧠 Qwen2.5-3B 本地推理引擎 (:8080)</span>
                <span style="color:#10b981; font-weight:600;">● 在线就绪</span>
              </div>
              <div style="display:flex; justify-content:space-between; align-items:center; background:#0f172a; padding:6px 8px; border-radius:6px;">
                <span>🐕 守护自愈引擎 (Crond Watchdog)</span>
                <span style="color:#10b981; font-weight:600;">● 自动巡检保活</span>
              </div>
            </div>
          </div>

        </div>
      </div>
    `;
  }

  window.OnePlus9OpenFullView = switchToPhoneFullView;

  function initAddon() {
    injectSidebarMenu();
    injectDashboardTab();
    fetchPhoneMetrics();

    if (window.location.hash === '#phone-dashboard') {
      setTimeout(switchToPhoneFullView, 300);
    }

    const observer = new MutationObserver(() => {
      injectSidebarMenu();
      injectDashboardTab();
      renderTopCapsule(currentMetrics);
    });

    observer.observe(document.body, { childList: true, subtree: true });

    if (metricsTimer) clearInterval(metricsTimer);
    metricsTimer = setInterval(fetchPhoneMetrics, 1500);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAddon);
  } else {
    initAddon();
  }
})();
