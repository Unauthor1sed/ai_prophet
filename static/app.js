// AI先知情报助手 - 前端API封装与应用逻辑（零CDN依赖）
const API_BASE = '/api';
let currentUser = null;
let currentPage = 'dashboard';

// ====== API封装 ======
async function api(url, options = {}) {
  const opts = { credentials: 'include', headers: {}, ...options };
  if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(opts.body);
  }
  const resp = await fetch(API_BASE + url, opts);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
  return data;
}

// ====== 认证 ======
async function checkAuth() {
  try {
    const data = await api('/auth/me');
    currentUser = data.user;
    document.getElementById('userDisplayName').textContent = currentUser.username;
    document.getElementById('userRoleBadge').textContent = getRoleName(currentUser.role);
    showAppropriateMenu();
    navigateTo('dashboard');
    return true;
  } catch (e) {
    window.location.href = '/login.html';
    return false;
  }
}

async function logout() {
  try { await api('/auth/logout', { method: 'POST' }); } catch(e) {}
  window.location.href = '/login.html';
}

function getRoleName(role) {
  const map = { individual: '普通用户', reviewer: '审核员', admin: '管理员', super_admin: '超级管理员' };
  return map[role] || role;
}

function showAppropriateMenu() {
  const role = currentUser.role;
  document.getElementById('menu-paper').style.display = 'block';
  document.getElementById('menu-reports').style.display = 'block';
  document.getElementById('menu-review').style.display = (['reviewer', 'admin', 'super_admin'].includes(role)) ? 'block' : 'none';
  document.getElementById('menu-words').style.display = (['admin', 'super_admin'].includes(role)) ? 'block' : 'none';
  document.getElementById('menu-sources').style.display = (['admin', 'super_admin'].includes(role)) ? 'block' : 'none';
  document.getElementById('menu-users').style.display = role === 'super_admin' ? 'block' : 'none';
}

// ====== 页面导航 ======
function navigateTo(page) {
  currentPage = page;
  document.querySelectorAll('.page').forEach(p => p.style.display = 'none');
  document.querySelectorAll('.menu-item').forEach(m => m.classList.remove('active'));
  
  const target = document.getElementById('page-' + page);
  const menuItem = document.getElementById('menu-' + page);
  if (target) target.style.display = 'block';
  if (menuItem) menuItem.classList.add('active');
  
  // 加载页面数据
  loadPageData(page);
}

function loadPageData(page) {
  switch(page) {
    case 'dashboard': loadDashboard(); break;
    case 'review': loadReviews(); break;
    case 'words': loadSensitiveWords(); break;
    case 'sources': loadNewsSources(); break;
    case 'users': loadUsers(); break;
    case 'reports': loadNewsDates(); break;
    case 'paper': loadPaperTasks(); break;
  }
}

// ====== 工具函数 ======
function formatDate(d) {
  if (!d) return '';
  const date = new Date(d);
  return date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}
function showToast(msg, type = 'info') {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.className = 'toast show ' + type;
  setTimeout(() => toast.className = 'toast', 3000);
}
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ====== 看板 ======
async function loadDashboard() {
  try {
    const stats = await api('/dashboard/stats');
    const reviewStats = await api('/reviews/stats');
    document.getElementById('stat-total-news').textContent = stats.total_news || 0;
    document.getElementById('stat-today-news').textContent = stats.today_news || 0;
    document.getElementById('stat-pending').textContent = reviewStats.pending || 0;
    document.getElementById('stat-users').textContent = stats.total_users || 0;
    document.getElementById('stat-sources').textContent = stats.total_sources || 0;
  } catch (e) {
    showToast('加载统计失败: ' + e.message, 'error');
  }
}

