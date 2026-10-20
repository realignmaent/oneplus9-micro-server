import json

with open("scratch/clean_procs.json", "r", encoding="utf-8") as f:
    procs = json.load(f)

# Sort procs
procs.sort(key=lambda x: x["mem_mb"], reverse=True)

bloat_count = len([p for p in procs if p["safe_disable"]])
bloat_mem = sum(p["mem_mb"] for p in procs if p["safe_disable"])

html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>一加 9 移动服务器任务管理器</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
  <style>
    ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{ background: rgba(150,150,150,0.3); border-radius: 3px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: rgba(150,150,150,0.5); }}
  </style>
</head>
<body class="bg-[#f3f4f6] text-[#1f2937] dark:bg-[#121212] dark:text-[#f3f4f6] p-4 font-sans antialiased select-none">

  <!-- Windows 11 Task Manager Window Frame -->
  <div class="max-w-6xl mx-auto bg-white dark:bg-[#1e1e1e] rounded-xl shadow-xl border border-gray-200 dark:border-[#2d2d2d] overflow-hidden flex flex-col min-h-[820px]">
    
    <!-- Title Bar -->
    <div class="flex items-center justify-between px-4 py-3 bg-[#f9fafb] dark:bg-[#252526] border-b border-gray-200 dark:border-[#2d2d2d]">
      <div class="flex items-center space-x-3">
        <svg class="w-5 h-5 text-blue-600 dark:text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>
        </svg>
        <span class="font-semibold text-sm">一加 9 (LE2110) 任务管理器 · 家庭微服务器</span>
      </div>
      <div class="relative w-72">
        <input type="text" id="searchInput" placeholder="搜索进程名称、包名或 PID..." 
               class="w-full text-xs px-3 py-1.5 pl-8 bg-white dark:bg-[#2d2d2d] border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500">
        <svg class="w-4 h-4 text-gray-400 absolute left-2.5 top-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
        </svg>
      </div>
      <div class="flex items-center space-x-2 text-xs">
        <span class="px-2.5 py-1 bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300 rounded font-medium flex items-center">
          <span class="w-2 h-2 rounded-full bg-green-500 inline-block mr-1.5 animate-pulse"></span>
          在线守护中 (192.168.31.172)
        </span>
      </div>
    </div>

    <!-- Navigation & Summary Metrics Bar -->
    <div class="p-4 bg-[#fcfcfc] dark:bg-[#1a1a1a] border-b border-gray-200 dark:border-[#2d2d2d] grid grid-cols-2 md:grid-cols-4 gap-3">
      <div class="p-3 bg-white dark:bg-[#252526] rounded-lg border border-gray-200 dark:border-[#333] shadow-sm">
        <div class="text-xs text-gray-500 dark:text-gray-400">CPU 占用率 (骁龙888)</div>
        <div class="text-2xl font-bold mt-1 text-blue-600 dark:text-blue-400 flex items-baseline">
          4.8% <span class="text-xs font-normal text-gray-400 ml-2">8 核温润调度</span>
        </div>
      </div>

      <div class="p-3 bg-white dark:bg-[#252526] rounded-lg border border-gray-200 dark:border-[#333] shadow-sm">
        <div class="text-xs text-gray-500 dark:text-gray-400">物理内存总占用</div>
        <div class="text-2xl font-bold mt-1 text-purple-600 dark:text-purple-400 flex items-baseline">
          8.4 / 12 GB <span class="text-xs font-normal text-gray-400 ml-2">余 3.6 GB</span>
        </div>
      </div>

      <div class="p-3 bg-white dark:bg-[#252526] rounded-lg border border-gray-200 dark:border-[#333] shadow-sm">
        <div class="text-xs text-gray-500 dark:text-gray-400">电池核心温度</div>
        <div class="text-2xl font-bold mt-1 text-emerald-600 dark:text-emerald-400 flex items-baseline">
          29.8 °C <span class="text-xs font-normal text-gray-400 ml-2">健康安全</span>
        </div>
      </div>

      <div class="p-3 bg-orange-50 dark:bg-[#2c2016] rounded-lg border border-orange-200 dark:border-orange-900 shadow-sm cursor-pointer hover:bg-orange-100 transition" onclick="setFilter('冗余预装')">
        <div class="text-xs text-orange-600 dark:text-orange-400 font-semibold flex items-center justify-between">
          <span>可精简冗余进程</span>
          <span class="text-[10px] bg-orange-200 dark:bg-orange-800 px-1.5 rounded">点击筛选</span>
        </div>
        <div class="text-2xl font-bold mt-1 text-orange-700 dark:text-orange-300 flex items-baseline">
          {bloat_mem/1024:.2f} GB <span class="text-xs font-normal text-orange-500 ml-2">共 {bloat_count} 个服务</span>
        </div>
      </div>
    </div>

    <!-- Category Filter Tabs -->
    <div class="px-4 py-2.5 bg-gray-50 dark:bg-[#202020] border-b border-gray-200 dark:border-[#2d2d2d] flex flex-wrap items-center justify-between gap-2">
      <div class="flex space-x-1" id="tabContainer">
        <button onclick="setFilter('ALL')" id="tab-ALL" class="tab-btn px-3 py-1 text-xs font-medium rounded-md bg-blue-600 text-white">全部活跃进程 ({len(procs)})</button>
        <button onclick="setFilter('冗余预装')" id="tab-冗余预装" class="tab-btn px-3 py-1 text-xs font-medium rounded-md text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-[#333]">🔥 冗余预装 ({bloat_count})</button>
        <button onclick="setFilter('核心服务')" id="tab-核心服务" class="tab-btn px-3 py-1 text-xs font-medium rounded-md text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-[#333]">🚀 核心微服务 (4)</button>
        <button onclick="setFilter('前台残留')" id="tab-前台残留" class="tab-btn px-3 py-1 text-xs font-medium rounded-md text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-[#333]">📱 前台残留 App (4)</button>
        <button onclick="setFilter('系统底层')" id="tab-系统底层" class="tab-btn px-3 py-1 text-xs font-medium rounded-md text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-[#333]">🛡️ Android 系统底层</button>
      </div>

      <button onclick="toggleOptimizeModal()" class="px-3 py-1 text-xs font-semibold rounded-md bg-gradient-to-r from-orange-500 to-amber-600 text-white shadow hover:opacity-90 flex items-center space-x-1">
        <svg class="w-3.5 h-3.5 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
        <span>一键安全瘦身指导</span>
      </button>
    </div>

    <!-- Process Table -->
    <div class="flex-1 overflow-auto">
      <table class="w-full text-left text-xs border-collapse">
        <thead class="sticky top-0 bg-[#f9fafb] dark:bg-[#252526] text-gray-600 dark:text-gray-400 border-b border-gray-200 dark:border-[#333] z-10">
          <tr>
            <th class="py-2.5 px-4 font-semibold cursor-pointer hover:text-blue-500" onclick="sortBy('title')">进程名称 / 服务描述</th>
            <th class="py-2.5 px-3 font-semibold">PID</th>
            <th class="py-2.5 px-3 font-semibold">分类标签</th>
            <th class="py-2.5 px-3 font-semibold text-right cursor-pointer hover:text-blue-500" onclick="sortBy('cpu_float')">CPU</th>
            <th class="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-blue-500" onclick="sortBy('mem_mb')">物理内存 (RSS) ▼</th>
            <th class="py-2.5 px-4 font-semibold">处置建议 / 状态</th>
          </tr>
        </thead>
        <tbody id="procTableBody" class="divide-y divide-gray-100 dark:divide-[#282828]">
          <!-- Injected via JS -->
        </tbody>
      </table>
    </div>

    <!-- Status Footer -->
    <div class="px-4 py-2 bg-[#f9fafb] dark:bg-[#252526] border-t border-gray-200 dark:border-[#2d2d2d] text-xs text-gray-500 flex justify-between items-center">
      <span>已加载 <span id="visibleCount" class="font-bold">{len(procs)}</span> 个活跃进程 | 骁龙 888 8 核在线</span>
      <span class="text-gray-400">免 Root 纯无感服务架构</span>
    </div>

  </div>

  <!-- Optimize Modal -->
  <div id="optimizeModal" class="hidden fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
    <div class="bg-white dark:bg-[#1e1e1e] rounded-xl max-w-2xl w-full p-5 border border-gray-300 dark:border-[#333] shadow-2xl">
      <div class="flex justify-between items-center pb-3 border-b border-gray-200 dark:border-[#333]">
        <h3 class="font-bold text-base text-gray-900 dark:text-white flex items-center">
          <span class="mr-2 text-orange-500">⚡</span> 一加 9 免 Root 瘦身提速脚本
        </h3>
        <button onclick="toggleOptimizeModal()" class="text-gray-400 hover:text-gray-600 text-lg">&times;</button>
      </div>
      <div class="mt-3 text-xs text-gray-600 dark:text-gray-300 leading-relaxed">
        <p class="mb-2">手机长期作为家庭服务器时，OPPO 自带的金融借贷、运动计步、智能手表手环等服务会在后台频繁自启并吞噬近 <b>2.8 GB 内存</b>。</p>
        <p class="mb-3">我们使用 Android 原生 <code>pm disable-user</code> 命令将其安全“冻结”（<b>100% 安全、完全可逆，随时可通过 enable 恢复</b>）：</p>
        
        <div class="relative bg-gray-900 text-green-400 p-3 rounded-lg font-mono text-[11px] overflow-auto max-h-56">
          <pre id="disableScript">adb shell "
