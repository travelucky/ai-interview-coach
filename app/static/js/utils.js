/**
 * 通用工具：Toast、escapeHtml、formatReportValue、renderPagination
 */
window.Toast = {
  show: function (message, type) {
    var wrap = document.getElementById('toastWrap');
    if (!wrap) return;
    var el = document.createElement('div');
    el.className = 'toast ' + (type || 'info');
    el.textContent = message || '';
    wrap.appendChild(el);
    setTimeout(function () { el.remove(); }, 3000);
  },
  success: function (m) { this.show(m, 'success'); },
  error: function (m) { this.show(m && m.toString() ? m.toString() : '操作失败，请重试', 'error'); },
  info: function (m) { this.show(m, 'info'); }
};

/** 从接口错误中取出可读文案，供 Toast 或内联提示使用 */
window.getErrorMessage = function (err) {
  if (!err) return '操作失败，请重试';
  var msg = err.message || err.msg || (typeof err === 'string' ? err : '');
  return (msg && msg.trim()) ? msg : '操作失败，请重试';
};

function escapeHtml(s) {
  if (s == null) return '';
  var div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

function formatReportValue(v) {
  if (v == null) return '';
  if (typeof v === 'string') return escapeHtml(v);
  if (Array.isArray(v)) return '<ul class="report-list mb-0">' + v.map(function (item) { return '<li>' + escapeHtml(typeof item === 'string' ? item : JSON.stringify(item)) + '</li>'; }).join('') + '</ul>';
  if (typeof v === 'object') return '<pre class="mb-0 small">' + escapeHtml(JSON.stringify(v, null, 2)) + '</pre>';
  return String(v);
}

/** 将接口返回的报告对象渲染为可读 HTML，不直接展示 JSON（综合得分由调用方单独展示） */
window.renderReportHtml = function (report) {
  if (!report) return '';
  var html = '';
  var sourceLabels = { rule: '本地规则评分', hybrid: '规则 + AI 混合评分', llm: 'AI 评分' };
  var sourceLabel = sourceLabels[report.scoring_source] || report.scoring_source || '未知';
  var completion = Number(report.completion_ratio);
  html += '<div class="report-meta"><span>评分来源：' + escapeHtml(sourceLabel) + '</span>';
  if (report.session_mode === 'training') html += '<span>类型：专项训练</span>';
  if (!isNaN(completion)) html += '<span>完成度：' + Math.round(completion * 100) + '%</span>';
  if (report.scoring_version) html += '<span>评分版本：' + escapeHtml(String(report.scoring_version)) + '</span>';
  if (report.created_at) html += '<span>生成时间：' + escapeHtml(String(report.created_at).replace('T', ' ').slice(0, 19)) + '</span>';
  html += '</div>';
  var contentLabels = { technical_correctness: '技术正确性', knowledge_depth: '知识深度', logic: '逻辑结构', project_practice: '项目实践', job_fit: '岗位匹配度', expression_performance: '表达表现' };
  var content = report.content_analysis;
  if (content && typeof content === 'object') {
    html += '<div class="report-section"><h4 class="report-section-title">内容分析</h4><div class="report-dims">';
    for (var k in contentLabels) {
      if (contentLabels.hasOwnProperty(k) && content[k] !== undefined && content[k] !== null) {
        var val = content[k];
        var num = typeof val === 'number' ? val : parseInt(val, 10);
        var pct = isNaN(num) ? 0 : Math.max(0, Math.min(100, num));
        html += '<div class="report-dim-row"><span class="report-dim-name">' + escapeHtml(contentLabels[k]) + '</span><div class="report-dim-bar-wrap"><div class="report-dim-bar" style="width:' + pct + '%"></div></div><span class="report-dim-num">' + (isNaN(num) ? escapeHtml(String(val)) : num + ' / 100') + '</span></div>';
      }
    }
    html += '</div></div>';
  }

  var exprLabels = { pace: '语速', clarity: '清晰度', confidence: '自信度' };
  var expr = report.expression_analysis;
  if (expr && typeof expr === 'object') {
    html += '<div class="report-section"><h4 class="report-section-title">表达分析</h4><div class="report-dims report-dims-text">';
    if (expr.status === 'not_measured') {
      html += '<div class="report-notice">本次未采集可靠的声音特征，以下项目不计入得分。</div>';
    } else if (expr.status === 'measured') {
      html += '<div class="report-notice">以下数据由录音时长和转写文本计算，仅用于表达训练，不计入技术得分。</div>';
    }
    for (var ek in exprLabels) {
      if (exprLabels.hasOwnProperty(ek) && expr[ek] !== undefined && expr[ek] !== null)
        html += '<div class="report-dim-row"><span class="report-dim-name">' + escapeHtml(exprLabels[ek]) + '</span><span class="report-dim-text">' + escapeHtml(String(expr[ek])) + '</span></div>';
    }
    if (expr.status === 'measured') {
      html += '<div class="report-type-scores">';
      html += '<span><b>语音回答</b> ' + escapeHtml(String(expr.voice_answer_count || 0)) + ' 次</span>';
      html += '<span><b>录音时长</b> ' + escapeHtml(String(expr.total_duration_seconds || 0)) + ' 秒</span>';
      html += '<span><b>有效字数</b> ' + escapeHtml(String(expr.character_count || 0)) + '</span>';
      html += '<span><b>填充词</b> ' + escapeHtml(String(expr.filler_word_count || 0)) + ' 次</span>';
      html += '<span><b>重复表达</b> ' + escapeHtml(String(expr.repetition_count || 0)) + ' 次</span>';
      html += '</div>';
      var acoustic = expr.acoustic_metrics;
      if (acoustic && acoustic.status === 'measured') {
        html += '<div class="report-notice">声学统计来自 WAV 信号，可重复计算；它们不等同于情绪、人格或自信度。</div>';
        html += '<div class="report-type-scores">';
        html += '<span><b>有声时长</b> ' + escapeHtml(String(acoustic.voiced_duration_seconds || 0)) + ' 秒</span>';
        html += '<span><b>静音占比</b> ' + escapeHtml(String(Math.round((acoustic.silence_ratio || 0) * 100))) + '%</span>';
        html += '<span><b>长停顿</b> ' + escapeHtml(String(acoustic.pause_count || 0)) + ' 次</span>';
        html += '<span><b>平均音量</b> ' + escapeHtml(String(acoustic.average_rms_dbfs)) + ' dBFS</span>';
        html += '<span><b>音量波动</b> ' + escapeHtml(String(acoustic.average_volume_variation_db)) + ' dB</span>';
        html += '<span><b>削波占比</b> ' + escapeHtml(String(Math.round((acoustic.clipping_ratio || 0) * 10000) / 100)) + '%</span>';
        html += '</div>';
      }
      if (expr.model_inference && expr.model_inference.status === 'not_enabled') {
        html += '<div class="report-notice">模型推断未启用：' + escapeHtml(String(expr.model_inference.reason || '尚无经样本校准的模型')) + '，因此不生成伪精确的「自信度得分」。</div>';
      }
    }
    html += '</div></div>';
    var typeScores = content && content.question_type_scores;
    var typeLabels = { technical: '技术题', project: '项目题', scenario: '场景题', behavioral: '行为题' };
    if (typeScores && typeof typeScores === 'object' && Object.keys(typeScores).length) {
      html += '<div class="report-section"><h4 class="report-section-title">题型得分</h4><div class="report-type-scores">';
      Object.keys(typeLabels).forEach(function (type) {
        if (typeScores[type] !== undefined && typeScores[type] !== null) {
          html += '<span><b>' + escapeHtml(typeLabels[type]) + '</b> ' + escapeHtml(String(typeScores[type])) + ' / 100</span>';
        }
      });
      html += '</div></div>';
    }
  }

  var questionScores = Array.isArray(report.question_scores) ? report.question_scores : [];
  if (questionScores.length) {
    html += '<div class="report-section"><h4 class="report-section-title">逐题评分</h4><div class="question-score-list">';
    questionScores.forEach(function (item, index) {
      var score = Number(item.final_score);
      var covered = Array.isArray(item.covered_points) ? item.covered_points : [];
      var missing = Array.isArray(item.missing_points) ? item.missing_points : [];
      var evidence = Array.isArray(item.evidence) ? item.evidence : [];
      var knowledgeReferences = Array.isArray(item.knowledge_references) ? item.knowledge_references : [];
      html += '<article class="question-score-card">';
      html += '<div class="question-score-head"><strong>第 ' + (index + 1) + ' 题</strong><span>' + (isNaN(score) ? '-' : score) + ' / 100</span></div>';
      if (item.question_content) html += '<p class="question-score-question">' + escapeHtml(String(item.question_content)) + '</p>';
      if (covered.length) html += '<div class="question-score-line"><b>已覆盖：</b>' + escapeHtml(covered.join('、')) + '</div>';
      if (missing.length) html += '<div class="question-score-line question-score-missing"><b>待补充：</b>' + escapeHtml(missing.join('、')) + '</div>';
      if (evidence.length) html += '<div class="question-score-line"><b>评分依据：</b>' + escapeHtml(evidence.join('；')) + '</div>';
      var dimensions = item.dimension_scores && typeof item.dimension_scores === 'object' ? item.dimension_scores : {};
      var dimensionLabels = { technical_correctness: '技术正确性', knowledge_depth: '知识深度', logic_structure: '逻辑结构', project_practice: '项目实践', job_fit: '岗位匹配', expression_performance: '表达表现' };
      if (Object.keys(dimensions).length) {
        html += '<div class="question-score-line"><b>独立 Rubric：</b><ul class="report-list mb-0">';
        Object.keys(dimensionLabels).forEach(function (key) {
          var dim = dimensions[key];
          if (!dim) return;
          var state = dim.status === 'evaluated' ? (String(dim.score) + ' / 100') : (dim.status === 'not_applicable' ? '不适用' : '待评估');
          var detail = [dim.rationale, dim.confidence ? '可信度：' + dim.confidence : ''].filter(Boolean).join('；');
          html += '<li><b>' + escapeHtml(dimensionLabels[key]) + '：</b>' + escapeHtml(state) + (detail ? '（' + escapeHtml(detail) + '）' : '') + '</li>';
        });
        html += '</ul></div>';
      }
      if (knowledgeReferences.length) {
        html += '<div class="question-score-line"><b>知识引用：</b><ul class="report-list mb-0">';
        knowledgeReferences.forEach(function (ref) {
          var retrieval = ref.retrieval || {};
          var methodLabels = { hybrid: '混合检索', 'fts5+rule': 'FTS5 + 规则', rule: '规则检索' };
          var detail = [
            ref.source ? '来源：' + ref.source : '',
            ref.score != null ? '相关度：' + ref.score : '',
            retrieval.method ? '方式：' + (methodLabels[retrieval.method] || retrieval.method) : ''
          ].filter(Boolean).join('，');
          html += '<li>' + escapeHtml(String(ref.title || '未命名知识')) + (detail ? '（' + escapeHtml(detail) + '）' : '') + '</li>';
        });
        html += '</ul></div>';
      }
      if (item.suggestion) html += '<div class="question-score-line"><b>建议：</b>' + escapeHtml(String(item.suggestion)) + '</div>';
      html += '</article>';
    });
    html += '</div></div>';
  }

  var retrievalSummary = Array.isArray(report.retrieval_summary) ? report.retrieval_summary : [];
  if (retrievalSummary.length) {
    var useCaseLabels = { followup: '动态追问', scoring: '逐题评分', training: '训练建议', recommendation: '训练建议' };
    var traceMethodLabels = { hybrid: '混合检索', 'fts5+rule': 'FTS5 + 规则', rule: '规则检索', none: '未命中' };
    html += '<div class="report-section"><h4 class="report-section-title">RAG 检索留痕</h4>';
    html += '<div class="report-notice">这里展示各环节的检索汇总；完整事件保留用于后台审计，逐题引用请见上方知识引用。</div>';
    html += '<ul class="report-list mb-0">';
    retrievalSummary.forEach(function (summary) {
      var label = useCaseLabels[summary.use_case] || summary.use_case || '未知场景';
      var methods = (summary.methods || []).map(function (method) {
        return traceMethodLabels[method] || method;
      });
      var detail = '检索 ' + Number(summary.event_count || 0) + ' 次，命中 ' + Number(summary.hit_count || 0) + ' 次';
      if (Number(summary.rejected_count || 0) > 0) detail += '，相关度不足 ' + Number(summary.rejected_count) + ' 次';
      detail += '，引用 ' + Number(summary.unique_knowledge_count || 0) + ' 条知识';
      if (methods.length) detail += '；方式 ' + methods.join(' / ');
      html += '<li><b>' + escapeHtml(String(label)) + '</b>：' + escapeHtml(detail) + '</li>';
    });
    html += '</ul></div>';
  }

  if (report.highlights) {
    var h = report.highlights;
    var hText = Array.isArray(h) ? h.join('；') : (typeof h === 'string' ? h : '');
    if (hText) html += '<div class="report-section"><h4 class="report-section-title">亮点</h4><div class="report-section-body">' + escapeHtml(hText) + '</div></div>';
  }
  if (report.improvements) {
    var imp = report.improvements;
    var impText = Array.isArray(imp) ? imp.join('；') : (typeof imp === 'string' ? imp : '');
    if (impText) html += '<div class="report-section"><h4 class="report-section-title">待改进</h4><div class="report-section-body">' + escapeHtml(impText) + '</div></div>';
  }
  var trainingTasks = Array.isArray(report.training_tasks) ? report.training_tasks : [];
  if (trainingTasks.length) {
    html += '<div class="report-section"><h4 class="report-section-title">个性化训练计划</h4>';
    html += '<div class="training-task-list">';
    trainingTasks.forEach(function (task, index) {
      var knowledge = task.knowledge && typeof task.knowledge === 'object' ? task.knowledge : null;
      var practice = task.practice_question && typeof task.practice_question === 'object' ? task.practice_question : null;
      var framework = Array.isArray(task.answer_framework) ? task.answer_framework : [];
      html += '<article class="training-task-card">';
      html += '<div class="training-task-head"><span class="training-task-index">任务 ' + (index + 1) + '</span>';
      var taskStatusLabels = { todo: '待训练', in_progress: '训练中', completed: '已完成' };
      html += '<span class="training-task-category">' + escapeHtml(String(task.category_label || '专项训练')) + ' · ' + escapeHtml(taskStatusLabels[task.status] || task.status || '待训练') + '</span></div>';
      html += '<h5>' + escapeHtml(String(task.title || '专项训练')) + '</h5>';
      if (task.objective) html += '<p class="training-task-objective"><b>目标：</b>' + escapeHtml(String(task.objective)) + '</p>';
      if (task.reason) html += '<p class="training-task-reason"><b>依据：</b>' + escapeHtml(String(task.reason)) + '</p>';
      if (knowledge) {
        html += '<div class="training-task-material"><b>推荐材料：</b>' + escapeHtml(String(knowledge.title || '岗位知识材料'));
        if (knowledge.summary) html += '<p>' + escapeHtml(String(knowledge.summary)) + '</p>';
        html += '</div>';
      }
      if (practice && practice.content) {
        html += '<div class="training-task-practice"><b>练习题：</b>' + escapeHtml(String(practice.content)) + '</div>';
      }
      if (framework.length) {
        html += '<div class="training-task-framework"><b>建议回答结构：</b><ol>';
        framework.forEach(function (step) { html += '<li>' + escapeHtml(String(step)) + '</li>'; });
        html += '</ol></div>';
      }
      if (task.suggested_days) html += '<div class="training-task-due">建议在 ' + escapeHtml(String(task.suggested_days)) + ' 天内完成并复测</div>';
      if (task.comparison) {
        if (task.comparison.comparable) {
          var delta = Number(task.comparison.score_delta || 0);
          html += '<div class="report-notice"><b>复测参考：</b>' + escapeHtml(String(task.comparison.source_score)) + ' → ' + escapeHtml(String(task.comparison.training_score)) + '（' + (delta >= 0 ? '+' : '') + escapeHtml(String(delta)) + '）。来源是完整面试，复测是三题专项训练，不能视为严格同卷对比。</div>';
        } else {
          html += '<div class="report-notice">复测不可直接比较：' + escapeHtml(String(task.comparison.reason || '评分口径不同')) + '</div>';
        }
      }
      if (report.session_id && task.id && (!task.status || task.status === 'todo')) {
        html += '<button type="button" class="btn btn-sm btn-primary btn-start-training" data-source-session="' + Number(report.session_id) + '" data-task-id="' + encodeURIComponent(String(task.id)) + '">开始专项训练</button>';
      } else if (task.status === 'in_progress') {
        html += '<div class="training-task-due">该任务已有进行中的专项面试，请从未完成面试继续。</div>';
      }
      html += '</article>';
    });
    html += '</div></div>';
  }
  if (report.training_comparison) {
    var comparison = report.training_comparison;
    html += '<div class="report-section"><h4 class="report-section-title">专项复测对比</h4>';
    if (comparison.comparable) {
      var scoreDelta = Number(comparison.score_delta || 0);
      html += '<div class="report-score-block"><span class="report-score-label">来源面试 → 本次专项复测（参考）</span><span class="report-score-value">' + escapeHtml(String(comparison.source_score)) + ' → ' + escapeHtml(String(comparison.training_score)) + '</span><span class="report-score-unit">（' + (scoreDelta >= 0 ? '+' : '') + escapeHtml(String(scoreDelta)) + '）</span></div><div class="report-notice">来源是完整面试，本次是三题专项训练；仅在同评分版本下展示，不代表严格同卷对比。</div>';
    } else {
      html += '<div class="report-notice">' + escapeHtml(String(comparison.reason || '评分版本或岗位不一致，不能直接比较')) + '</div>';
    }
    html += '</div>';
  }
  if (report.suggestions) {
    var s = report.suggestions;
    var items = [];
    if (Array.isArray(s)) {
      items = s.map(function (x) { return (typeof x === 'string' ? x : (x && x.text ? x.text : String(x))).trim(); }).filter(Boolean);
    } else if (typeof s === 'string' && s.trim()) {
      items = s.split(/\n+/).map(function (x) { return x.trim(); }).filter(Boolean);
      if (items.length <= 1 && items[0] && items[0].length > 80) {
        items = items[0].split(/(?<=[。；;])\s*/).map(function (x) { return x.trim(); }).filter(Boolean);
      }
    }
    if (items.length) {
      html += '<div class="report-section"><h4 class="report-section-title">改进建议</h4><div class="report-section-body report-suggestions"><ul class="report-list report-list-suggestions">';
      items.forEach(function (item) {
        var text = typeof item === 'string' ? item : (item && item.text ? item.text : String(item));
        if (text) html += '<li>' + escapeHtml(text) + '</li>';
      });
      html += '</ul></div></div>';
    }
  }
  return html || '<p class="text-secondary">暂无详细报告</p>';
};

function renderPagination(el, page, total, perPage, onPage) {
  if (!el) return;
  el.innerHTML = '';
  if (!total || total <= 0) return;
  var totalPages = Math.max(1, Math.ceil(total / perPage));
  if (totalPages <= 1) return;
  page = Math.max(1, Math.min(page, totalPages));
  var win = 2;
  var pages = [];
  if (totalPages <= 7) {
    for (var i = 1; i <= totalPages; i++) pages.push(i);
  } else {
    pages.push(1);
    var lo = Math.max(2, page - win);
    var hi = Math.min(totalPages - 1, page + win);
    if (lo > 2) pages.push(-1);
    for (var j = lo; j <= hi; j++) if (j >= 1 && j <= totalPages) pages.push(j);
    if (hi < totalPages - 1) pages.push(-2);
    if (totalPages > 1) pages.push(totalPages);
  }
  function addPageItem(p) {
    var li = document.createElement('li');
    li.className = 'page-item' + (p === page ? ' active' : '');
    var a = document.createElement('a');
    a.className = 'page-link';
    a.href = '#';
    a.textContent = p === -1 || p === -2 ? '…' : p;
    if (p === -1 || p === -2) { li.classList.add('disabled'); a.addEventListener('click', function (e) { e.preventDefault(); }); }
    else a.addEventListener('click', function (ev) { ev.preventDefault(); onPage(p); });
    li.appendChild(a);
    el.appendChild(li);
  }
  for (var k = 0; k < pages.length; k++) addPageItem(pages[k]);
}
