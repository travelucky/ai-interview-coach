/**
 * 管理后台页 /admin：鉴权、Hash 路由、数据大屏/类目/知识库/用户/系统管理
 */
(function () {
  var currentUser = null;
  var positions = [];
  var adminCharts = { sessions: null, questions: null, questionType: null, scoreDistribution: null, sessionPosition: null };
  var questionsPage = 1;
  var knowledgePage = 1;
  var usersPage = 1;
  var perPage = 10;
  var modalQuestion, modalKnowledge, modalUser, modalPosition;

  function setButtonLoading(btn, loading, loadingText) {
    if (!btn) return;
    loadingText = loadingText || '加载中…';
    if (loading) {
      btn.disabled = true;
      btn.classList.add('btn-loading');
      btn.setAttribute('data-original-text', btn.textContent || '');
      btn.innerHTML = '<span class="spinner-inline"></span>' + loadingText;
    } else {
      var orig = btn.getAttribute('data-original-text');
      btn.disabled = false;
      btn.classList.remove('btn-loading');
      btn.textContent = orig || '';
      btn.removeAttribute('data-original-text');
    }
  }

  function setView(sectionId) {
    document.querySelectorAll('.view-section').forEach(function (s) { s.classList.remove('active'); });
    var el = document.getElementById(sectionId);
    if (el) el.classList.add('active');
    document.querySelectorAll('.admin-nav-link').forEach(function (a) {
      a.classList.toggle('active', a.getAttribute('data-view') === sectionId);
    });
  }

  function route() {
    var hash = (location.hash || '#dashboard').slice(1);
    var map = { dashboard: 'adminDashboard', categories: 'adminCategories', questions: 'adminQuestions', knowledge: 'adminKnowledge', users: 'adminUsers', config: 'adminConfig' };
    var view = map[hash] || 'adminDashboard';
    setView(view);
    if (hash === 'dashboard') loadAdminDashboard();
    else if (hash === 'categories') { loadPositionsList(); }
    else if (hash === 'questions') loadQuestions();
    else if (hash === 'knowledge') loadKnowledge();
    else if (hash === 'users') loadUsers();
    else if (hash === 'config') loadConfig();
  }

  function loadPositions() {
    return API.getAdminPositions().then(function (data) {
      positions = data.positions || data.items || [];
      var posSel = document.getElementById('questionPosition');
      var filterSel = document.getElementById('qFilterPosition');
      var knowledgeFilter = document.getElementById('kFilterPosition');
      var knowledgePosition = document.getElementById('knowledgePosition');
      if (posSel) {
        var cur = posSel.value;
        posSel.innerHTML = '<option value="">请选择岗位</option>';
        positions.forEach(function (p) { var o = document.createElement('option'); o.value = p.id; o.textContent = p.name; posSel.appendChild(o); });
        if (cur) posSel.value = cur;
      }
      if (filterSel) {
        var cur = filterSel.value;
        filterSel.innerHTML = '<option value="">全部岗位</option>';
        positions.forEach(function (p) { var o = document.createElement('option'); o.value = p.code; o.textContent = p.name; filterSel.appendChild(o); });
        if (cur) filterSel.value = cur;
      }
      [knowledgeFilter, knowledgePosition].forEach(function (select) {
        if (!select) return;
        var cur = select.value;
        var first = select === knowledgeFilter ? '全部岗位' : '请选择岗位';
        select.innerHTML = '<option value="">' + first + '</option>';
        positions.forEach(function (p) {
          var option = document.createElement('option');
          option.value = p.code;
          option.textContent = p.name;
          select.appendChild(option);
        });
        if (cur) select.value = cur;
      });
    }).catch(function (err) { if (window.Toast) Toast.error(window.getErrorMessage ? getErrorMessage(err) : (err && err.message)); });
  }

  function loadPositionsList() {
    var msgEl = document.getElementById('positionListMsg');
    if (msgEl) { msgEl.style.display = 'none'; msgEl.textContent = ''; }
    var tbody = document.getElementById('positionTbody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="5" class="loading">加载中…</td></tr>';
    API.getAdminPositions().then(function (data) {
      var list = data.positions || data.items || [];
      positions = list;
      if (list.length === 0) { tbody.innerHTML = '<tr><td colspan="5" class="empty-hint">暂无岗位，请点击新增岗位</td></tr>'; }
      else {
        tbody.innerHTML = list.map(function (p) {
          var desc = (p.description || '-').toString();
          if (desc.length > 40) desc = desc.slice(0, 40) + '…';
          return '<tr><td>' + escapeHtml(p.code) + '</td><td>' + escapeHtml(p.name) + '</td><td>' + escapeHtml(desc) + '</td><td><button type="button" class="btn btn-sm btn-outline-primary me-1 btn-edit-position" data-id="' + p.id + '">编辑</button> <button type="button" class="btn btn-sm btn-outline-danger btn-delete-position" data-id="' + p.id + '">删除</button></td></tr>';
        }).join('');
        tbody.querySelectorAll('.btn-edit-position').forEach(function (b) { b.addEventListener('click', function () { openPositionModal(Number(b.dataset.id)); }); });
        tbody.querySelectorAll('.btn-delete-position').forEach(function (b) { b.addEventListener('click', function () { deletePosition(Number(b.dataset.id)); }); });
      }
    }).catch(function (err) {
      var msg = (window.getErrorMessage ? getErrorMessage(err) : (err && err.message)) || '加载失败';
      tbody.innerHTML = '<tr><td colspan="5" class="empty-hint">' + escapeHtml(msg) + '</td></tr>';
      if (window.Toast) Toast.error(msg);
    });
  }

  function openPositionModal(id) {
    var errEl = document.getElementById('positionFormError');
    if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
    var codeEl = document.getElementById('positionCode');
    var nameEl = document.getElementById('positionName');
    var descEl = document.getElementById('positionDescription');
    if (id != null) {
      var pos = positions.find(function (p) { return p.id === id; });
      if (pos) {
        document.getElementById('modalPositionTitle').textContent = '编辑岗位';
        codeEl.value = pos.code;
        codeEl.readOnly = true;
        nameEl.value = pos.name || '';
        descEl.value = pos.description || '';
      } else {
        API.getPosition(id).then(function (d) {
          var p = d.position || d;
          document.getElementById('modalPositionTitle').textContent = '编辑岗位';
          codeEl.value = p.code;
          codeEl.readOnly = true;
          nameEl.value = p.name || '';
          descEl.value = p.description || '';
          modalPosition.show();
        }).catch(function (err) { if (window.Toast) Toast.error(getErrorMessage(err)); });
        return;
      }
    } else {
      document.getElementById('modalPositionTitle').textContent = '新增岗位';
      codeEl.value = '';
      codeEl.readOnly = false;
      nameEl.value = '';
      descEl.value = '';
    }
    window._positionEditId = id;
    if (id == null || positions.find(function (p) { return p.id === id; })) modalPosition.show();
  }

  function deletePosition(id) {
    if (!confirm('确定删除该岗位？若其下存在题目将无法删除。')) return;
    var msgEl = document.getElementById('positionListMsg');
    if (msgEl) { msgEl.style.display = 'none'; msgEl.textContent = ''; }
    API.deletePosition(id).then(function () { if (window.Toast) Toast.success('已删除'); loadPositionsList(); loadPositions(); }).catch(function (err) {
      var msg = getErrorMessage(err);
      if (msgEl) { msgEl.textContent = '删除失败：' + msg; msgEl.style.display = 'block'; }
      if (window.Toast) Toast.error(msg);
    });
  }

  function loadAdminDashboard() {
    var cardsEl = document.getElementById('adminStatCards');
    if (!cardsEl) return;
    cardsEl.innerHTML = '<div class="loading">加载中…</div>';
    API.getDashboardAdmin().then(function (data) {
      var stats = data.stats || data;
      var statsMap = {
        total_users: stats.total_users != null ? stats.total_users : (stats.users_count || 0),
        total_sessions: stats.total_sessions != null ? stats.total_sessions : (stats.sessions_count || 0),
        sessions_7d: stats.total_sessions_7d != null ? stats.total_sessions_7d : (stats.sessions_7d || 0),
        total_questions: stats.total_questions != null ? stats.total_questions : (stats.questions_count || 0)
      };
      cardsEl.innerHTML = [
        { label: '总用户数', value: statsMap.total_users },
        { label: '总面试场次', value: statsMap.total_sessions },
        { label: '近7日场次', value: statsMap.sessions_7d },
        { label: '知识库题目数', value: statsMap.total_questions }
      ].map(function (s) { return '<div class="stat-card"><div class="label">' + s.label + '</div><div class="value">' + s.value + '</div></div>'; }).join('');

      // 近 7 日场次 → 折线图（趋势）
      var sessionsByDay = data.sessions_by_day || [];
      var ctx = document.getElementById('adminChartSessions');
      toggleChartHint('adminChartSessionsHint', !!sessionsByDay.length);
      if (adminCharts.sessions) { adminCharts.sessions.destroy(); adminCharts.sessions = null; }
      if (ctx && sessionsByDay.length && window.Chart) {
        adminCharts.sessions = new Chart(ctx.getContext('2d'), {
          type: 'line',
          data: {
            labels: sessionsByDay.map(function (d) { return (d.date || '').toString().slice(5); }),
            datasets: [{ label: '场次', data: sessionsByDay.map(function (d) { return d.count; }), borderColor: '#006EFF', backgroundColor: 'rgba(0,110,255,0.12)', fill: true, tension: 0.3, pointRadius: 4 }]
          },
          options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } } }
        });
      }
      // 各岗位题目数量 → 饼图
      var questionsByPosition = data.questions_by_position || [];
      var ctx2 = document.getElementById('adminChartQuestions');
      toggleChartHint('adminChartQuestionsHint', !!questionsByPosition.length);
      if (adminCharts.questions) { adminCharts.questions.destroy(); adminCharts.questions = null; }
      if (ctx2 && questionsByPosition.length && window.Chart) {
        var qColors = ['rgba(0,110,255,0.85)', 'rgba(5,150,105,0.85)', 'rgba(245,158,11,0.85)', 'rgba(239,68,68,0.85)', 'rgba(139,92,246,0.85)'];
        adminCharts.questions = new Chart(ctx2.getContext('2d'), {
          type: 'pie',
          data: {
            labels: questionsByPosition.map(function (p) { return (p.position_name || p.position_code) + ' (' + (p.count || 0) + ')'; }),
            datasets: [{ data: questionsByPosition.map(function (p) { return p.count; }), backgroundColor: qColors.slice(0, questionsByPosition.length), borderWidth: 2, borderColor: '#fff' }]
          },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
        });
      }
      // 题目类型分布 → 雷达图
      var questionsByType = data.questions_by_type || [];
      var ctx3 = document.getElementById('adminChartQuestionType');
      toggleChartHint('adminChartQuestionTypeHint', questionsByType.some(function (t) { return t.count > 0; }));
      if (adminCharts.questionType) { adminCharts.questionType.destroy(); adminCharts.questionType = null; }
      if (ctx3 && window.Chart) {
        var typeLabels = questionsByType.map(function (t) { return t.type_name || t.type || ''; });
        var typeData = questionsByType.map(function (t) { return t.count; });
        adminCharts.questionType = new Chart(ctx3.getContext('2d'), {
          type: 'radar',
          data: {
            labels: typeLabels,
            datasets: [{ label: '题目数', data: typeData, backgroundColor: 'rgba(0,110,255,0.2)', borderColor: '#006EFF', borderWidth: 2, pointBackgroundColor: '#006EFF' }]
          },
          options: { responsive: true, maintainAspectRatio: false, scales: { r: { min: 0, beginAtZero: true, ticks: { stepSize: 1 } } }, plugins: { legend: { display: false } } }
        });
      }
      // 用户得分分布 → 竖向柱状图（待提升/良好/优秀）
      var scoreDistribution = data.score_distribution || [];
      var ctx4 = document.getElementById('adminChartScoreDistribution');
      var hasScoreData = scoreDistribution.some(function (d) { return (d.count || 0) > 0; });
      toggleChartHint('adminChartScoreDistributionHint', !hasScoreData);
      if (adminCharts.scoreDistribution) { adminCharts.scoreDistribution.destroy(); adminCharts.scoreDistribution = null; }
      if (ctx4 && window.Chart) {
        var distLabels = scoreDistribution.map(function (d) { return d.label + ' (' + (d.range || '') + '分)'; });
        var distData = scoreDistribution.map(function (d) { return d.count || 0; });
        var distColors = ['rgba(239,68,68,0.85)', 'rgba(245,158,11,0.85)', 'rgba(5,150,105,0.85)'];
        adminCharts.scoreDistribution = new Chart(ctx4.getContext('2d'), {
          type: 'bar',
          data: {
            labels: distLabels,
            datasets: [{ label: '场次数', data: distData, backgroundColor: distColors.slice(0, scoreDistribution.length), borderRadius: 6, borderSkipped: false }]
          },
          options: { responsive: true, maintainAspectRatio: false, barPercentage: 0.6, categoryPercentage: 0.8, scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } }, plugins: { legend: { display: false } } }
        });
      }
      // 各岗位面试场次占比 → 折线图（岗位-场次）
      var sessionsByPosition = data.sessions_by_position || [];
      var ctx5 = document.getElementById('adminChartSessionPosition');
      toggleChartHint('adminChartSessionPositionHint', sessionsByPosition.length > 0);
      if (adminCharts.sessionPosition) { adminCharts.sessionPosition.destroy(); adminCharts.sessionPosition = null; }
      if (ctx5 && sessionsByPosition.length && window.Chart) {
        var posLabels = sessionsByPosition.map(function (p) { return p.position_name || p.position_code; });
        adminCharts.sessionPosition = new Chart(ctx5.getContext('2d'), {
          type: 'line',
          data: {
            labels: posLabels,
            datasets: [{ label: '场次', data: sessionsByPosition.map(function (p) { return p.count; }), borderColor: '#006EFF', backgroundColor: 'rgba(0,110,255,0.12)', fill: true, tension: 0.3, pointRadius: 4 }]
          },
          options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } }, plugins: { legend: { display: false } } }
        });
      }
      var recentActivity = data.recent_activity || [];
      var tbody = document.getElementById('adminRecentActivityBody');
      var hintEl = document.getElementById('adminRecentActivityHint');
      if (tbody) {
        if (recentActivity.length === 0) { tbody.innerHTML = ''; if (hintEl) { hintEl.style.display = 'block'; } }
        else {
          if (hintEl) hintEl.style.display = 'none';
          tbody.innerHTML = recentActivity.map(function (a) {
            var timeStr = (a.started_at || '').replace('T', ' ').slice(0, 19);
            return '<tr><td>' + (a.session_id || '-') + '</td><td>' + escapeHtml(a.user_name || a.user_id || '-') + '</td><td>' + escapeHtml(a.position_name || a.position_code || '-') + '</td><td>' + escapeHtml(timeStr) + '</td><td>' + escapeHtml(a.status_label || a.status || '-') + '</td></tr>';
          }).join('');
        }
      }
    }).catch(function (err) {
      var msg = (window.getErrorMessage ? getErrorMessage(err) : (err && err.message)) || '加载失败';
      cardsEl.innerHTML = '<div class="empty-hint">' + msg + '</div>';
      if (window.Toast) Toast.error(msg);
    });
  }
  function toggleChartHint(id, hasData) {
    var el = document.getElementById(id);
    if (el) el.style.display = hasData ? 'none' : 'block';
  }

  function loadQuestions() {
    var msgEl = document.getElementById('questionListMsg');
    if (msgEl) { msgEl.style.display = 'none'; msgEl.textContent = ''; }
    var tbody = document.getElementById('questionTbody');
    if (!tbody) return Promise.resolve();
    tbody.innerHTML = '<tr><td colspan="5" class="loading">加载中…</td></tr>';
    var positionCode = document.getElementById('qFilterPosition') && document.getElementById('qFilterPosition').value;
    var keywordEl = document.getElementById('qSearchKeyword');
    var keyword = keywordEl ? keywordEl.value.trim() : '';
    var params = { page: questionsPage, per_page: perPage };
    if (positionCode) params.position_code = positionCode;
    if (keyword) params.keyword = keyword;
    return API.getQuestions(params).then(function (data) {
      var list = data.questions || data.items || [];
      var total = data.total != null ? data.total : list.length;
      if (list.length === 0) { tbody.innerHTML = '<tr><td colspan="5" class="empty-hint">暂无题目</td></tr>'; }
      else {
        tbody.innerHTML = list.map(function (q) {
          var text = (q.content || '').slice(0, 60) + ((q.content && q.content.length > 60) ? '…' : '');
          var statusLabels = { pending: '待审核', in_review: '审核中', reviewed: '人工通过', ai_reviewed: 'AI 辅助', rejected: '退回' };
          var core = q.is_core ? '<span class="badge text-bg-primary me-1">核心</span>' : '';
          return '<tr><td>' + escapeHtml(text) + '<div class="small text-secondary">v' + escapeHtml(String(q.content_version || 1)) + ' / ' + escapeHtml(q.source || '-') + '</div></td><td>' + escapeHtml(q.question_type || q.type || '-') + ' / L' + escapeHtml(String(q.difficulty || 1)) + '</td><td>' + escapeHtml(q.position_code || '-') + '</td><td>' + core + escapeHtml(statusLabels[q.review_status] || q.review_status || '待审核') + '</td><td><button type="button" class="btn btn-sm btn-outline-primary me-1 btn-edit-question" data-id="' + q.id + '">编辑</button> <button type="button" class="btn btn-sm btn-outline-danger btn-delete-question" data-id="' + q.id + '">删除</button></td></tr>';
        }).join('');
        tbody.querySelectorAll('.btn-edit-question').forEach(function (b) { b.addEventListener('click', function () { openQuestionModal(Number(b.dataset.id)); }); });
        tbody.querySelectorAll('.btn-delete-question').forEach(function (b) { b.addEventListener('click', function () { deleteQuestion(Number(b.dataset.id)); }); });
      }
      renderPagination(document.getElementById('questionPagination'), questionsPage, total, perPage, function (p) { questionsPage = p; loadQuestions(); });
    }).catch(function (err) {
      var msg = (window.getErrorMessage ? getErrorMessage(err) : (err && err.message)) || '加载失败';
      tbody.innerHTML = '<tr><td colspan="5" class="empty-hint">' + escapeHtml(msg) + '</td></tr>';
      if (window.Toast) Toast.error(msg);
    });
  }

  function openQuestionModal(id) {
    var errEl = document.getElementById('questionFormError');
    if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
    var modalTitle = document.getElementById('modalQuestionTitle');
    var contentEl = document.getElementById('questionContent');
    var typeEl = document.getElementById('questionType');
    var refEl = document.getElementById('questionRefAnswer');
    var difficultyEl = document.getElementById('questionDifficulty');
    var topicEl = document.getElementById('questionTopic');
    var tagsEl = document.getElementById('questionTags');
    var sourceEl = document.getElementById('questionSource');
    var reviewEl = document.getElementById('questionReviewStatus');
    var reviewerEl = document.getElementById('questionReviewer');
    var coreEl = document.getElementById('questionIsCore');
    var posSel = document.getElementById('questionPosition');
    if (posSel) {
      posSel.innerHTML = '<option value="">请选择岗位</option>';
      positions.forEach(function (p) { var o = document.createElement('option'); o.value = p.id; o.textContent = p.name; posSel.appendChild(o); });
    }
    if (id != null) {
      API.getQuestion(id).then(function (d) {
        var q = d.question || d;
        modalTitle.textContent = '编辑题目';
        contentEl.value = q.content || '';
        typeEl.value = q.question_type || q.type || 'technical';
        refEl.value = q.reference_answer || '';
        difficultyEl.value = q.difficulty || 1;
        topicEl.value = q.topic || '';
        tagsEl.value = q.tags || '';
        sourceEl.value = q.source || '';
        reviewEl.value = q.review_status || 'pending';
        reviewerEl.value = q.reviewer || '';
        coreEl.checked = Boolean(q.is_core);
        if (posSel && q.position_id) posSel.value = q.position_id;
        window._questionEditId = id;
        modalQuestion.show();
      }).catch(function (err) { if (window.Toast) Toast.error(getErrorMessage(err)); });
    } else {
      modalTitle.textContent = '新增题目';
      contentEl.value = ''; refEl.value = ''; typeEl.value = 'technical'; difficultyEl.value = 2;
      topicEl.value = ''; tagsEl.value = ''; sourceEl.value = 'admin'; reviewEl.value = 'pending'; reviewerEl.value = ''; coreEl.checked = false;
      if (posSel) posSel.value = '';
      window._questionEditId = null;
      modalQuestion.show();
    }
  }

  function deleteQuestion(id) {
    if (!confirm('确定删除该题目？')) return;
    var msgEl = document.getElementById('questionListMsg');
    if (msgEl) { msgEl.style.display = 'none'; msgEl.textContent = ''; }
    API.deleteQuestion(id).then(function () {
      if (window.Toast) Toast.success('已删除');
      questionsPage = 1;
      loadQuestions();
    }).catch(function (err) {
      var msg = getErrorMessage(err);
      if (msgEl) { msgEl.textContent = '删除失败：' + msg; msgEl.style.display = 'block'; }
      if (window.Toast) Toast.error(msg);
    });
  }

  function loadKnowledge() {
    var tbody = document.getElementById('knowledgeTbody');
    if (!tbody) return Promise.resolve();
    tbody.innerHTML = '<tr><td colspan="5" class="loading">加载中…</td></tr>';
    var positionCode = document.getElementById('kFilterPosition').value;
    var keyword = document.getElementById('kSearchKeyword').value.trim();
    var params = { page: knowledgePage, per_page: perPage };
    if (positionCode) params.position_code = positionCode;
    if (keyword) params.keyword = keyword;
    return API.getKnowledge(params).then(function (data) {
      var list = data.items || [];
      if (!list.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-hint">暂无匹配的知识条目</td></tr>';
      } else {
        tbody.innerHTML = list.map(function (item) {
          var title = String(item.title || '').slice(0, 60);
          var meta = [item.topic, item.source].filter(Boolean).join(' / ') || '-';
          var embedding = item.embedding_status === 'ready'
            ? '<span class="badge text-bg-success">已就绪</span><div class="small text-secondary">' + escapeHtml(item.embedding_model || '') + '</div>'
            : '<span class="badge text-bg-warning">待更新</span>';
          return '<tr><td>' + escapeHtml(title) + '</td><td>' + escapeHtml(item.position_code || '-') + '</td><td>' + escapeHtml(meta) + '</td><td>' + embedding + '</td><td><button type="button" class="btn btn-sm btn-outline-primary me-1 btn-edit-knowledge" data-id="' + item.id + '">编辑</button><button type="button" class="btn btn-sm btn-outline-danger btn-delete-knowledge" data-id="' + item.id + '">删除</button></td></tr>';
        }).join('');
        tbody.querySelectorAll('.btn-edit-knowledge').forEach(function (button) {
          button.addEventListener('click', function () { openKnowledgeModal(Number(button.dataset.id)); });
        });
        tbody.querySelectorAll('.btn-delete-knowledge').forEach(function (button) {
          button.addEventListener('click', function () { deleteKnowledge(Number(button.dataset.id)); });
        });
      }
      renderPagination(document.getElementById('knowledgePagination'), knowledgePage, data.total || 0, perPage, function (page) {
        knowledgePage = page;
        loadKnowledge();
      });
    }).catch(function (err) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-hint">' + escapeHtml(getErrorMessage(err)) + '</td></tr>';
      if (window.Toast) Toast.error(getErrorMessage(err));
    });
  }

  function openKnowledgeModal(id) {
    var error = document.getElementById('knowledgeFormError');
    if (error) { error.style.display = 'none'; error.textContent = ''; }
    var fill = function (item) {
      document.getElementById('modalKnowledgeTitle').textContent = item ? '编辑知识' : '新增知识';
      document.getElementById('knowledgeTitle').value = item ? (item.title || '') : '';
      document.getElementById('knowledgePosition').value = item ? (item.position_code || '') : '';
      document.getElementById('knowledgeContent').value = item ? (item.content || '') : '';
      document.getElementById('knowledgeTags').value = item ? (item.tags || '') : '';
      document.getElementById('knowledgeKeywords').value = item ? (item.keywords || '') : '';
      document.getElementById('knowledgeTopic').value = item ? (item.topic || '') : '';
      document.getElementById('knowledgeSource').value = item ? (item.source || '') : '';
      document.getElementById('knowledgeDifficulty').value = item ? (item.difficulty || 1) : 1;
      window._knowledgeEditId = id;
      modalKnowledge.show();
    };
    if (id == null) { fill(null); return; }
    API.getKnowledgeItem(id).then(function (data) { fill(data.knowledge || data); }).catch(function (err) {
      if (window.Toast) Toast.error(getErrorMessage(err));
    });
  }

  function deleteKnowledge(id) {
    if (!confirm('确定删除该知识条目？历史报告中的引用快照仍会保留。')) return;
    API.deleteKnowledge(id).then(function () {
      if (window.Toast) Toast.success('知识条目已删除');
      loadKnowledge();
    }).catch(function (err) { if (window.Toast) Toast.error(getErrorMessage(err)); });
  }

  function loadUsers() {
    var msgEl = document.getElementById('userListMsg');
    if (msgEl) { msgEl.style.display = 'none'; msgEl.textContent = ''; }
    var tbody = document.getElementById('userTbody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="5" class="loading">加载中…</td></tr>';
    API.getUsers({ page: usersPage, per_page: perPage }).then(function (data) {
      var list = data.users || data.items || [];
      var total = data.total != null ? data.total : list.length;
      if (list.length === 0) { tbody.innerHTML = '<tr><td colspan="5" class="empty-hint">暂无用户</td></tr>'; }
      else {
        tbody.innerHTML = list.map(function (u) {
          var roleText = u.role === 'admin' ? '管理员' : '普通用户';
          var createdAt = u.created_at ? String(u.created_at).slice(0, 16) : '-';
          return '<tr><td>' + escapeHtml(u.username) + '</td><td>' + escapeHtml(u.display_name || '-') + '</td><td>' + roleText + '</td><td>' + escapeHtml(createdAt) + '</td><td><button type="button" class="btn btn-sm btn-outline-primary me-1 btn-edit-user" data-id="' + u.id + '">编辑</button> <button type="button" class="btn btn-sm btn-outline-danger btn-delete-user" data-id="' + u.id + '">删除</button></td></tr>';
        }).join('');
        tbody.querySelectorAll('.btn-edit-user').forEach(function (b) { b.addEventListener('click', function () { openUserModal(Number(b.dataset.id), list); }); });
        tbody.querySelectorAll('.btn-delete-user').forEach(function (b) { b.addEventListener('click', function () { deleteUser(Number(b.dataset.id)); }); });
      }
      renderPagination(document.getElementById('userPagination'), usersPage, total, perPage, function (p) { usersPage = p; loadUsers(); });
    }).catch(function (err) {
      var msg = (window.getErrorMessage ? getErrorMessage(err) : (err && err.message)) || '加载失败';
      tbody.innerHTML = '<tr><td colspan="5" class="empty-hint">' + escapeHtml(msg) + '</td></tr>';
      if (window.Toast) Toast.error(msg);
    });
  }

  function openUserModal(id, list) {
    var errEl = document.getElementById('userFormError');
    if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
    var u = id != null ? list.find(function (x) { return x.id === id; }) : null;
    document.getElementById('modalUserTitle').textContent = u ? '编辑用户' : '新增用户';
    document.getElementById('userUsername').value = u ? u.username : '';
    document.getElementById('userUsername').readOnly = !!u;
    document.getElementById('userDisplayNameInput').value = u ? (u.display_name || '') : '';
    document.getElementById('userPassword').value = '';
    document.getElementById('userPassword').required = !u;
    document.getElementById('userRole').value = u ? u.role : 'user';
    window._userEditId = id;
    modalUser.show();
  }

  function deleteUser(id) {
    if (!confirm('确定删除该用户？')) return;
    var msgEl = document.getElementById('userListMsg');
    if (msgEl) { msgEl.style.display = 'none'; msgEl.textContent = ''; }
    API.deleteUser(id).then(function () { if (window.Toast) Toast.success('已删除'); loadUsers(); }).catch(function (err) {
      var msg = getErrorMessage(err);
      if (msgEl) { msgEl.textContent = '删除失败：' + msg; msgEl.style.display = 'block'; }
      if (window.Toast) Toast.error(msg);
    });
  }

  function loadConfig() {
    var elQ = document.getElementById('configQuestionsPerSession');
    var elBase = document.getElementById('configLlmApiBase');
    var elModel = document.getElementById('configLlmModel');
    var elLlmStatus = document.getElementById('configLlmStatus');
    var elAsrStatus = document.getElementById('configAsrStatus');
    var elEmbeddingStatus = document.getElementById('configEmbeddingStatus');
    var elEmbeddingModel = document.getElementById('configEmbeddingModel');
    var errEl = document.getElementById('configLoadError');
    var msgEl = document.getElementById('configSaveMsg');
    if (!elQ) return;
    if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
    if (msgEl) { msgEl.style.display = 'none'; msgEl.textContent = ''; msgEl.classList.remove('alert-success', 'alert-danger'); }
    API.getConfig().then(function (data) {
      var c = data.config || data;
      elQ.value = (c.questions_per_session != null && c.questions_per_session !== '') ? c.questions_per_session : 5;
      if (elBase) elBase.textContent = c.llm_api_base || '-';
      if (elModel) elModel.textContent = c.llm_model || '-';
      if (elLlmStatus) elLlmStatus.textContent = c.llm_configured ? '已通过环境变量配置' : '未配置（将使用本地规则降级）';
      if (elAsrStatus) elAsrStatus.textContent = c.asr_configured ? '已通过环境变量配置' : '未配置（仍可使用文字输入）';
      if (elEmbeddingStatus) elEmbeddingStatus.textContent = c.embedding_configured ? '已通过环境变量配置' : '未配置（RAG 自动回退到 FTS5 + 规则）';
      if (elEmbeddingModel) elEmbeddingModel.textContent = c.embedding_model || '-';
    }).catch(function (err) {
      var msg = getErrorMessage(err);
      if (errEl) { errEl.textContent = '加载配置失败：' + msg; errEl.style.display = 'block'; }
      if (window.Toast) Toast.error(msg);
    });
  }

  API.getProfile().then(function (data) {
    currentUser = data.user;
    if (!currentUser) { window.location.href = '/login'; return; }
    if (currentUser.role !== 'admin') { window.location.href = '/user'; return; }
    var mod = document.getElementById('modalPosition');
    if (mod) modalPosition = new bootstrap.Modal(mod);
    mod = document.getElementById('modalQuestion');
    if (mod) modalQuestion = new bootstrap.Modal(mod);
    mod = document.getElementById('modalKnowledge');
    if (mod) modalKnowledge = new bootstrap.Modal(mod);
    mod = document.getElementById('modalUser');
    if (mod) modalUser = new bootstrap.Modal(mod);
    loadPositions().then(function () {
      route();
      window.addEventListener('hashchange', route);
    });

    document.getElementById('btnAddPosition').addEventListener('click', function () { openPositionModal(null); });
    document.getElementById('btnPositionSubmit').addEventListener('click', function () {
      var btn = document.getElementById('btnPositionSubmit');
      var errEl = document.getElementById('positionFormError');
      if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
      var code = document.getElementById('positionCode').value.trim();
      var name = document.getElementById('positionName').value.trim();
      var description = document.getElementById('positionDescription').value.trim() || null;
      var id = window._positionEditId;
      if (!code || !name) { if (window.Toast) Toast.error('请填写岗位编码和名称'); return; }
      setButtonLoading(btn, true, '提交中…');
      if (id != null) {
        API.updatePosition(id, { name: name, description: description }).then(function () {
          modalPosition.hide();
          if (window.Toast) Toast.success('已更新');
          loadPositionsList();
          loadPositions();
        }).catch(function (err) {
          var msg = getErrorMessage(err);
          if (errEl) { errEl.textContent = msg; errEl.style.display = 'block'; }
          if (window.Toast) Toast.error(msg);
        }).finally(function () { setButtonLoading(btn, false); });
      } else {
        API.createPosition({ code: code, name: name, description: description }).then(function () {
          modalPosition.hide();
          if (window.Toast) Toast.success('已新增');
          loadPositionsList();
          loadPositions();
        }).catch(function (err) {
          var msg = getErrorMessage(err);
          if (errEl) { errEl.textContent = msg; errEl.style.display = 'block'; }
          if (window.Toast) Toast.error(msg);
        }).finally(function () { setButtonLoading(btn, false); });
      }
    });

    document.getElementById('btnReloadQuestions').addEventListener('click', function () {
      var btn = document.getElementById('btnReloadQuestions');
      if (btn) setButtonLoading(btn, true, '查询中…');
      questionsPage = 1;
      loadQuestions().finally(function () { if (btn) setButtonLoading(btn, false); });
    });
    document.getElementById('btnResetQuestionsFilter').addEventListener('click', function () {
      var sel = document.getElementById('qFilterPosition');
      var kw = document.getElementById('qSearchKeyword');
      if (sel) sel.value = '';
      if (kw) kw.value = '';
      questionsPage = 1;
      loadQuestions();
    });
    document.getElementById('btnClearQuestionBank').addEventListener('click', function () {
      if (!confirm('确定停用全部题目吗？历史面试记录会保留。')) return;
      var btn = document.getElementById('btnClearQuestionBank');
      if (btn) setButtonLoading(btn, true, '清空中…');
      API.clearAllQuestions().then(function (res) {
        if (window.Toast) Toast.success(res.message || '已停用全部题目');
        questionsPage = 1;
        loadQuestions();
      }).catch(function (err) {
        if (window.Toast) Toast.error(window.getErrorMessage ? getErrorMessage(err) : (err && err.message) || '清空失败');
      }).finally(function () { if (btn) setButtonLoading(btn, false); });
    });
    var qSearchKeywordEl = document.getElementById('qSearchKeyword');
    if (qSearchKeywordEl) {
      qSearchKeywordEl.addEventListener('keydown', function (e) { if (e.key === 'Enter') { questionsPage = 1; loadQuestions(); } });
    }
    document.getElementById('btnAddQuestion').addEventListener('click', function () { openQuestionModal(null); });
    document.getElementById('btnQuestionSubmit').addEventListener('click', function () {
      var btn = document.getElementById('btnQuestionSubmit');
      var errEl = document.getElementById('questionFormError');
      if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
      var content = document.getElementById('questionContent').value.trim();
      var question_type = document.getElementById('questionType').value;
      var position_id = document.getElementById('questionPosition').value ? parseInt(document.getElementById('questionPosition').value, 10) : null;
      if (!content || !position_id) { if (window.Toast) Toast.error('请填写题目内容并选择岗位'); return; }
      var reference_answer = document.getElementById('questionRefAnswer').value.trim() || null;
      var id = window._questionEditId;
      var payload = {
        content: content,
        question_type: question_type,
        position_id: position_id,
        reference_answer: reference_answer,
        difficulty: parseInt(document.getElementById('questionDifficulty').value, 10) || 1,
        topic: document.getElementById('questionTopic').value.trim(),
        tags: document.getElementById('questionTags').value.trim(),
        source: document.getElementById('questionSource').value.trim() || 'admin',
        review_status: document.getElementById('questionReviewStatus').value,
        reviewer: document.getElementById('questionReviewer').value.trim(),
        is_core: document.getElementById('questionIsCore').checked
      };
      setButtonLoading(btn, true, '提交中…');
      (id != null ? API.updateQuestion(id, payload) : API.createQuestion(payload)).then(function () {
        modalQuestion.hide();
        if (window.Toast) Toast.success(id != null ? '已更新' : '已新增');
        loadQuestions();
      }).catch(function (err) {
        var msg = getErrorMessage(err);
        if (errEl) { errEl.textContent = msg; errEl.style.display = 'block'; }
        if (window.Toast) Toast.error(msg);
      }).finally(function () { setButtonLoading(btn, false); });
    });

    document.getElementById('btnReloadKnowledge').addEventListener('click', function () {
      knowledgePage = 1;
      loadKnowledge();
    });
    document.getElementById('kSearchKeyword').addEventListener('keydown', function (event) {
      if (event.key === 'Enter') { knowledgePage = 1; loadKnowledge(); }
    });
    document.getElementById('btnAddKnowledge').addEventListener('click', function () { openKnowledgeModal(null); });
    document.getElementById('btnKnowledgeSubmit').addEventListener('click', function () {
      var button = document.getElementById('btnKnowledgeSubmit');
      var error = document.getElementById('knowledgeFormError');
      if (error) { error.style.display = 'none'; error.textContent = ''; }
      var payload = {
        title: document.getElementById('knowledgeTitle').value.trim(),
        position_code: document.getElementById('knowledgePosition').value,
        content: document.getElementById('knowledgeContent').value.trim(),
        tags: document.getElementById('knowledgeTags').value.trim(),
        keywords: document.getElementById('knowledgeKeywords').value.trim(),
        topic: document.getElementById('knowledgeTopic').value.trim(),
        source: document.getElementById('knowledgeSource').value.trim() || 'admin',
        difficulty: parseInt(document.getElementById('knowledgeDifficulty').value, 10) || 1
      };
      if (!payload.title || !payload.position_code || !payload.content) {
        if (window.Toast) Toast.error('请填写标题、岗位和知识内容');
        return;
      }
      var id = window._knowledgeEditId;
      setButtonLoading(button, true, '提交中…');
      (id != null ? API.updateKnowledge(id, payload) : API.createKnowledge(payload)).then(function () {
        modalKnowledge.hide();
        if (window.Toast) Toast.success(id != null ? '知识已更新，请刷新向量' : '知识已新增，请刷新向量');
        loadKnowledge();
      }).catch(function (err) {
        var message = getErrorMessage(err);
        if (error) { error.textContent = message; error.style.display = 'block'; }
        if (window.Toast) Toast.error(message);
      }).finally(function () { setButtonLoading(button, false); });
    });
    document.getElementById('btnRefreshEmbeddings').addEventListener('click', function () {
      var button = document.getElementById('btnRefreshEmbeddings');
      var positionCode = document.getElementById('kFilterPosition').value;
      setButtonLoading(button, true, '更新中…');
      API.refreshKnowledgeEmbeddings({ position_code: positionCode || null }).then(function (data) {
        var result = data.result || {};
        if (window.Toast) Toast.success('向量更新 ' + (result.updated || 0) + ' 条，跳过 ' + (result.skipped || 0) + ' 条');
        loadKnowledge();
      }).catch(function (err) {
        if (window.Toast) Toast.error(getErrorMessage(err));
      }).finally(function () { setButtonLoading(button, false); });
    });
    document.getElementById('btnImportKnowledge').addEventListener('click', function () {
      var button = document.getElementById('btnImportKnowledge');
      var fileInput = document.getElementById('knowledgeImportFile');
      var positionCode = document.getElementById('kFilterPosition').value;
      var file = fileInput.files && fileInput.files[0];
      if (!positionCode) { if (window.Toast) Toast.error('请先在左侧筛选框选择导入岗位'); return; }
      if (!file) { if (window.Toast) Toast.error('请选择 Markdown、TXT 或 PDF 文件'); return; }
      setButtonLoading(button, true, '导入中…');
      API.importKnowledgeDocument(file, positionCode, 'admin_import').then(function (data) {
        var result = data.result || {};
        fileInput.value = '';
        if (window.Toast) Toast.success('导入 ' + (result.created || 0) + ' 条，跳过重复 ' + (result.skipped_duplicates || 0) + ' 条；请更新向量');
        knowledgePage = 1;
        loadKnowledge();
      }).catch(function (err) {
        if (window.Toast) Toast.error(getErrorMessage(err));
      }).finally(function () { setButtonLoading(button, false); });
    });

    document.getElementById('btnAddUser').addEventListener('click', function () { openUserModal(null, []); });
    document.getElementById('btnUserSubmit').addEventListener('click', function () {
      var btn = document.getElementById('btnUserSubmit');
      var errEl = document.getElementById('userFormError');
      if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
      var username = document.getElementById('userUsername').value.trim();
      var display_name = document.getElementById('userDisplayNameInput').value.trim() || null;
      var password = document.getElementById('userPassword').value;
      var role = document.getElementById('userRole').value;
      var id = window._userEditId;
      if (id == null && (!username || !password)) { if (window.Toast) Toast.error('请填写用户名和密码'); return; }
      var origText = btn.textContent;
      btn.disabled = true;
      btn.textContent = '提交中…';
      var done = function () { btn.disabled = false; btn.textContent = origText; };
      if (id != null) {
        var body = { display_name: display_name, role: role };
        if (password) body.password = password;
        API.updateUser(id, body).then(function () { modalUser.hide(); if (window.Toast) Toast.success('已更新'); loadUsers(); }).catch(function (err) {
          var msg = getErrorMessage(err);
          if (errEl) { errEl.textContent = msg; errEl.style.display = 'block'; }
          if (window.Toast) Toast.error(msg);
        }).finally(done);
      } else {
        API.createUser({ username: username, display_name: display_name, password: password, role: role }).then(function () { modalUser.hide(); if (window.Toast) Toast.success('已新增'); loadUsers(); }).catch(function (err) {
          var msg = getErrorMessage(err);
          if (errEl) { errEl.textContent = msg; errEl.style.display = 'block'; }
          if (window.Toast) Toast.error(msg);
        }).finally(done);
      }
    });

    document.getElementById('btnSaveConfig').addEventListener('click', function () {
      var btn = document.getElementById('btnSaveConfig');
      var msgEl = document.getElementById('configSaveMsg');
      if (msgEl) { msgEl.style.display = 'none'; msgEl.textContent = ''; msgEl.classList.remove('alert-success', 'alert-danger'); }
      setButtonLoading(btn, true, '保存中…');
      API.updateConfig({
        questions_per_session: parseInt(document.getElementById('configQuestionsPerSession').value, 10) || 5
      }).then(function () {
        if (msgEl) { msgEl.textContent = '配置已保存'; msgEl.classList.add('alert-success'); msgEl.classList.remove('alert-danger'); msgEl.style.display = 'block'; }
        if (window.Toast) Toast.success('配置已保存');
      }).catch(function (err) {
        var msg = getErrorMessage(err);
        if (msgEl) { msgEl.textContent = '保存失败：' + msg; msgEl.classList.add('alert-danger'); msgEl.classList.remove('alert-success'); msgEl.style.display = 'block'; }
        if (window.Toast) Toast.error(msg);
      }).finally(function () { setButtonLoading(btn, false); });
    });

    var btnLogout = document.getElementById('btnAdminLogout');
    if (btnLogout) btnLogout.addEventListener('click', function () {
      var btn = btnLogout;
      btn.disabled = true;
      API.logout().then(function () { window.location.href = '/login'; }).catch(function () { window.location.href = '/login'; }).finally(function () { btn.disabled = false; });
    });
  }).catch(function () { window.location.href = '/login'; });
})();