# 1. 停用金融钱包与推广推送
pm disable-user --user 0 com.finshell.wallet
pm disable-user --user 0 com.opos.ads
pm disable-user --user 0 com.oplus.appdetail

# 2. 停用运动计步与健康服务 (手机在桌上无需计步)
pm disable-user --user 0 com.heytap.health
pm disable-user --user 0 com.oplus.healthservice

# 3. 停用蓝牙穿戴/手表手环生态常驻
pm disable-user --user 0 com.heytap.accessory
pm disable-user --user 0 com.heytap.mydevices

# 4. 停用全局搜索与负一屏卡片
pm disable-user --user 0 com.heytap.quicksearchbox
pm disable-user --user 0 com.coloros.assistantscreen
pm disable-user --user 0 com.coloros.sceneservice

# 5. 停用冗余原厂服务
pm disable-user --user 0 com.oplus.statistics.rom
pm disable-user --user 0 com.oplus.aiunit
pm disable-user --user 0 com.microsoft.appmanager
pm disable-user --user 0 com.oplus.remotecontrol
pm disable-user --user 0 com.coloros.smartsidebar
"</pre>
        </div>
      </div>
      <div class="mt-4 flex justify-end space-x-2">
        <button onclick="copyScript()" class="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded text-xs font-semibold">
          一键复制优化命令
        </button>
        <button onclick="toggleOptimizeModal()" class="px-3 py-1.5 bg-gray-200 dark:bg-[#333] text-gray-700 dark:text-gray-300 rounded text-xs">
          关闭
        </button>
      </div>
    </div>
  </div>

  <script>
    const allProcs = {json.dumps(procs, ensure_ascii=False)};
    let currentFilter = 'ALL';
    let currentSort = 'mem_mb';
    let sortAsc = false;

    function renderTable() {{
      const tbody = document.getElementById('procTableBody');
      const search = document.getElementById('searchInput').value.toLowerCase();
      
      let list = allProcs.filter(p => {{
        if (currentFilter !== 'ALL' && p.category !== currentFilter) return false;
        if (search) {{
          return p.title.toLowerCase().includes(search) || 
                 p.raw_name.toLowerCase().includes(search) || 
                 p.pid.toString().includes(search);
        }}
        return true;
      }});

      list.sort((a, b) => {{
        let v1 = a[currentSort];
        let v2 = b[currentSort];
        if (typeof v1 === 'string') {{
          return sortAsc ? v1.localeCompare(v2) : v2.localeCompare(v1);
        }}
        return sortAsc ? v1 - v2 : v2 - v1;
      }});

      document.getElementById('visibleCount').innerText = list.length;

      let html = '';
      list.forEach(p => {{
        let badgeColor = 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300';
        if (p.category === '核心服务') badgeColor = 'bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300 border border-blue-300';
        else if (p.category === '冗余预装') badgeColor = 'bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300 font-semibold';
        else if (p.category === '前台残留') badgeColor = 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300';
        else if (p.category === '系统底层') badgeColor = 'bg-gray-100 text-gray-500 dark:bg-[#222] dark:text-gray-400';

        let actionHtml = '';
        if (p.safe_disable) {{
          actionHtml = `<span class="px-2 py-0.5 rounded text-[11px] font-medium bg-red-50 text-red-600 dark:bg-red-950 dark:text-red-400 border border-red-200 dark:border-red-900">建议停用/冻结</span>`;
        }} else if (p.category === '核心服务') {{
          actionHtml = `<span class="px-2 py-0.5 rounded text-[11px] font-semibold bg-green-50 text-green-600 dark:bg-green-950 dark:text-green-300">守护保活 (必留)</span>`;
        }} else {{
          actionHtml = `<span class="text-gray-400 text-[11px]">系统正常运转</span>`;
        }}

        html += `
          <tr class="hover:bg-blue-50/50 dark:hover:bg-[#252528] transition-colors">
            <td class="py-2.5 px-4">
              <div class="font-semibold text-gray-900 dark:text-gray-100 flex items-center">
                ${{p.category === '核心服务' ? '⭐ ' : ''}}${{p.title}}
              </div>
              <div class="text-[11px] text-gray-400 font-mono">${{p.raw_name}}</div>
              <div class="text-[11px] text-gray-500 mt-0.5">${{p.desc}}</div>
            </td>
            <td class="py-2.5 px-3 font-mono text-gray-500">${{p.pid}}</td>
            <td class="py-2.5 px-3">
              <span class="px-2 py-0.5 rounded text-[10px] ${{badgeColor}}">${{p.category}}</span>
            </td>
            <td class="py-2.5 px-3 text-right font-mono ${{p.cpu_float > 1.0 ? 'font-bold text-blue-600' : 'text-gray-400'}}">${{p.cpu}}</td>
            <td class="py-2.5 px-4 text-right font-mono font-semibold ${{p.mem_mb > 500 ? 'text-purple-600 dark:text-purple-400' : 'text-gray-800 dark:text-gray-200'}}">
              ${{p.mem_mb >= 1024 ? (p.mem_mb/1024).toFixed(2) + ' GB' : p.mem_mb + ' MB'}}
            </td>
            <td class="py-2.5 px-4">${{actionHtml}}</td>
          </tr>
        `;
      }});

      tbody.innerHTML = html;
    }}

    function setFilter(cat) {{
      currentFilter = cat;
      document.querySelectorAll('.tab-btn').forEach(btn => {{
        btn.classList.remove('bg-blue-600', 'text-white');
        btn.classList.add('text-gray-600', 'dark:text-gray-300');
      }});
      const activeBtn = document.getElementById('tab-' + cat);
      if (activeBtn) {{
        activeBtn.classList.add('bg-blue-600', 'text-white');
        activeBtn.classList.remove('text-gray-600', 'dark:text-gray-300');
      }}
      renderTable();
    }}

    function sortBy(col) {{
      if (currentSort === col) {{
        sortAsc = !sortAsc;
      }} else {{
        currentSort = col;
        sortAsc = false;
      }}
      renderTable();
    }}

    document.getElementById('searchInput').addEventListener('input', renderTable);

    function toggleOptimizeModal() {{
      const m = document.getElementById('optimizeModal');
      m.classList.toggle('hidden');
    }}

    function copyScript() {{
      const text = document.getElementById('disableScript').innerText;
      navigator.clipboard.writeText(text).then(() => {{
        alert('优化命令已复制到剪贴板！可直接在终端或由 AI 执行。');
      }});
    }}

    renderTable();
  </script>
</body>
</html>
"""

with open("task_manager.html", "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"Generated task_manager.html ({len(html_content)} bytes)")
