/**
 * 用户端页 /user：鉴权、Hash 路由、数据大屏/模拟面试/历史/个人中心
 */
(function () {
  var TARGET_SAMPLE_RATE = 16000;
  var ACTIVE_SESSION_STORAGE_KEY = 'aiInterview.activeSessionId';

  /** 将浏览器录制的音频 Blob 转为 16kHz 单声道 WAV，供后端讯飞服务识别 */
  function blobToWav16k(blob) {
    return new Promise(function (resolve, reject) {
      var ctx = new (window.AudioContext || window.webkitAudioContext)();
      var fr = new FileReader();
      fr.onload = function () {
        ctx.decodeAudioData(fr.result).then(function (buffer) {
          if (!buffer || !buffer.length) { reject(new Error('录音为空，请重新录制')); return; }
          var ch = buffer.numberOfChannels;
          var sr = buffer.sampleRate;
          var left = buffer.getChannelData(0);
          var mono = ch > 1 ? new Float32Array(buffer.length) : left;
          if (ch > 1) {
            var right = buffer.getChannelData(1);
            for (var i = 0; i < buffer.length; i++) mono[i] = (left[i] + right[i]) / 2;
          }
          var outSr = TARGET_SAMPLE_RATE;
          var outLen = Math.max(1, Math.floor(mono.length * outSr / sr));
          var out = new Int16Array(outLen);
          for (var j = 0; j < outLen; j++) {
            var i = outLen <= 1 ? 0 : (j * (mono.length - 1)) / (outLen - 1);
            var idx = Math.floor(i);
            var frac = i - idx;
            var s = idx < mono.length - 1 ? mono[idx] * (1 - frac) + mono[idx + 1] * frac : mono[idx];
            s = s < -1 ? -1 : s > 1 ? 1 : s;
            out[j] = s < 0 ? s * 0x8000 : s * 0x7FFF;
          }
          var wavLen = 44 + outLen * 2;
          var buf = new ArrayBuffer(wavLen);
          var view = new DataView(buf);
          function writeStr(offset, str) { for (var k = 0; k < str.length; k++) view.setUint8(offset + k, str.charCodeAt(k)); }
          writeStr(0, 'RIFF');
          view.setUint32(4, wavLen - 8, true);
          writeStr(8, 'WAVE');
          writeStr(12, 'fmt ');
          view.setUint32(16, 16, true);
          view.setUint16(20, 1, true);
          view.setUint16(22, 1, true);
          view.setUint32(24, outSr, true);
          view.setUint32(28, outSr * 2, true);
          view.setUint16(32, 2, true);
          view.setUint16(34, 16, true);
          writeStr(36, 'data');
          view.setUint32(40, outLen * 2, true);
          for (var n = 0; n < outLen; n++) view.setInt16(44 + n * 2, out[n], true);
          resolve(new Blob([buf], { type: 'audio/wav' }));
        }).catch(function () { reject(new Error('无法解析录音，请使用文字输入')); });
      };
      fr.onerror = function () { reject(new Error('读取录音失败')); };
      fr.readAsArrayBuffer(blob);
    });
  }

  var currentUser = null;
  var positions = [];
  var userChartTrend = null;
  var userChartByPosition = null;
  var userChartScoreDist = null;
  var userChartDimensions = null;
  var userChartQuestionTypes = null;
  var currentSessionId = null;
  var currentSession = null;
  var mediaRecorder = null;
  var recordingStartedAt = null;
  var recordingTimer = null;
  var pendingVoiceDraft = null;
  var historyPage = 1;

  function resetVoiceButton() {
    var btn = document.getElementById('btnVoice');
    if (!btn) return;
    btn.classList.remove('recording', 'loading');
    btn.disabled = false;
    btn.innerHTML = '<span>🎤</span> 语音';
  }

  function clearVoiceDraft(clearText) {
    if (pendingVoiceDraft && pendingVoiceDraft.playbackUrl) {
      URL.revokeObjectURL(pendingVoiceDraft.playbackUrl);
    }
    pendingVoiceDraft = null;
    var draft = document.getElementById('voiceDraft');
    var playback = document.getElementById('voicePlayback');
    var status = document.getElementById('voiceDraftStatus');
    if (draft) draft.classList.add('hide');
    if (playback) { playback.pause(); playback.removeAttribute('src'); playback.load(); }
    if (status) status.textContent = '';
    if (clearText) {
      var replyText = document.getElementById('replyText');
      if (replyText) replyText.value = '';
    }
  }

  function stopRecordingTimer() {
    if (recordingTimer) clearInterval(recordingTimer);
    recordingTimer = null;
  }

  function rememberActiveSession(sessionId) {
    try {
      if (sessionId) window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, String(sessionId));
      else window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
    } catch (error) {}
  }

  function getRememberedSessionId() {
    try {
      var value = parseInt(window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY), 10);
      return value > 0 ? value : null;
    } catch (error) {
      return null;
    }
  }

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

  /** 语音朗读题目（使用浏览器 TTS），仅对实际题目内容播报；头像用 img 下闭嘴/半张/张嘴 切换 */
  var interviewerSpeakTimer = null;
  function speakQuestion(text) {
    var t = (text || '').trim();
    if (!t) return;
    var skip = /^(暂无|本场题目已全部作答完毕|可结束面试)/.test(t) || t.indexOf('可点击结束面试') !== -1;
    if (skip) return;
    if (!window.speechSynthesis) return;
    var avatar = document.getElementById('interviewerAvatar');
    var faceImg = document.getElementById('interviewerFace');
    var statusEl = document.getElementById('interviewerStatus');
    function setSpeaking(on) {
      if (avatar) avatar.classList.toggle('is-speaking', !!on);
      if (statusEl) statusEl.textContent = on ? '正在读题…' : '待命';
      if (faceImg && avatar) {
        if (interviewerSpeakTimer) { clearInterval(interviewerSpeakTimer); interviewerSpeakTimer = null; }
        if (on) {
          var imgSpeaking = avatar.getAttribute('data-img-speaking') || '';
          var imgHalf = avatar.getAttribute('data-img-half') || imgSpeaking;
          if (imgSpeaking) faceImg.src = imgSpeaking;
          var useHalf = true;
          interviewerSpeakTimer = setInterval(function () {
            useHalf = !useHalf;
            faceImg.src = useHalf ? imgHalf : imgSpeaking;
          }, 380);
        } else {
          var imgIdle = avatar.getAttribute('data-img-idle') || '';
          if (imgIdle) faceImg.src = imgIdle;
        }
      }
    }
    window.speechSynthesis.cancel();
    var u = new SpeechSynthesisUtterance(t);
    u.lang = 'zh-CN';
    u.rate = 0.95;
    u.onstart = function () { setSpeaking(true); };
    u.onend = function () { setSpeaking(false); };
    u.onerror = function () { setSpeaking(false); };
    window.speechSynthesis.speak(u);
  }

  function scrollDialogueToBottom() {
    var wrap = document.querySelector('.dialogue-list-wrap');
    if (wrap) wrap.scrollTop = wrap.scrollHeight;
  }

  function setView(sectionId) {
    document.querySelectorAll('.view-section').forEach(function (s) { s.classList.remove('active'); });
    var el = document.getElementById(sectionId);
    if (el) el.classList.add('active');
    document.querySelectorAll('.user-nav-link').forEach(function (a) {
      a.classList.toggle('active', a.getAttribute('data-view') === sectionId);
    });
  }

  function route() {
    var hash = (location.hash || '#dashboard').slice(1);
    var map = { dashboard: 'userDashboard', interview: 'userInterview', history: 'userHistory', profile: 'userProfile' };
    var view = map[hash] || 'userDashboard';
    setView(view);
    if (hash === 'dashboard') loadUserDashboard();
    else if (hash === 'interview') renderInterviewStart();
    else if (hash === 'history') loadHistory();
    else if (hash === 'profile') loadProfile();
  }

  function loadPositions() {
    var wrap = document.getElementById('interviewStart');
    var btn = document.getElementById('btnStartInterview');
    if (wrap) wrap.classList.add('positions-loading');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner-inline"></span>加载岗位中…'; }
    return API.getPositions().then(function (data) {
      positions = data.positions || data.items || [];
      var sel = document.getElementById('interviewPosition');
      if (!sel) return;
      sel.innerHTML = '<option value="">请选择岗位</option>';
      positions.forEach(function (p) { var o = document.createElement('option'); o.value = p.code; o.textContent = p.name; sel.appendChild(o); });
    }).catch(function (err) { if (window.Toast) Toast.error(window.getErrorMessage ? getErrorMessage(err) : (err && err.message) || '岗位加载失败'); }).finally(function () {
      if (wrap) wrap.classList.remove('positions-loading');
      if (btn) { btn.disabled = false; btn.textContent = '开始面试'; }
    });
  }

  function loadInterviewMode() {
    var notice = document.getElementById('interviewModeNotice');
    if (!notice) return Promise.resolve();
    return API.getHealth().then(function (data) {
      var llmConfigured = !!(data.services && data.services.llm && data.services.llm.configured);
      notice.classList.toggle('is-ai', llmConfigured);
      notice.textContent = llmConfigured
        ? '当前模式：AI 增强追问与逐题评分；外部服务失败时自动切换为本地规则。'
        : '当前模式：本地规则追问与逐题评分；配置大模型后将自动启用 AI 增强。';
    }).catch(function () {
      notice.textContent = '当前模式状态暂时无法读取，文字面试仍可继续。';
    });
  }

  function loadUserDashboard() {
    var cardsEl = document.getElementById('userStatCards');
    if (!cardsEl) return;
    cardsEl.innerHTML = '<div class="loading">加载中…</div>';
    return API.getDashboardUser().then(function (data) {
      var total = data.total_sessions != null ? data.total_sessions : 0;
      var avg = data.average_score != null ? data.average_score : null;
      var best = data.best_score != null ? data.best_score : null;
      var recent5 = data.recent_5_avg != null ? data.recent_5_avg : null;
      cardsEl.innerHTML = [
        { label: '面试总场次', value: total },
        { label: '正式面试', value: data.standard_total_sessions != null ? data.standard_total_sessions : '-' },
        { label: '专项训练', value: data.training_total_sessions != null ? data.training_total_sessions : '-' },
        { label: '平均得分', value: typeof avg === 'number' ? avg.toFixed(1) : (avg != null ? avg : '-') },
        { label: '最高得分', value: typeof best === 'number' ? best.toFixed(1) : (best != null ? best : '-') },
        { label: '最近5场均分', value: typeof recent5 === 'number' ? recent5.toFixed(1) : (recent5 != null ? recent5 : '-') }
      ].map(function (s) { return '<div class="stat-card"><div class="label">' + s.label + '</div><div class="value">' + s.value + '</div></div>'; }).join('');

      // ---------- 成绩趋势：至少 2 个点才画图，否则只显示空状态 ----------
      var trend = data.average_score_trend || [];
      var trendScopeEl = document.getElementById('userTrendScope');
      if (trendScopeEl) {
        var scopeText = data.trend_position_name
          ? ('对比范围：' + data.trend_position_name + ' · ' + (data.trend_scoring_version || '当前评分版本'))
          : '';
        if (scopeText && data.trend_uses_fallback) {
          scopeText += '（最新分组不足 2 场，已展示最近可比较分组）';
        }
        trendScopeEl.textContent = scopeText;
      }
      var trendHintEl = document.getElementById('userChartTrendHint');
      var trendWrap = document.getElementById('userChartTrend') && document.getElementById('userChartTrend').closest('.chart-inner');
      if (trendHintEl) {
        if (trend.length === 0) trendHintEl.textContent = '完成至少 2 次面试后，将在这里展示成绩趋势';
        else if (trend.length === 1) trendHintEl.textContent = '再完成 1 次面试即可显示趋势线';
        else trendHintEl.textContent = '';
        trendHintEl.classList.toggle('is-visible', trend.length < 2);
      }
      if (trendWrap) trendWrap.classList.toggle('chart-empty', trend.length < 2);
      var ctx = document.getElementById('userChartTrend');
      if (userChartTrend) { userChartTrend.destroy(); userChartTrend = null; }
      if (ctx && trend.length >= 2 && window.Chart) {
        var trendLabels = trend.map(function (t) { return (t.date || '').toString().slice(5); });
        var trendScores = trend.map(function (t) { return t.score; });
        userChartTrend = new Chart(ctx.getContext('2d'), {
          type: 'line',
          data: {
            labels: trendLabels,
            datasets: [{
              label: '得分',
              data: trendScores,
              borderColor: '#006EFF',
              backgroundColor: 'rgba(0,110,255,0.12)',
              fill: true,
              tension: 0.3,
              pointRadius: 4,
              pointHoverRadius: 8
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: { y: { min: 0, max: 100 } },
            plugins: { legend: { display: true } }
          }
        });
      }

      function renderMultiLineTrend(canvasId, hintId, rows, scoreField, definitions, previousChart) {
        var canvas = document.getElementById(canvasId);
        var hint = document.getElementById(hintId);
        var wrap = canvas && canvas.closest('.chart-inner');
        var hasTrend = rows.length >= 2;
        if (hint) hint.classList.toggle('is-visible', !hasTrend);
        if (wrap) wrap.classList.toggle('chart-empty', !hasTrend);
        if (previousChart) previousChart.destroy();
        if (!canvas || !hasTrend || !window.Chart) return null;
        var colors = ['#006EFF', '#059669', '#F59E0B', '#EF4444', '#8B5CF6', '#0891B2'];
        var datasets = definitions.map(function (definition, index) {
          return {
            label: definition.label,
            data: rows.map(function (row) {
              var scores = row[scoreField] || {};
              return scores[definition.key] == null ? null : scores[definition.key];
            }),
            borderColor: colors[index % colors.length],
            backgroundColor: colors[index % colors.length],
            tension: 0.25,
            spanGaps: true
          };
        }).filter(function (dataset) {
          return dataset.data.some(function (value) { return value != null; });
        });
        if (!datasets.length) {
          if (hint) hint.classList.add('is-visible');
          if (wrap) wrap.classList.add('chart-empty');
          return null;
        }
        return new Chart(canvas.getContext('2d'), {
          type: 'line',
          data: {
            labels: rows.map(function (row) { return (row.date || '').toString().slice(5); }),
            datasets: datasets
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: { y: { min: 0, max: 100 } },
            plugins: { legend: { position: 'bottom' } }
          }
        });
      }

      userChartDimensions = renderMultiLineTrend(
        'userChartDimensions',
        'userChartDimensionsHint',
        data.dimension_trend || [],
        'scores',
        [
          { key: 'technical_correctness', label: '技术正确性' },
          { key: 'knowledge_depth', label: '知识深度' },
          { key: 'logic_structure', label: '逻辑结构' },
          { key: 'project_practice', label: '项目实践' },
          { key: 'job_fit', label: '岗位匹配' },
          { key: 'expression_performance', label: '表达表现' }
        ],
        userChartDimensions
      );
      userChartQuestionTypes = renderMultiLineTrend(
        'userChartQuestionTypes',
        'userChartQuestionTypesHint',
        data.question_type_trend || [],
        'scores',
        [
          { key: 'technical', label: '技术题' },
          { key: 'project', label: '项目题' },
          { key: 'scenario', label: '场景题' },
          { key: 'behavioral', label: '行为题' }
        ],
        userChartQuestionTypes
      );

      // ---------- 各岗位平均分：横向条形图（与竖柱、饼图区分） ----------
      var byPosition = data.scores_by_position || [];
      var byPosHintEl = document.getElementById('userChartByPositionHint');
      var byPosWrap = document.getElementById('userChartByPosition') && document.getElementById('userChartByPosition').closest('.chart-inner');
      if (byPosHintEl) {
        byPosHintEl.textContent = '完成面试后，将按岗位展示平均分';
        byPosHintEl.classList.toggle('is-visible', !byPosition.length);
      }
      if (byPosWrap) byPosWrap.classList.toggle('chart-empty', !byPosition.length);
      var ctxPos = document.getElementById('userChartByPosition');
      if (userChartByPosition) { userChartByPosition.destroy(); userChartByPosition = null; }
      if (ctxPos && byPosition.length && window.Chart) {
        var realScores = byPosition.map(function (p) { return p.avg_score; });
        var displayScores = realScores.map(function (s) { return (s === 0 || s == null) ? 8 : s; });
        userChartByPosition = new Chart(ctxPos.getContext('2d'), {
          type: 'bar',
          data: {
            labels: byPosition.map(function (p) { return p.position_name || p.position_code; }),
            datasets: [{ label: '平均分', data: displayScores, backgroundColor: 'rgba(0,110,255,0.75)' }]
          },
          options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            scales: { x: { min: 0, max: 100, beginAtZero: true } },
            plugins: {
              legend: { display: false },
              tooltip: {
                callbacks: {
                  label: function (ctx) {
                    var idx = ctx.dataIndex;
                    var real = realScores[idx];
                    return '平均分: ' + (real != null ? real : 0) + ' 分';
                  }
                }
              }
            }
          }
        });
      }

      // ---------- 得分分布：雷达图（待提升/良好/优秀 三轴），至少 2 次成绩才显示 ----------
      var scoreDist = data.score_distribution || [];
      var totalDistCount = scoreDist.reduce(function (sum, d) { return sum + (d.count || 0); }, 0);
      var hasDist = totalDistCount >= 2;
      var distHintEl = document.getElementById('userChartScoreDistHint');
      var distWrap = document.getElementById('userChartScoreDist') && document.getElementById('userChartScoreDist').closest('.chart-inner');
      if (distHintEl) {
        distHintEl.textContent = '完成至少 2 次面试后，将展示得分分布（待提升 / 良好 / 优秀）';
        distHintEl.classList.toggle('is-visible', !hasDist);
      }
      if (distWrap) distWrap.classList.toggle('chart-empty', !hasDist);
      var ctxDist = document.getElementById('userChartScoreDist');
      if (userChartScoreDist) { userChartScoreDist.destroy(); userChartScoreDist = null; }
      if (ctxDist && hasDist && window.Chart) {
        var distLabels = scoreDist.map(function (d) { return (d.label || d.range) + ' ' + (d.count || 0); });
        var distData = scoreDist.map(function (d) { return d.count || 0; });
        userChartScoreDist = new Chart(ctxDist.getContext('2d'), {
          type: 'radar',
          data: {
            labels: distLabels,
            datasets: [{
              label: '场次',
              data: distData,
              backgroundColor: 'rgba(0,110,255,0.2)',
              borderColor: '#006EFF',
              borderWidth: 2,
              pointBackgroundColor: '#006EFF',
              pointBorderColor: '#fff',
              pointHoverBackgroundColor: '#006EFF'
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              r: { min: 0, beginAtZero: true, ticks: { stepSize: 1 } }
            },
            plugins: { legend: { display: false } }
          }
        });
      }
      var recent = data.recent_scores || [];
      var recentEl = document.getElementById('userRecentScores');
      var recentHint = document.getElementById('userRecentScoresHint');
      if (recent.length === 0) {
        recentEl.innerHTML = '';
        if (recentHint) { recentHint.textContent = '完成模拟面试后，最近成绩将显示在这里'; recentHint.style.display = 'block'; }
      } else {
        if (recentHint) recentHint.style.display = 'none';
        recentEl.innerHTML = '<table class="table"><thead><tr><th>时间</th><th>得分</th><th>岗位</th></tr></thead><tbody>' + recent.map(function (r) { return '<tr><td>' + escapeHtml(String(r.date || r.started_at || '')) + '</td><td>' + ((r.score != null ? r.score : r.overall_score) ?? '-') + '</td><td>' + escapeHtml(r.position || '-') + '</td></tr>'; }).join('') + '</tbody></table>';
      }
      var weaknessEl = document.getElementById('userWeaknessSummary');
      if (weaknessEl) {
        var frequent = data.high_frequency_weaknesses || [];
        var improved = data.improved_weaknesses || [];
        if (!frequent.length && !improved.length) {
          weaknessEl.innerHTML = '<p class="empty-hint">' + (
            (data.average_score_trend || []).length >= 2
              ? '当前对比范围内未识别到低于 70 分的能力维度或缺失评分点。'
              : '完成至少两次同岗位、同评分版本面试后展示变化。'
          ) + '</p>';
        } else {
          var weaknessHtml = '';
          if (frequent.length) weaknessHtml += '<h4 class="small">高频待提升</h4><ul class="report-list">' + frequent.map(function (item) { return '<li>' + escapeHtml(item.label) + '（' + escapeHtml(String(item.count)) + ' 次）</li>'; }).join('') + '</ul>';
          if (improved.length) weaknessHtml += '<h4 class="small">已改善</h4><ul class="report-list">' + improved.map(function (item) { return '<li>' + escapeHtml(item.label) + '：' + escapeHtml(String(item.earlier_count)) + ' → ' + escapeHtml(String(item.recent_count)) + '</li>'; }).join('') + '</ul>';
          weaknessEl.innerHTML = weaknessHtml;
        }
      }
      var comparisonEl = document.getElementById('userTrainingComparisons');
      if (comparisonEl) {
        var comparisons = data.training_comparisons || [];
        var availableTasks = Number(data.available_training_tasks || 0);
        comparisonEl.innerHTML = comparisons.length ? '<p class="text-muted small">来源为完整面试，复测为三题专项训练；同评分版本下的变化仅作训练参考。</p><table class="table"><thead><tr><th>任务</th><th>来源</th><th>复测</th><th>变化</th></tr></thead><tbody>' + comparisons.map(function (item) {
          var delta = item.score_delta == null ? '-' : ((item.score_delta >= 0 ? '+' : '') + item.score_delta);
          return '<tr><td>' + escapeHtml(item.title || '专项训练') + '</td><td>' + escapeHtml(String(item.source_score == null ? '-' : item.source_score)) + '</td><td>' + escapeHtml(String(item.training_score == null ? '-' : item.training_score)) + '</td><td>' + escapeHtml(item.comparable ? String(delta) : '版本不同') + '</td></tr>';
        }).join('') + '</tbody></table>' : (
          '<p class="empty-hint">当前还没有已完成的专项复测，因此没有可展示的复测分数。</p>' +
          (availableTasks > 0
            ? '<p class="text-secondary small">已有 ' + escapeHtml(String(availableTasks)) + ' 个训练任务可继续。请到历史成绩打开报告并点击“开始专项训练”，完成后这里会显示来源分、复测分和变化。</p><a class="btn btn-sm btn-outline-primary" href="#history">查看历史成绩</a>'
            : '<p class="text-secondary small">完成正式面试并从报告启动专项训练后，这里会生成复测记录。</p>')
        );
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

  function renderInterviewStart() {
    clearVoiceDraft(true);
    document.getElementById('interviewStart').classList.remove('hide');
    document.getElementById('interviewOngoing').classList.add('hide');
    document.getElementById('interviewReport').classList.add('hide');
    currentSessionId = null;
    currentSession = null;
    var posSel = document.getElementById('interviewPosition');
    if (posSel) { posSel.innerHTML = '<option value="">请选择岗位</option>'; positions.forEach(function (p) { var o = document.createElement('option'); o.value = p.code; o.textContent = p.name + (p.maturity === 'beta' ? '（Beta）' : ''); posSel.appendChild(o); }); }
    loadActiveInterviewSessions(true);
  }

  function setInterviewControls(actions) {
    actions = actions || {};
    var replyArea = document.querySelector('.interview-reply-area');
    var finishBtn = document.getElementById('btnFinishInterview');
    var abandonBtn = document.getElementById('btnAbandonInterview');
    if (replyArea) replyArea.style.display = actions.can_reply === false ? 'none' : '';
    if (finishBtn) {
      finishBtn.disabled = !actions.can_finish;
      finishBtn.textContent = actions.can_finish ? '结束并生成报告' : '结束面试';
    }
    if (abandonBtn) abandonBtn.style.display = actions.can_abandon === false ? 'none' : '';
    if (currentSession) currentSession.available_actions = actions;
  }

  function loadActiveInterviewSessions(autoRestore) {
    var panel = document.getElementById('activeInterviewPanel');
    var list = document.getElementById('activeInterviewList');
    if (!panel || !list) return Promise.resolve();
    list.innerHTML = '<div class="loading">正在读取未完成面试…</div>';
    panel.classList.remove('hide');
    return API.getActiveInterviewSessions().then(function (data) {
      var sessions = data.sessions || data.items || [];
      var rememberedId = getRememberedSessionId();
      var remembered = sessions.find(function (item) { return item.id === rememberedId; });
      if (rememberedId && !remembered) rememberActiveSession(null);
      if (autoRestore && remembered) {
        return restoreInterviewSession(remembered.id, true);
      }
      if (!sessions.length) {
        panel.classList.add('hide');
        list.innerHTML = '';
        if (rememberedId) rememberActiveSession(null);
        return;
      }
      panel.classList.remove('hide');
      list.innerHTML = sessions.map(function (item) {
        var statusLabel = item.status === 'scoring' ? '等待生成报告' : (item.status === 'failed' ? '报告生成失败，可重试' : '进行中');
        var actionLabel = item.status === 'interviewing' ? '继续面试' : '继续处理';
        return '<div class="active-interview-item"><div class="active-interview-item__meta"><div class="active-interview-item__title">' + escapeHtml(item.position_name || item.position_code || '模拟面试') + (item.mode === 'training' ? ' · 专项训练' : '') + '</div><div class="active-interview-item__detail">' + escapeHtml(statusLabel) + ' · 已答 ' + escapeHtml(String(item.answered_question_count || 0)) + ' / ' + escapeHtml(String(item.total_question_count || 0)) + ' 题</div></div><div class="active-interview-item__actions"><button type="button" class="btn btn-sm btn-primary btn-resume-interview" data-id="' + item.id + '">' + actionLabel + '</button></div></div>';
      }).join('');
      list.querySelectorAll('.btn-resume-interview').forEach(function (button) {
        button.addEventListener('click', function () {
          setButtonLoading(button, true, '恢复中…');
          restoreInterviewSession(Number(button.dataset.id), false).catch(function () {
            setButtonLoading(button, false);
          });
        });
      });
    }).catch(function (err) {
      list.innerHTML = '<div class="empty-hint">' + escapeHtml(getErrorMessage(err) || '未完成面试读取失败') + '</div>';
    });
  }

  function restoreInterviewSession(sessionId, silent) {
    clearVoiceDraft(true);
    return API.getInterviewState(sessionId).then(function (data) {
      var session = data.session || {};
      if (session.status === 'completed' && data.available_actions && data.available_actions.can_view_report) {
        rememberActiveSession(null);
        return API.getReport(sessionId).then(function (reportData) {
          showCompletedReport(reportData.report || reportData);
        });
      }
      currentSessionId = data.session_id || session.id;
      currentSession = {
        question_ids: data.question_ids || [],
        mode: session.mode || 'standard',
        training_task: null,
        status: session.status,
        available_actions: data.available_actions || {}
      };
      rememberActiveSession(currentSessionId);
      document.getElementById('interviewStart').classList.add('hide');
      document.getElementById('interviewReport').classList.add('hide');
      document.getElementById('interviewOngoing').classList.remove('hide');
      var title = document.getElementById('interviewTopTitle');
      if (title) title.textContent = currentSession.mode === 'training' ? '专项训练' : '模拟面试';
      var dialogueList = document.getElementById('dialogueList');
      if (dialogueList) {
        dialogueList.innerHTML = '';
        (data.messages || []).forEach(function (message) {
          if (message.role === 'user') appendAnswerTurn(dialogueList, message.content, message.id, message.editable);
          else appendQuestionTurn(dialogueList, message.content);
        });
      }
      var progress = data.progress || {};
      var total = progress.total || currentSession.question_ids.length;
      var current = progress.current || 1;
      document.getElementById('progressCurrent').textContent = current;
      document.getElementById('progressTotal').textContent = total;
      updateInterviewQuestionIndex(current, total);
      var prompt = data.current_question && data.current_question.content;
      document.getElementById('currentQuestionText').textContent = prompt || '本场题目已完成，请生成报告。';
      var replyText = document.getElementById('replyText');
      if (replyText) replyText.value = '';
      updateDialogueListEmpty();
      scrollDialogueToBottom();
      setInterviewControls(data.available_actions);
      if (!silent && window.Toast) Toast.success('已恢复上次面试');
      if (session.status === 'scoring' && data.available_actions && data.available_actions.can_finish) {
        window.setTimeout(function () {
          finalizeCurrentInterview().catch(function () {});
        }, 0);
      }
      return data;
    }).catch(function (err) {
      if (getRememberedSessionId() === sessionId) rememberActiveSession(null);
      if (!silent && window.Toast) Toast.error(getErrorMessage(err) || '恢复面试失败');
      throw err;
    });
  }

  function activateInterview(data) {
    clearVoiceDraft(true);
    currentSessionId = data.session_id;
    rememberActiveSession(currentSessionId);
    var questionIds = data.question_ids || [];
    var first = data.first_question || {};
    currentSession = {
      question_ids: questionIds,
      first_question: first,
      mode: data.mode || 'standard',
      training_task: data.training_task || null,
      status: 'interviewing',
      available_actions: { can_reply: true, can_finish: false, can_abandon: true }
    };
    document.getElementById('interviewStart').classList.add('hide');
    document.getElementById('interviewReport').classList.add('hide');
    document.getElementById('interviewOngoing').classList.remove('hide');
    var title = document.getElementById('interviewTopTitle');
    if (title) {
      var trainingTitle = String((currentSession.training_task && currentSession.training_task.title) || '能力提升');
      title.textContent = currentSession.mode === 'training'
        ? '专项训练 · ' + trainingTitle.slice(0, 28)
        : '模拟面试';
    }
    var list = document.getElementById('dialogueList');
    if (list) list.innerHTML = '';
    var replyText = document.getElementById('replyText');
    if (replyText) replyText.value = '';
    document.getElementById('progressTotal').textContent = questionIds.length;
    document.getElementById('progressCurrent').textContent = '1';
    updateInterviewQuestionIndex(1, questionIds.length);
    var firstContent = first.content || '暂无题目，请结束面试';
    document.getElementById('currentQuestionText').textContent = firstContent;
    if (list && firstContent && firstContent !== '暂无题目，请结束面试') appendQuestionTurn(list, firstContent);
    updateDialogueListEmpty();
    setInterviewControls(currentSession.available_actions);
    speakQuestion(firstContent);
    if (window.Toast) Toast.info(currentSession.mode === 'training' ? '专项训练已开始，共 3 题' : '面试已开始');
  }

  function showCompletedReport(report) {
    document.getElementById('interviewStart').classList.add('hide');
    document.getElementById('interviewOngoing').classList.add('hide');
    document.getElementById('interviewReport').classList.remove('hide');
    var scoreEl = document.getElementById('reportScore');
    if (scoreEl) scoreEl.innerHTML = (report.overall_score != null && report.overall_score !== '') ? '<span class="report-score-label">综合得分</span><span class="report-score-value">' + escapeHtml(String(report.overall_score)) + '</span><span class="report-score-unit"> / 100 分</span>' : '暂无得分';
    var contentEl = document.getElementById('reportContent');
    if (contentEl) contentEl.innerHTML = window.renderReportHtml ? renderReportHtml(report) : '';
  }

  function finalizeCurrentInterview() {
    if (!currentSessionId) return Promise.resolve();
    var finishingSessionId = currentSessionId;
    var btn = document.getElementById('btnFinishInterview');
    var overlay = document.getElementById('interviewLayoutOverlay');
    var overlayText = document.getElementById('interviewOverlayText');
    if (btn) setButtonLoading(btn, true, '生成中…');
    if (overlay) { overlay.style.display = 'flex'; if (overlayText) overlayText.textContent = '正在生成报告，请稍候…'; }
    return API.finishInterview(finishingSessionId).then(function () {
      return API.getReport(finishingSessionId);
    }).then(function (data) {
      rememberActiveSession(null);
      showCompletedReport(data.report || data);
      // 报告写入后立即刷新隐藏的大屏 DOM。用户稍后返回大屏时无需
      // 强制刷新页面，也不会继续看到面试完成前的统计数据。
      loadUserDashboard();
      if (window.Toast) Toast.success('面试已结束');
    }).catch(function (err) {
      if (window.Toast) Toast.error(getErrorMessage(err));
      if (currentSession) {
        currentSession.status = 'failed';
        setInterviewControls({ can_reply: false, can_finish: true, can_abandon: true });
      }
      throw err;
    }).finally(function () {
      if (overlay) overlay.style.display = 'none';
      if (btn) setButtonLoading(btn, false);
      if (currentSession && currentSession.available_actions) setInterviewControls(currentSession.available_actions);
    });
  }

  function updateInterviewQuestionIndex(current, total) {
    var el = document.getElementById('interviewQuestionIndex');
    if (!el) return;
    el.innerHTML = '';
    var n = Math.max(1, parseInt(total, 10) || 1);
    var cur = Math.max(1, parseInt(current, 10) || 1);
    for (var i = 1; i <= n; i++) {
      var span = document.createElement('span');
      span.className = 'q-num' + (i === cur ? ' active' : '') + (i < cur ? ' done' : '');
      span.textContent = i;
      el.appendChild(span);
    }
  }

  function updateDialogueListEmpty() {
    var list = document.getElementById('dialogueList');
    var wrap = list && list.closest('.dialogue-list-wrap');
    if (wrap) wrap.classList.toggle('has-items', list && list.children.length > 0);
  }

  function appendQuestionTurn(list, questionText) {
    if (!list || !questionText) return;
    var turn = document.createElement('div');
    turn.className = 'dialogue-turn dialogue-turn--question';
    turn.innerHTML = '<div class="dialogue-turn__avatar" aria-hidden="true">题</div><div class="dialogue-turn__body"><div class="dialogue-turn__label">题目</div><div class="dialogue-turn__content"></div></div>';
    var content = turn.querySelector('.dialogue-turn__content');
    content.textContent = questionText;
    list.appendChild(turn);
  }

  function setAnswerEditable(turn, editable) {
    if (!turn) return;
    var body = turn.querySelector('.dialogue-turn__body');
    var editBtn = turn.querySelector('.dialogue-turn__edit-btn');
    if (!editable) {
      if (editBtn) editBtn.remove();
      turn.dataset.editable = 'false';
      return;
    }
    turn.dataset.editable = 'true';
    if (!body || editBtn) return;
    editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'dialogue-turn__edit-btn';
    editBtn.textContent = '编辑';
    editBtn.addEventListener('click', function () { enterAnswerEditMode(turn); });
    body.appendChild(editBtn);
  }

  function appendAnswerTurn(list, answerText, messageId, editable) {
    if (!list) return;
    var turn = document.createElement('div');
    turn.className = 'dialogue-turn dialogue-turn--answer';
    if (messageId) turn.dataset.messageId = String(messageId);
    turn.innerHTML = '<div class="dialogue-turn__avatar" aria-hidden="true">我</div><div class="dialogue-turn__body"><div class="dialogue-turn__label">我的回答</div><div class="dialogue-turn__content"></div></div>';
    var body = turn.querySelector('.dialogue-turn__body');
    var content = turn.querySelector('.dialogue-turn__content');
    content.textContent = (answerText && answerText.trim()) ? answerText.trim() : '[语音]';
    list.appendChild(turn);
    setAnswerEditable(turn, !!messageId && !!editable);
  }

  function enterAnswerEditMode(turn) {
    var contentEl = turn && turn.querySelector('.dialogue-turn__content');
    var editBtn = turn && turn.querySelector('.dialogue-turn__edit-btn');
    var wrap = turn && turn.querySelector('.dialogue-turn__edit-wrap');
    if (!contentEl || !turn || wrap) return;
    var messageId = turn.dataset && turn.dataset.messageId;
    if (!messageId || !currentSessionId) return;
    var currentText = contentEl.textContent || '';
    var editWrap = document.createElement('div');
    editWrap.className = 'dialogue-turn__edit-wrap';
    var textarea = document.createElement('textarea');
    textarea.className = 'dialogue-turn__edit-input';
    textarea.rows = 3;
    textarea.value = currentText;
    var btnRow = document.createElement('div');
    btnRow.className = 'dialogue-turn__edit-actions';
    var btnSave = document.createElement('button');
    btnSave.type = 'button';
    btnSave.className = 'btn btn-primary btn-sm';
    btnSave.textContent = '保存';
    var btnCancel = document.createElement('button');
    btnCancel.type = 'button';
    btnCancel.className = 'btn btn-outline-secondary btn-sm';
    btnCancel.textContent = '取消';
    btnRow.appendChild(btnSave);
    btnRow.appendChild(btnCancel);
    editWrap.appendChild(textarea);
    editWrap.appendChild(btnRow);
    contentEl.style.display = 'none';
    if (editBtn) editBtn.style.display = 'none';
    contentEl.parentNode.insertBefore(editWrap, contentEl.nextSibling);

    function exitEdit(applyText) {
      if (applyText != null) contentEl.textContent = applyText;
      contentEl.style.display = '';
      if (editBtn) editBtn.style.display = '';
      if (editWrap.parentNode) editWrap.parentNode.removeChild(editWrap);
    }

    btnCancel.addEventListener('click', function () { exitEdit(); });
    btnSave.addEventListener('click', function () {
      var newContent = textarea.value.trim();
      if (!newContent) { if (window.Toast) Toast.error('内容不能为空'); return; }
      btnSave.disabled = true;
      btnSave.textContent = '保存中…';
      API.updateInterviewMessage(currentSessionId, messageId, newContent).then(function (data) {
        exitEdit(newContent);
        setAnswerEditable(turn, !!data.editable);
        var list = document.getElementById('dialogueList');
        var lastQuestion = list && list.querySelector('.dialogue-turn--question:last-child .dialogue-turn__content');
        if (lastQuestion && data.assistant_content) lastQuestion.textContent = data.assistant_content;
        if (data.assistant_content) document.getElementById('currentQuestionText').textContent = data.assistant_content;
        var progress = data.progress || {};
        if (progress.current != null) document.getElementById('progressCurrent').textContent = progress.current;
        if (progress.total != null) document.getElementById('progressTotal').textContent = progress.total;
        if (progress.current != null && progress.total != null) updateInterviewQuestionIndex(progress.current, progress.total);
        if (currentSession) {
          currentSession.status = data.status || currentSession.status;
          currentSession.available_actions = data.available_actions || currentSession.available_actions;
        }
        setInterviewControls(data.available_actions || (currentSession && currentSession.available_actions));
        if (window.Toast) Toast.success('已更新');
        if (data.auto_finish) {
          window.setTimeout(function () {
            finalizeCurrentInterview().catch(function () {});
          }, 0);
        }
      }).catch(function (err) {
        if (window.Toast) Toast.error(getErrorMessage(err));
        btnSave.disabled = false;
        btnSave.textContent = '保存';
      });
    });
    textarea.focus();
  }

  function applyReplySuccess(data, userText, successMessage) {
    var list = document.getElementById('dialogueList');
    var lastTurn = list && list.lastElementChild;
    var lastIsQuestion = lastTurn && lastTurn.classList && lastTurn.classList.contains('dialogue-turn--question');
    if (!lastIsQuestion) {
      var currentQuestion = document.getElementById('currentQuestionText');
      var questionText = (currentQuestion && currentQuestion.textContent) ? currentQuestion.textContent.trim() : '';
      if (questionText && questionText !== '加载中…') appendQuestionTurn(list, questionText);
    }
    appendAnswerTurn(list, userText, data.user_message_id, data.user_message_editable);
    var replyText = document.getElementById('replyText');
    if (replyText) replyText.value = '';
    var progress = data.progress || {};
    var tot = progress.total != null ? progress.total : (currentSession && currentSession.question_ids ? currentSession.question_ids.length : 0);
    tot = Math.max(1, parseInt(tot, 10) || 1);
    var cur = progress.current != null ? progress.current : (list.querySelectorAll('.dialogue-turn--answer').length + 1);
    cur = Math.max(1, Math.min(parseInt(cur, 10) || 1, tot));
    document.getElementById('progressCurrent').textContent = cur;
    document.getElementById('progressTotal').textContent = tot;
    updateInterviewQuestionIndex(cur, tot);
    var nextContent = (data.content && data.content.trim()) ? data.content : '暂无下一题，可结束面试';
    document.getElementById('currentQuestionText').textContent = nextContent;
    updateDialogueListEmpty();
    scrollDialogueToBottom();
    if (currentSession) {
      currentSession.status = data.status || currentSession.status;
      currentSession.available_actions = data.available_actions || currentSession.available_actions;
    }
    setInterviewControls(data.available_actions || (currentSession && currentSession.available_actions));
    speakQuestion(nextContent);
    if (window.Toast) Toast.success(successMessage || '回答已提交');
    if (data.auto_finish) {
      window.setTimeout(function () { finalizeCurrentInterview().catch(function () {}); }, 0);
    }
  }

  function submitReply() {
    var text = document.getElementById('replyText').value.trim();
    if (!currentSessionId) return;
    if (!text) { if (window.Toast) Toast.error('请输入回答'); return; }
    var btn = document.getElementById('btnSendReply');
    var replyArea = document.querySelector('.interview-reply-area');
    var list = document.getElementById('dialogueList');
    var loadingBubble = null;
    if (btn) setButtonLoading(btn, true, '提交中…');
    if (replyArea) replyArea.classList.add('is-loading');
    if (list) {
      loadingBubble = document.createElement('div');
      loadingBubble.className = 'dialogue-item loading-msg';
      loadingBubble.textContent = '提交中…';
      list.appendChild(loadingBubble);
      scrollDialogueToBottom();
    }
    var requestId = (window.crypto && window.crypto.randomUUID)
      ? window.crypto.randomUUID()
      : String(Date.now()) + '-' + Math.random().toString(16).slice(2);
    API.replyInterview(currentSessionId, text, requestId).then(function (data) {
      if (loadingBubble && loadingBubble.parentNode) loadingBubble.remove();
      clearVoiceDraft(false);
      applyReplySuccess(data, text, '回答已提交');
    }).catch(function (err) {
      if (loadingBubble && loadingBubble.parentNode) loadingBubble.remove();
      if (window.Toast) Toast.error(getErrorMessage(err));
    }).finally(function () {
      if (btn) setButtonLoading(btn, false);
      if (replyArea) replyArea.classList.remove('is-loading');
    });
  }

  function loadHistory() {
    var tbody = document.getElementById('historyTbody');
    var empty = document.getElementById('historyEmpty');
    var pagination = document.getElementById('historyPagination');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="5"><div class="loading">加载中…</div></td></tr>';
    if (empty) empty.classList.add('hide');
    API.getDashboardUser().then(function (data) {
      var totalEl = document.getElementById('userHistoryTotal');
      var avgEl = document.getElementById('userHistoryAvg');
      var bestEl = document.getElementById('userHistoryBest');
      if (totalEl) totalEl.textContent = data.total_sessions != null ? data.total_sessions : '-';
      if (avgEl) avgEl.textContent = (data.average_score != null && typeof data.average_score === 'number') ? data.average_score.toFixed(1) : '-';
      if (bestEl) bestEl.textContent = (data.best_score != null && typeof data.best_score === 'number') ? data.best_score.toFixed(1) : '-';
    }).catch(function () {});
    API.getSessions({ page: historyPage, per_page: 10 }).then(function (data) {
      var list = data.sessions || data.items || [];
      var total = data.total != null ? data.total : 0;
      if (list.length === 0) { tbody.innerHTML = ''; if (empty) empty.classList.remove('hide'); }
      else {
        tbody.innerHTML = list.map(function (s) {
          var report = s.report || {};
          var score = report.overall_score != null ? report.overall_score : '-';
          var statusLabels = {
            interviewing: '进行中',
            scoring: '评分中',
            completed: '已完成',
            failed: '评分失败',
            abandoned: '已放弃'
          };
          var status = statusLabels[s.status] || '未开始';
          var positionLabel = (s.position_code || '-') + (s.mode === 'training' ? '（专项）' : '');
          return '<tr><td>' + escapeHtml(String(s.started_at || '').slice(0, 16)) + '</td><td>' + escapeHtml(positionLabel) + '</td><td>' + score + '</td><td>' + status + '</td><td><div class="history-actions"><button type="button" class="btn btn-sm btn-outline-primary btn-view-report" data-id="' + s.id + '">报告</button><button type="button" class="btn btn-sm btn-outline-danger btn-delete-session" data-id="' + s.id + '">删除</button></div></td></tr>';
        }).join('');
        tbody.querySelectorAll('.btn-view-report').forEach(function (b) { b.addEventListener('click', function () { showReportModal(Number(b.dataset.id)); }); });
        tbody.querySelectorAll('.btn-delete-session').forEach(function (b) {
          b.addEventListener('click', function () {
            var id = Number(b.dataset.id);
            if (!window.confirm('确定删除这条面试记录吗？')) return;
            setButtonLoading(b, true, '删除中…');
            API.deleteSession(id).then(function () {
              if (window.Toast) Toast.success('已删除');
              loadHistory();
            }).catch(function (err) {
              if (window.Toast) Toast.error(getErrorMessage(err));
              setButtonLoading(b, false);
            });
          });
        });
        renderPagination(pagination, historyPage, total, 10, function (p) { historyPage = p; loadHistory(); });
      }
    }).catch(function (err) {
      var msg = (window.getErrorMessage ? getErrorMessage(err) : (err && err.message)) || '加载失败';
      tbody.innerHTML = '<tr><td colspan="5" class="empty-hint">' + escapeHtml(msg) + '</td></tr>';
      if (window.Toast) Toast.error(msg);
    });
  }

  function showReportModal(sessionId) {
    var bodyEl = document.getElementById('modalReportBody');
    if (bodyEl) bodyEl.innerHTML = '<div class="loading">加载中…</div>';
    var modal = document.getElementById('modalReport');
    if (modal) bootstrap.Modal.getOrCreateInstance(modal).show();
    API.getReport(sessionId).then(function (data) {
      var report = data.report || data;
      var scoreHtml = (report.overall_score != null && report.overall_score !== '') ? '<div class="report-score-block"><span class="report-score-label">综合得分</span><span class="report-score-value">' + escapeHtml(String(report.overall_score)) + '</span><span class="report-score-unit"> / 100 分</span></div>' : '';
      if (bodyEl) bodyEl.innerHTML = scoreHtml + (window.renderReportHtml ? renderReportHtml(report) : '');
    }).catch(function (err) {
      if (bodyEl) bodyEl.innerHTML = '<p class="text-danger">' + escapeHtml(getErrorMessage(err)) + '</p>';
      if (window.Toast) Toast.error(getErrorMessage(err));
    });
  }

  function loadProfile() {
    document.getElementById('profileDisplayName').value = currentUser ? (currentUser.display_name || '') : '';
    document.getElementById('profilePassword').value = '';
  }

  API.getProfile().then(function (data) {
    currentUser = data.user;
    if (!currentUser) { window.location.href = '/login'; return; }
    if (currentUser.role === 'admin') { window.location.href = '/admin'; return; }
    document.getElementById('userDisplayName').textContent = currentUser.display_name || currentUser.username;
    Promise.all([loadPositions(), loadInterviewMode()]).then(function () {
      route();
      window.addEventListener('hashchange', route);
    });

    document.getElementById('btnStartInterview').addEventListener('click', function () {
      var code = document.getElementById('interviewPosition').value;
      if (!code) { if (window.Toast) Toast.error('请选择岗位'); return; }
      var btn = document.getElementById('btnStartInterview');
      if (btn) setButtonLoading(btn, true, '加载中…');
      API.startInterview(code).then(function (data) {
        activateInterview(data);
      }).catch(function (err) { if (window.Toast) Toast.error(getErrorMessage(err) || '启动失败'); }).finally(function () { if (btn) setButtonLoading(btn, false); });
    });

    document.addEventListener('click', function (event) {
      var button = event.target.closest && event.target.closest('.btn-start-training');
      if (!button) return;
      var sourceSessionId = Number(button.getAttribute('data-source-session'));
      var taskId = '';
      try {
        taskId = decodeURIComponent(button.getAttribute('data-task-id') || '');
      } catch (error) {
        taskId = '';
      }
      if (!sourceSessionId || !taskId) {
        if (window.Toast) Toast.error('训练任务信息不完整，请刷新报告后重试');
        return;
      }
      setButtonLoading(button, true, '创建中…');
      API.startTraining(sourceSessionId, taskId).then(function (data) {
        var modal = document.getElementById('modalReport');
        if (modal && window.bootstrap) {
          var modalInstance = bootstrap.Modal.getInstance(modal);
          if (modalInstance) modalInstance.hide();
        }
        history.replaceState(null, '', '#interview');
        setView('userInterview');
        activateInterview(data);
      }).catch(function (err) {
        if (window.Toast) Toast.error(getErrorMessage(err) || '专项训练创建失败');
        setButtonLoading(button, false);
      });
    });

    document.getElementById('btnSendReply').addEventListener('click', submitReply);
    document.getElementById('replyText').addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitReply(); } });

    document.getElementById('btnVoice').addEventListener('click', function () {
      var btn = document.getElementById('btnVoice');
      if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
        stopRecordingTimer();
        btn.classList.remove('recording');
        btn.innerHTML = '<span>⏳</span> 处理中…';
        btn.disabled = true;
        return;
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
        if (window.Toast) Toast.error('当前浏览器不支持录音，请改用 Chrome/Edge 或直接文字作答');
        return;
      }
      clearVoiceDraft(false);
      navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
        mediaRecorder = new MediaRecorder(stream);
        recordingStartedAt = Date.now();
        var chunks = [];
        mediaRecorder.ondataavailable = function (e) { if (e.data.size) chunks.push(e.data); };
        mediaRecorder.onstop = function () {
          stream.getTracks().forEach(function (t) { t.stop(); });
          var recordedDurationMs = recordingStartedAt ? Date.now() - recordingStartedAt : null;
          recordingStartedAt = null;
          stopRecordingTimer();
          var blob = new Blob(chunks, { type: mediaRecorder.mimeType || 'audio/webm' });
          if (!currentSessionId || !blob.size) {
            resetVoiceButton();
            if (window.Toast) Toast.error('未录制到有效音频，请重试或改用文字输入');
            return;
          }
          var draft = document.getElementById('voiceDraft');
          var status = document.getElementById('voiceDraftStatus');
          if (draft) draft.classList.remove('hide');
          if (status) status.textContent = '正在转码并识别，尚未提交…';
          blobToWav16k(blob).then(function (wavBlob) {
            var file = new File([wavBlob], 'rec.wav', { type: 'audio/wav' });
            var playbackUrl = URL.createObjectURL(wavBlob);
            pendingVoiceDraft = {
              file: file,
              durationMs: recordedDurationMs,
              playbackUrl: playbackUrl,
              transcript: '',
              transcriptionReceipt: ''
            };
            var playback = document.getElementById('voicePlayback');
            if (playback) playback.src = playbackUrl;
            return API.transcribeInterviewAudio(file);
          }).then(function (data) {
            if (!pendingVoiceDraft) return;
            pendingVoiceDraft.transcript = data.transcript || '';
            pendingVoiceDraft.transcriptionReceipt = data.transcription_receipt || '';
            var replyText = document.getElementById('replyText');
            if (replyText) { replyText.value = pendingVoiceDraft.transcript; replyText.focus(); }
            var seconds = Math.max(0.1, (pendingVoiceDraft.durationMs || 0) / 1000).toFixed(1);
            if (status) status.textContent = '已识别 ' + seconds + ' 秒录音；请回放并确认转写内容。';
          }).catch(function (err) {
            if (status) status.textContent = '转写失败：' + (getErrorMessage(err) || '请重新录制或改用文字输入');
            if (window.Toast) Toast.error(getErrorMessage(err) || '语音识别失败，可重录或使用文字输入');
          }).finally(function () { resetVoiceButton(); });
        };
        mediaRecorder.start();
        btn.classList.add('recording');
        btn.innerHTML = '<span>⏹</span> 停止录音 0s';
        recordingTimer = setInterval(function () {
          if (!recordingStartedAt || !mediaRecorder || mediaRecorder.state !== 'recording') return;
          btn.innerHTML = '<span>⏹</span> 停止录音 ' + Math.floor((Date.now() - recordingStartedAt) / 1000) + 's';
        }, 500);
      }).catch(function () {
        resetVoiceButton();
        if (window.Toast) Toast.error('无法使用麦克风：请允许浏览器麦克风权限，或直接使用文字输入');
      });
    });

    document.getElementById('btnConfirmVoice').addEventListener('click', function () {
      if (!pendingVoiceDraft || !currentSessionId) {
        if (window.Toast) Toast.error('请先录制并完成语音转写');
        return;
      }
      var confirmedText = document.getElementById('replyText').value.trim();
      if (!confirmedText) {
        if (window.Toast) Toast.error('转写内容为空，请重录或改用文字输入');
        return;
      }
      var button = document.getElementById('btnConfirmVoice');
      var draftSnapshot = pendingVoiceDraft;
      var requestId = (window.crypto && window.crypto.randomUUID)
        ? window.crypto.randomUUID()
        : String(Date.now()) + '-' + Math.random().toString(16).slice(2);
      setButtonLoading(button, true, '提交中…');
      API.replyInterviewAudio(
        currentSessionId,
        draftSnapshot.file,
        requestId,
        draftSnapshot.durationMs,
        confirmedText,
        draftSnapshot.transcriptionReceipt
      ).then(function (data) {
        var metric = data.expression_metric;
        var metricText = metric ? '（' + metric.duration_seconds + ' 秒，' + metric.characters_per_minute + ' 字/分钟）' : '';
        clearVoiceDraft(false);
        applyReplySuccess(data, data.user_content || confirmedText, '语音已确认并提交' + metricText);
      }).catch(function (err) {
        if (window.Toast) Toast.error(getErrorMessage(err) || '语音提交失败，草稿已保留');
      }).finally(function () { setButtonLoading(button, false); });
    });

    document.getElementById('btnRerecordVoice').addEventListener('click', function () {
      clearVoiceDraft(true);
      document.getElementById('btnVoice').click();
    });
    document.getElementById('btnCancelVoice').addEventListener('click', function () {
      clearVoiceDraft(true);
      if (window.Toast) Toast.info('语音草稿已取消，本题进度未变更');
    });

    document.getElementById('btnFinishInterview').addEventListener('click', function () {
      finalizeCurrentInterview().catch(function () {});
    });

    document.getElementById('btnAbandonInterview').addEventListener('click', function () {
      if (!currentSessionId) return;
      if (!window.confirm('确定放弃这场面试吗？已产生的回答会保留，但不能继续作答或生成正式报告。')) return;
      var btn = document.getElementById('btnAbandonInterview');
      var abandoningSessionId = currentSessionId;
      setButtonLoading(btn, true, '放弃中…');
      API.abandonInterview(abandoningSessionId).then(function () {
        rememberActiveSession(null);
        if (window.Toast) Toast.success('已放弃该场面试');
        renderInterviewStart();
      }).catch(function (err) {
        if (window.Toast) Toast.error(getErrorMessage(err));
      }).finally(function () {
        setButtonLoading(btn, false);
      });
    });

    document.getElementById('btnBackAfterReport').addEventListener('click', function () {
      rememberActiveSession(null);
      renderInterviewStart();
    });

    document.getElementById('btnSaveProfile').addEventListener('click', function () {
      var btn = document.getElementById('btnSaveProfile');
      var errEl = document.getElementById('profileSaveError');
      var display_name = document.getElementById('profileDisplayName').value.trim() || null;
      var password = document.getElementById('profilePassword').value || undefined;
      if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
      if (btn) setButtonLoading(btn, true, '保存中…');
      API.updateProfile({ display_name: display_name, password: password }).then(function () {
        if (currentUser) currentUser.display_name = display_name;
        document.getElementById('userDisplayName').textContent = display_name || currentUser.username;
        if (window.Toast) Toast.success('已保存');
      }).catch(function (err) {
        var msg = getErrorMessage(err);
        if (errEl) { errEl.textContent = msg; errEl.style.display = 'block'; }
        if (window.Toast) Toast.error(msg);
      }).finally(function () { if (btn) setButtonLoading(btn, false); });
    });

    document.getElementById('btnExportPersonalData').addEventListener('click', function () {
      var btn = document.getElementById('btnExportPersonalData');
      setButtonLoading(btn, true, '导出中…');
      API.exportPersonalData().then(function (data) {
        var blob = new Blob([JSON.stringify(data.export || {}, null, 2)], { type: 'application/json;charset=utf-8' });
        var url = URL.createObjectURL(blob);
        var link = document.createElement('a');
        link.href = url;
        link.download = 'ai-interview-personal-data.json';
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        if (window.Toast) Toast.success('个人数据已导出');
      }).catch(function (err) {
        if (window.Toast) Toast.error(getErrorMessage(err));
      }).finally(function () { setButtonLoading(btn, false); });
    });

    document.getElementById('btnDeleteOwnAccount').addEventListener('click', function () {
      var passwordEl = document.getElementById('deleteAccountPassword');
      var password = passwordEl.value || '';
      if (!password) {
        if (window.Toast) Toast.error('请先输入当前密码');
        return;
      }
      if (!window.confirm('此操作会永久删除账号、面试回答、评分和训练记录，且无法恢复。确定继续吗？')) return;
      var btn = document.getElementById('btnDeleteOwnAccount');
      setButtonLoading(btn, true, '删除中…');
      API.deleteOwnAccount(password).then(function () {
        window.location.href = '/login';
      }).catch(function (err) {
        passwordEl.value = '';
        if (window.Toast) Toast.error(getErrorMessage(err));
      }).finally(function () { setButtonLoading(btn, false); });
    });

    document.getElementById('btnLogout').addEventListener('click', function () {
      var btn = document.getElementById('btnLogout');
      btn.disabled = true;
      API.logout().then(function () { window.location.href = '/login'; }).catch(function () { window.location.href = '/login'; }).finally(function () { btn.disabled = false; });
    });
  }).catch(function () { window.location.href = '/login'; });
})();
