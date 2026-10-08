/**
 * 登录页：已登录则按角色跳转；提交登录后跳转 /admin 或 /user
 */
(function () {
  var loginForm = document.getElementById('loginForm');
  var loginBtn = document.getElementById('loginBtn');
  var registerForm = document.getElementById('registerForm');
  var registerBtn = document.getElementById('registerBtn');
  if (!loginForm) return;

  function redirectByRole(role) {
    if (role === 'admin') window.location.href = '/admin';
    else window.location.href = '/user';
  }

  API.getProfile().then(function (data) {
    var user = data.user;
    if (user && user.role) redirectByRole(user.role);
  }).catch(function () {});

  function showLoginError(msg) {
    var el = document.getElementById('loginError');
    if (el) { el.textContent = msg || ''; el.style.display = msg ? 'block' : 'none'; }
    if (typeof Toast !== 'undefined' && msg) Toast.error(msg);
  }

  function showRegisterError(msg) {
    var el = document.getElementById('registerError');
    if (el) { el.textContent = msg || ''; el.style.display = msg ? 'block' : 'none'; }
    if (typeof Toast !== 'undefined' && msg) Toast.error(msg);
  }

  function setMode(mode) {
    var sub = document.getElementById('loginSub');
    if (mode === 'register') {
      if (loginForm) loginForm.classList.add('hide');
      if (registerForm) registerForm.classList.remove('hide');
      if (sub) sub.textContent = '创建新账号（普通用户）';
      showLoginError('');
      showRegisterError('');
    } else {
      if (registerForm) registerForm.classList.add('hide');
      if (loginForm) loginForm.classList.remove('hide');
      if (sub) sub.textContent = '请使用账号密码登录';
      showLoginError('');
      showRegisterError('');
    }
  }

  var toRegisterLink = document.getElementById('toRegisterLink');
  var toLoginLink = document.getElementById('toLoginLink');
  if (toRegisterLink) toRegisterLink.addEventListener('click', function (e) { e.preventDefault(); setMode('register'); });
  if (toLoginLink) toLoginLink.addEventListener('click', function (e) { e.preventDefault(); setMode('login'); });

  loginForm.addEventListener('submit', function (e) {
    e.preventDefault();
    showLoginError('');
    var username = document.getElementById('loginUsername').value.trim();
    var password = document.getElementById('loginPassword').value;
    if (!username || !password) {
      showLoginError('请输入用户名和密码');
      return;
    }
    loginBtn.disabled = true;
    API.login(username, password)
      .then(function () { return API.getProfile(); })
      .then(function (data) {
        if (typeof Toast !== 'undefined') Toast.success('登录成功');
        redirectByRole(data.user ? data.user.role : 'user');
      })
      .catch(function (err) {
        var msg = (typeof getErrorMessage === 'function' ? getErrorMessage(err) : (err && err.message)) || '登录失败，请检查网络或账号密码';
        showLoginError(msg);
        loginBtn.disabled = false;
      });
  });

  if (registerForm) {
    registerForm.addEventListener('submit', function (e) {
      e.preventDefault();
      showRegisterError('');

      var username = (document.getElementById('regUsername').value || '').trim();
      var displayName = (document.getElementById('regDisplayName').value || '').trim();
      var password = document.getElementById('regPassword').value || '';
      var password2 = document.getElementById('regPassword2').value || '';

      if (!username) return showRegisterError('请输入用户名');
      if (username.length < 3 || username.length > 64) return showRegisterError('用户名长度需为 3-64');
      if (!/^[A-Za-z0-9_-]+$/.test(username)) return showRegisterError('用户名仅支持字母/数字/下划线/短横线');
      if (!password || password.length < 6) return showRegisterError('密码至少 6 位');
      if (password !== password2) return showRegisterError('两次密码不一致');

      if (registerBtn) registerBtn.disabled = true;
      API.register({
        username: username,
        display_name: displayName || null,
        password: password,
        confirm_password: password2
      })
        .then(function () {
          // 注册成功后自动登录（避免用户再输一次）
          return API.login(username, password);
        })
        .then(function () { return API.getProfile(); })
        .then(function (data) {
          if (typeof Toast !== 'undefined') Toast.success('注册成功');
          redirectByRole(data.user ? data.user.role : 'user');
        })
        .catch(function (err) {
          var msg = (typeof getErrorMessage === 'function' ? getErrorMessage(err) : (err && err.message)) || '注册失败，请重试';
          showRegisterError(msg);
          if (registerBtn) registerBtn.disabled = false;
        });
    });
  }
})();
