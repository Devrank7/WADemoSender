/* ================================================================
   WhatsApp Chat Emulator — Chat Logic (Pixel-Perfect Android 2025)
   ================================================================ */

(function () {
  'use strict';

  // ───── Config from URL params ─────
  var params = new URLSearchParams(window.location.search);
  var config = {
    name: params.get('name') || 'AI Business Assistant',
    phone: params.get('phone') || '',
    avatar: params.get('avatar') || '',
    spreadsheet: params.get('spreadsheet') || '',
    row: params.get('row') || '',
  };

  // ───── Default avatar (Dark themed silhouette) ─────
  var DEFAULT_AVATAR =
    'data:image/svg+xml,' +
    encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96">' +
      '<circle cx="48" cy="48" r="48" fill="#3b4a54"/>' +
      '<circle cx="48" cy="36" r="14" fill="#5a6b75"/>' +
      '<ellipse cx="48" cy="72" rx="24" ry="18" fill="#5a6b75"/>' +
      '</svg>'
    );

  // ───── WhatsApp double-check SVG ─────
  var CHECK_SVG = '<svg viewBox="0 0 16 11" width="16" height="11">' +
    '<path d="M11.07 0.73l-5.24 5.24-1.64-1.64c-0.2-0.2-0.52-0.2-0.72 0s-0.2 0.52 0 0.72l2 2c0.1 0.1 0.23 0.15 0.36 0.15s0.26-0.05 0.36-0.15l5.6-5.6c0.2-0.2 0.2-0.52 0-0.72s-0.52-0.2-0.72 0z" fill="currentColor"/>' +
    '<path d="M15.07 0.73l-5.24 5.24-0.36-0.36c-0.2-0.2-0.52-0.2-0.72 0s-0.2 0.52 0 0.72l0.72 0.72c0.1 0.1 0.23 0.15 0.36 0.15s0.26-0.05 0.36-0.15l5.6-5.6c0.2-0.2 0.2-0.52 0-0.72s-0.52-0.2-0.72 0z" fill="currentColor"/>' +
    '</svg>';

  // ───── DOM refs ─────
  var chatArea = document.getElementById('chatArea');
  var messageInput = document.getElementById('messageInput');
  var headerName = document.getElementById('headerName');
  var headerAvatar = document.getElementById('headerAvatar');
  var headerStatus = document.getElementById('headerStatus');
  var cameraBtn = document.getElementById('cameraBtn');
  var actionBtn = document.getElementById('actionBtn');
  var statusBarTime = document.getElementById('statusBarTime');

  // ───── State ─────
  var conversationHistory = [];
  var sessionId = 'wa_emulator_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
  var isWaitingForResponse = false;
  var lastSentType = null;

  // ───── Time formatting ─────
  function formatTime24() {
    var now = new Date();
    return (
      now.getHours().toString().padStart(2, '0') +
      ':' +
      now.getMinutes().toString().padStart(2, '0')
    );
  }

  function updateStatusBarTime() {
    if (statusBarTime) {
      statusBarTime.textContent = formatTime24();
    }
  }

  // ───── Header status management ─────
  function setHeaderStatus(status) {
    if (!headerStatus) return;

    headerStatus.className = 'wa-header-status';

    switch (status) {
      case 'online':
        headerStatus.textContent = 'online';
        headerStatus.classList.add('online');
        break;
      case 'typing':
        headerStatus.textContent = 'digitando...';
        headerStatus.classList.add('typing');
        break;
      default:
        headerStatus.textContent = 'online';
        headerStatus.classList.add('online');
    }
  }

  // ───── Init ─────
  function init() {
    headerName.textContent = config.name;

    // Set avatar: explicit URL > auto-fetch by phone > default
    if (config.avatar) {
      setAvatar(config.avatar);
    } else if (config.phone) {
      fetchWhatsAppAvatar(config.phone);
    } else {
      setAvatar(DEFAULT_AVATAR);
    }

    // Update status bar time
    updateStatusBarTime();
    setInterval(updateStatusBarTime, 30000);

    // Set online status
    setHeaderStatus('online');

    // Add today's date separator
    addDateSeparator('HOJE');

    // Input event listeners
    messageInput.addEventListener('keydown', onKeyDown);
    messageInput.addEventListener('input', onInputChange);

    actionBtn.addEventListener('click', function () {
      if (messageInput.value.trim().length > 0) {
        sendMessage();
      }
    });

    autoResizeTextarea();

    // Auto-configure system prompt if spreadsheet + row params are present
    if (config.spreadsheet && config.row) {
      configurePrompt(config.spreadsheet, config.row);
    }
  }

  // ───── Toggle Action Button (Mic ↔ Send) with crossfade ─────
  function onInputChange() {
    var hasText = messageInput.value.trim().length > 0;
    var micIcon = actionBtn.querySelector('.mic-icon');
    var sendIcon = actionBtn.querySelector('.send-icon');

    if (hasText) {
      micIcon.classList.remove('visible');
      micIcon.classList.add('hidden');
      sendIcon.classList.remove('hidden');
      sendIcon.classList.add('visible');
      if (cameraBtn) {
        cameraBtn.classList.add('hidden');
      }
    } else {
      sendIcon.classList.remove('visible');
      sendIcon.classList.add('hidden');
      micIcon.classList.remove('hidden');
      micIcon.classList.add('visible');
      if (cameraBtn) {
        cameraBtn.classList.remove('hidden');
      }
    }

    // Auto-resize textarea
    messageInput.style.height = 'auto';
    messageInput.style.height = Math.min(messageInput.scrollHeight, 100) + 'px';
    scrollToBottom();
  }

  // ───── Auto-configure system prompt ─────
  function configurePrompt(spreadsheetId, row) {
    var statusEl = document.createElement('div');
    statusEl.className = 'config-status';
    statusEl.textContent = 'Configuring AI assistant...';
    document.querySelector('.wa-phone-frame').appendChild(statusEl);

    var requestBody = { spreadsheetId: spreadsheetId, row: parseInt(row, 10) };

    fetch('/proxy/configure-prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    })
      .then(function (resp) {
        return resp.json();
      })
      .then(function (data) {
        if (data.success) {
          statusEl.textContent = 'AI ready (' + data.promptLength + ' chars)';
          statusEl.classList.add('config-success');
        } else {
          statusEl.textContent = 'Error: ' + (data.error || 'unknown');
          statusEl.classList.add('config-error');
        }
        setTimeout(function () {
          statusEl.style.opacity = '0';
          setTimeout(function () { statusEl.remove(); }, 300);
        }, 2500);
      })
      .catch(function (err) {
        statusEl.textContent = 'Failed: ' + err.message;
        statusEl.classList.add('config-error');
        setTimeout(function () {
          statusEl.style.opacity = '0';
          setTimeout(function () { statusEl.remove(); }, 300);
        }, 3000);
      });
  }

  // ───── Avatar ─────
  function fetchWhatsAppAvatar(phone) {
    var cleanPhone = phone.replace(/\D/g, '');
    var proxyUrl = '/proxy/wa-avatar?phone=' + encodeURIComponent(cleanPhone);
    var testImg = new Image();
    testImg.onload = function () { setAvatar(proxyUrl); };
    testImg.onerror = function () { setAvatar(DEFAULT_AVATAR); };
    testImg.src = proxyUrl;
  }

  function setAvatar(url) {
    headerAvatar.src = url;
    headerAvatar.onerror = function () {
      headerAvatar.src = DEFAULT_AVATAR;
    };
  }

  // ───── Date separator ─────
  function addDateSeparator(text) {
    var el = document.createElement('div');
    el.className = 'wa-date-separator';
    el.textContent = text || 'HOJE';
    chatArea.appendChild(el);
    lastSentType = null;
  }

  // ───── Input handling ─────
  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  function autoResizeTextarea() {
    messageInput.addEventListener('input', function () {
      messageInput.style.height = 'auto';
      messageInput.style.height = Math.min(messageInput.scrollHeight, 100) + 'px';
      scrollToBottom();
    });
  }

  // ───── Send message ─────
  async function sendMessage() {
    var text = messageInput.value.trim();
    if (!text || isWaitingForResponse) return;

    isWaitingForResponse = true;

    // Clear input
    messageInput.value = '';
    messageInput.style.height = 'auto';
    onInputChange();
    messageInput.focus();

    // Show sent message
    addMessage(text, 'sent');

    // Update conversation history
    conversationHistory.push({ role: 'user', content: text });

    // Show "typing..." in header + typing bubble in chat
    setHeaderStatus('typing');
    var typingEl = showTyping();
    scrollToBottom();

    try {
      var response = await fetch('/proxy/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          conversationHistory: conversationHistory.slice(-10),
          sessionId: sessionId,
        }),
      });

      var data = await response.json();
      removeTyping(typingEl);
      setHeaderStatus('online');

      if (data.success && data.response) {
        addMessage(data.response, 'received');
        conversationHistory.push({ role: 'assistant', content: data.response });
      } else {
        addMessage('Desculpe, algo deu errado. Tente novamente.', 'received');
      }
    } catch (err) {
      removeTyping(typingEl);
      setHeaderStatus('online');
      addMessage('Erro de conexão. O servidor está funcionando?', 'received');
      console.error('Chat error:', err);
    }

    scrollToBottom();
    isWaitingForResponse = false;
  }

  // ───── Add message to chat ─────
  function addMessage(text, type) {
    var showTail = lastSentType !== type;
    lastSentType = type;

    var row = document.createElement('div');
    row.className = 'message-row ' + type;
    if (showTail) {
      row.classList.add('has-tail');
    }

    var bubble = document.createElement('div');
    bubble.className = 'message-bubble';

    // Message text
    var textSpan = document.createElement('span');
    textSpan.className = 'message-text';
    textSpan.textContent = text;
    bubble.appendChild(textSpan);

    // Time + checks metadata
    var meta = document.createElement('span');
    meta.className = 'message-meta';

    var timeSpan = document.createElement('span');
    timeSpan.className = 'message-time';
    timeSpan.textContent = formatTime24();
    meta.appendChild(timeSpan);

    if (type === 'sent') {
      var checks = document.createElement('span');
      checks.className = 'message-checks read';
      checks.innerHTML = CHECK_SVG;
      meta.appendChild(checks);
    }

    bubble.appendChild(meta);
    row.appendChild(bubble);
    chatArea.appendChild(row);
    scrollToBottom();
  }

  // ───── Typing indicator ─────
  function showTyping() {
    var container = document.createElement('div');
    container.className = 'typing-indicator';

    var bubble = document.createElement('div');
    bubble.className = 'typing-bubble';
    for (var i = 0; i < 3; i++) {
      var dot = document.createElement('div');
      dot.className = 'typing-dot';
      bubble.appendChild(dot);
    }
    container.appendChild(bubble);

    chatArea.appendChild(container);
    scrollToBottom();
    return container;
  }

  function removeTyping(el) {
    if (el && el.parentNode) {
      el.style.opacity = '0';
      el.style.transform = 'translateY(-4px)';
      el.style.transition = 'opacity 0.15s ease, transform 0.15s ease';
      setTimeout(function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, 150);
    }
    lastSentType = 'sent';
  }

  // ───── Scroll ─────
  function scrollToBottom() {
    requestAnimationFrame(function () {
      chatArea.scrollTo({
        top: chatArea.scrollHeight,
        behavior: 'smooth'
      });
    });
  }

  // ───── Start ─────
  init();
})();