// ====== 审核 ======
async function loadReviews() {
  const container = document.getElementById('review-list');
  container.innerHTML = '<div class="loading"><div class="spinner"></div>加载中...</div>';
  try {
    const data = await api('/reviews');
    const items = data.items || [];
    if (items.length === 0) {
      container.innerHTML = '<div class="empty-state"><div class="icon">✅</div><p>暂无待审核内容</p></div>';
      return;
    }
    container.innerHTML = items.map(item => `
      <div class="review-card" data-id="${item.id}">
        <div class="review-header">
          <span class="source-tag">${escapeHtml(item.source || '未知来源')}</span>
          <span class="time">${formatDate(item.created_at)}</span>
        </div>
        <h4>${escapeHtml(item.translated_title || item.title)}</h4>
        ${item.summary ? `<p class="summary">${escapeHtml(item.summary)}</p>` : ''}
        <div class="review-actions">
          <button class="btn-approve" onclick="handleReview(${item.id}, 'approve')">✅ 通过</button>
          <button class="btn-reject" onclick="handleReview(${item.id}, 'reject')">❌ 拒绝</button>
          <a href="${escapeHtml(item.url)}" target="_blank" class="btn-view">查看原文</a>
        </div>
        <div class="review-comment">
          <input type="text" id="comment-${item.id}" placeholder="审核备注（可选）" />
        </div>
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><p style="color:#f87171">加载失败: ${escapeHtml(e.message)}</p></div>`;
  }
}

async function handleReview(id, action) {
  const comment = document.getElementById('comment-' + id)?.value || '';
  try {
    await api(`/reviews/${id}/action`, { method: 'POST', body: { action, comment } });
    showToast(action === 'approve' ? '已通过' : '已拒绝', 'success');
    loadReviews();
    loadDashboard();
  } catch (e) {
    showToast('操作失败: ' + e.message, 'error');
  }
}

// ====== 敏感词 ======
async function loadSensitiveWords() {
  const container = document.getElementById('words-list');
  container.innerHTML = '<div class="loading"><div class="spinner"></div>加载中...</div>';
  try {
    const data = await api('/sensitive-words');
    const items = data.items || [];
    if (items.length === 0) {
      container.innerHTML = '<div class="empty-state"><p>暂无敏感词</p></div>';
      return;
    }
    container.innerHTML = items.map(w => `
      <div class="word-item">
        <span class="word-text">${escapeHtml(w.word)}</span>
        <span class="word-cat">${escapeHtml(w.category)}</span>
        <button class="btn-del" onclick="deleteWord(${w.id})">删除</button>
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = `<p style="color:#f87171">${escapeHtml(e.message)}</p>`;
  }
}

async function addWord() {
  const word = document.getElementById('new-word').value.trim();
  const cat = document.getElementById('new-word-cat').value;
  if (!word) return showToast('请输入敏感词', 'error');
  try {
    await api('/sensitive-words', { method: 'POST', body: { word, category: cat } });
    document.getElementById('new-word').value = '';
    showToast('添加成功', 'success');
    loadSensitiveWords();
  } catch (e) { showToast(e.message, 'error'); }
}

async function deleteWord(id) {
  if (!confirm('确定删除？')) return;
  try { await api(`/sensitive-words/${id}`, { method: 'DELETE' }); loadSensitiveWords(); } 
  catch (e) { showToast(e.message, 'error'); }
}

// ====== 资讯源 ======
async function loadNewsSources() {
  const container = document.getElementById('sources-list');
  container.innerHTML = '<div class="loading"><div class="spinner"></div>加载中...</div>';
  try {
    const data = await api('/news-sources');
    const items = data.items || [];
    if (items.length === 0) {
      container.innerHTML = '<div class="empty-state"><p>暂无资讯源</p></div>';
      return;
    }
    container.innerHTML = items.map(s => `
      <div class="source-item">
        <div>
          <strong>${escapeHtml(s.name)}</strong>
          <span class="source-type">${escapeHtml(s.source_type)}</span>
          <div class="source-url">${escapeHtml(s.url)}</div>
        </div>
        <div class="source-actions">
          <button class="${s.is_active ? 'btn-reject' : 'btn-approve'}" onclick="toggleSource(${s.id})">${s.is_active ? '禁用' : '启用'}</button>
          <button class="btn-del" onclick="deleteSource(${s.id})">删除</button>
        </div>
      </div>
    `).join('');
  } catch (e) { container.innerHTML = `<p style="color:#f87171">${escapeHtml(e.message)}</p>`; }
}

async function addSource() {
  const name = document.getElementById('new-source-name').value.trim();
  const url = document.getElementById('new-source-url').value.trim();
  if (!name || !url) return showToast('请填写名称和URL', 'error');
  try {
    await api('/news-sources', { method: 'POST', body: { name, url } });
    document.getElementById('new-source-name').value = '';
    document.getElementById('new-source-url').value = '';
    showToast('添加成功', 'success');
    loadNewsSources();
  } catch (e) { showToast(e.message, 'error'); }
}

async function toggleSource(id) {
  try { await api(`/news-sources/${id}/toggle`, { method: 'POST' }); loadNewsSources(); } 
  catch (e) { showToast(e.message, 'error'); }
}

async function deleteSource(id) {
  if (!confirm('确定删除？')) return;
  try { await api(`/news-sources/${id}`, { method: 'DELETE' }); loadNewsSources(); } 
  catch (e) { showToast(e.message, 'error'); }
}

// ====== 用户管理（超管） ======
async function loadUsers() {
  const container = document.getElementById('users-list');
  container.innerHTML = '<div class="loading"><div class="spinner"></div>加载中...</div>';
  try {
    const data = await api('/users');
    const items = data.items || [];
    container.innerHTML = items.map(u => `
      <div class="user-item">
        <div>
          <strong>${escapeHtml(u.username)}</strong>
          <span class="role-badge role-${u.role}">${getRoleName(u.role)}</span>
          ${!u.is_active ? '<span class="disabled">已禁用</span>' : ''}
          <div class="user-time">注册: ${formatDate(u.created_at)}</div>
        </div>
        <select onchange="changeUserRole(${u.id}, this.value)" class="role-select">
          <option value="individual" ${u.role==='individual'?'selected':''}>普通用户</option>
          <option value="reviewer" ${u.role==='reviewer'?'selected':''}>审核员</option>
          <option value="admin" ${u.role==='admin'?'selected':''}>管理员</option>
          <option value="super_admin" ${u.role==='super_admin'?'selected':''}>超级管理员</option>
        </select>
      </div>
    `).join('');
  } catch (e) { container.innerHTML = `<p style="color:#f87171">${escapeHtml(e.message)}</p>`; }
}

async function changeUserRole(userId, newRole) {
  try { await api('/users/role', { method: 'POST', body: { user_id: userId, role: newRole } }); showToast('角色已更新', 'success'); } 
  catch (e) { showToast(e.message, 'error'); loadUsers(); }
}

// ====== 早报查询 ======
async function loadNewsDates() {
  const select = document.getElementById('report-date');
  select.innerHTML = '<option value="">加载中...</option>';
  try {
    const data = await api('/news/dates');
    const dates = data.dates || [];
    if (dates.length === 0) { select.innerHTML = '<option value="">暂无数据</option>'; return; }
    select.innerHTML = dates.map(d => `<option value="${d}">${d}</option>`).join('');
    if (dates.length > 0) loadNewsByDate(dates[0]);
  } catch (e) { showToast(e.message, 'error'); }
}

async function loadNewsByDate(date) {
  if (!date) return;
  const container = document.getElementById('news-list');
  container.innerHTML = '<div class="loading"><div class="spinner"></div>加载中...</div>';
  try {
    const data = await api('/news?date=' + date);
    const items = data.items || [];
    if (items.length === 0) { container.innerHTML = '<div class="empty-state"><p>该日期无内容</p></div>'; return; }
    container.innerHTML = items.map(n => `
      <div class="news-item">
        <div class="news-header">
          <span class="source-tag">${escapeHtml(n.source || '未知')}</span>
          <span class="score">相关度: ${(n.relevance_score * 100).toFixed(0)}%</span>
        </div>
        <h4><a href="${escapeHtml(n.url)}" target="_blank">${escapeHtml(n.translated_title || n.title)}</a></h4>
        ${n.summary ? `<p class="news-summary">${escapeHtml(n.summary)}</p>` : ''}
      </div>
    `).join('');
  } catch (e) { container.innerHTML = `<p style="color:#f87171">${escapeHtml(e.message)}</p>`; }
}

// ====== 论文精析 ======
let paperPollTimer = null;

async function submitPaper() {
  const fileInput = document.getElementById('paper-file');
  const titleInput = document.getElementById('paper-title');
  const file = fileInput.files[0];
  
  if (!file) return showToast('请选择PDF文件', 'error');
  if (!file.name.toLowerCase().endsWith('.pdf')) return showToast('请上传PDF文件', 'error');
  if (file.size > 50 * 1024 * 1024) return showToast('文件不能超过50MB', 'error');

  const formData = new FormData();
  formData.append('file', file);
  formData.append('title', titleInput.value.trim());

  const btn = document.getElementById('btn-submit-paper');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>上传中...';

  try {
    const result = await api('/papers/upload', { method: 'POST', body: formData });
    showToast('论文已提交，开始分析！', 'success');
    fileInput.value = '';
    titleInput.value = '';
    loadPaperTasks();
    startPolling();
  } catch (e) {
    showToast('上传失败: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '提交分析';
  }
}

async function loadPaperTasks() {
  const container = document.getElementById('paper-tasks');
  try {
    const data = await api('/papers/tasks');
    const tasks = data.items || [];
    if (tasks.length === 0) {
      container.innerHTML = '<div class="empty-state"><p>暂无分析任务</p></div>';
      return;
    }
    container.innerHTML = tasks.map(t => {
      const isRunning = ['pending', 'parsing', 'analyzing', 'generating'].includes(t.status);
      const isDone = t.status === 'completed';
      const isFailed = t.status === 'failed';
      return `
        <div class="paper-task ${isDone ? 'done' : ''} ${isFailed ? 'failed' : ''}">
          <div class="task-header">
            <strong>${escapeHtml(t.title || '未命名论文')}</strong>
            <span class="task-status status-${t.status}">${getStatusText(t.status)}</span>
          </div>
          <div class="task-filename">${escapeHtml(t.original_filename || '')}</div>
          <div class="progress-bar"><div class="progress-fill" style="width:${t.progress}%"></div></div>
          <div class="progress-text">${escapeHtml(t.progress_msg || '')}</div>
          ${t.analysis_result ? `<div class="task-result"><pre>${escapeHtml(t.analysis_result.substring(0, 2000))}</pre></div>` : ''}
          ${t.report_url ? `<a href="${t.report_url}" target="_blank" class="btn-download">📄 下载完整报告</a>` : ''}
          ${t.error_msg ? `<div class="error-msg">错误: ${escapeHtml(t.error_msg)}</div>` : ''}
          <div class="task-time">提交时间: ${formatDate(t.created_at)}</div>
        </div>
      `;
    }).join('');
    
    // 如果有运行中的任务，继续轮询
    const hasRunning = tasks.some(t => ['pending', 'parsing', 'analyzing', 'generating'].includes(t.status));
    if (hasRunning) {
      if (!paperPollTimer) startPolling();
    } else {
      stopPolling();
    }
  } catch (e) {
    container.innerHTML = `<p style="color:#f87171">${escapeHtml(e.message)}</p>`;
  }
}

function getStatusText(status) {
  const map = { pending: '等待中', parsing: '解析中', analyzing: 'AI分析中', generating: '生成报告中', completed: '已完成', failed: '失败' };
  return map[status] || status;
}

function startPolling() {
  stopPolling();
  paperPollTimer = setInterval(loadPaperTasks, 5000);
}

function stopPolling() {
  if (paperPollTimer) { clearInterval(paperPollTimer); paperPollTimer = null; }
}

// ====== 初始化 ======
document.addEventListener('DOMContentLoaded', () => {
  checkAuth();
});
