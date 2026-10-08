/**
 * 后端 API 封装，所有请求带 credentials 以携带 Session
 */
const API = {
  base: '/api',

  async request(method, path, body = null, formData = null) {
    const opts = {
      method,
      credentials: 'include',
      headers: {},
      // 大屏、历史成绩和会话状态必须读取刚写入的报告，避免浏览器
      // 在单页切换时复用完成面试前的 GET 响应。
      cache: method === 'GET' ? 'no-store' : 'default'
    };
    if (formData) {
      opts.body = formData;
    } else if (body && method !== 'GET') {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(this.base + path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.message || res.statusText || '请求失败');
    return data;
  },

  get(path) { return this.request('GET', path); },
  post(path, body) { return this.request('POST', path, body); },
  put(path, body) { return this.request('PUT', path, body); },
  del(path) { return this.request('DELETE', path); },
  postForm(path, formData) { return this.request('POST', path, null, formData); },

  // 认证
  login(username, password) { return this.post('/auth/login', { username, password }); },
  register(data) { return this.post('/auth/register', data); },
  logout() { return this.post('/auth/logout'); },

  // 用户
  getProfile() { return this.get('/user/profile'); },
  updateProfile(data) { return this.put('/user/profile', data); },
  exportPersonalData() { return this.get('/user/data-export'); },
  deleteOwnAccount(password) { return this.request('DELETE', '/user/account', { password: password }); },
  getPositions() { return this.get('/user/positions'); },
  getHealth() { return this.get('/health'); },

  // 管理员
  getUsers(params) {
    const q = new URLSearchParams(params).toString();
    return this.get('/admin/users' + (q ? '?' + q : ''));
  },
  createUser(data) { return this.post('/admin/users', data); },
  getUser(id) { return this.get('/admin/users/' + id); },
  updateUser(id, data) { return this.put('/admin/users/' + id, data); },
  deleteUser(id) { return this.del('/admin/users/' + id); },
  getAdminPositions(params) {
    const q = params && Object.keys(params).length ? '?' + new URLSearchParams(params).toString() : '';
    return this.get('/admin/positions' + q);
  },
  getPosition(id) { return this.get('/admin/positions/' + id); },
  createPosition(data) { return this.post('/admin/positions', data); },
  updatePosition(id, data) { return this.put('/admin/positions/' + id, data); },
  deletePosition(id) { return this.del('/admin/positions/' + id); },
  getQuestions(params) {
    const q = new URLSearchParams(params).toString();
    return this.get('/admin/questions' + (q ? '?' + q : ''));
  },
  getQuestion(id) { return this.get('/admin/questions/' + id); },
  createQuestion(data) { return this.post('/admin/questions', data); },
  updateQuestion(id, data) { return this.put('/admin/questions/' + id, data); },
  deleteQuestion(id) { return this.del('/admin/questions/' + id); },
  clearAllQuestions() { return this.del('/admin/questions/clear'); },
  getKnowledge(params) {
    const q = new URLSearchParams(params).toString();
    return this.get('/admin/knowledge' + (q ? '?' + q : ''));
  },
  getKnowledgeItem(id) { return this.get('/admin/knowledge/' + id); },
  createKnowledge(data) { return this.post('/admin/knowledge', data); },
  updateKnowledge(id, data) { return this.put('/admin/knowledge/' + id, data); },
  deleteKnowledge(id) { return this.del('/admin/knowledge/' + id); },
  refreshKnowledgeEmbeddings(data) { return this.post('/admin/knowledge/embeddings/refresh', data || {}); },
  importKnowledgeDocument(file, positionCode, source) {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('position_code', positionCode);
    if (source) fd.append('source', source);
    return this.postForm('/admin/knowledge/import', fd);
  },
  getConfig() { return this.get('/admin/config'); },
  updateConfig(data) { return this.put('/admin/config', data); },

  // 面试
  startInterview(positionCode) { return this.post('/interview/start', { position_code: positionCode }); },
  startTraining(sourceSessionId, taskId) {
    return this.post('/interview/training/start', {
      source_session_id: sourceSessionId,
      task_id: taskId
    });
  },
  replyInterview(sessionId, content, requestId) {
    return this.post('/interview/' + sessionId + '/reply', { content, request_id: requestId });
  },
  updateInterviewMessage(sessionId, messageId, content) {
    return this.request('PATCH', '/interview/' + sessionId + '/messages/' + messageId, { content });
  },
  transcribeInterviewAudio(file) {
    const fd = new FormData();
    fd.append('audio', file);
    return this.postForm('/interview/transcribe', fd);
  },
  replyInterviewAudio(sessionId, file, requestId, durationMs, confirmedContent, transcriptionReceipt) {
    const fd = new FormData();
    fd.append('audio', file);
    fd.append('request_id', requestId);
    if (durationMs != null) fd.append('duration_ms', String(Math.max(0, Math.round(durationMs))));
    if (confirmedContent != null) fd.append('confirmed_content', confirmedContent);
    if (transcriptionReceipt) fd.append('transcription_receipt', transcriptionReceipt);
    return this.postForm('/interview/' + sessionId + '/reply', fd);
  },
  finishInterview(sessionId) { return this.post('/interview/' + sessionId + '/finish'); },
  getActiveInterviewSessions() { return this.get('/interview/sessions/active'); },
  getInterviewState(sessionId) { return this.get('/interview/sessions/' + sessionId + '/state'); },
  abandonInterview(sessionId) { return this.post('/interview/sessions/' + sessionId + '/abandon'); },
  getSessions(params) {
    const q = new URLSearchParams(params).toString();
    return this.get('/interview/sessions' + (q ? '?' + q : ''));
  },
  deleteSession(sessionId) { return this.del('/interview/sessions/' + sessionId); },
  getReport(sessionId) { return this.get('/interview/sessions/' + sessionId + '/report'); },

  // 大屏
  getDashboardUser() { return this.get('/dashboard/user'); },
  getDashboardAdmin() { return this.get('/dashboard/admin'); },
};
