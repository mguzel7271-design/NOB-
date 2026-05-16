var currentChatUser = null;
var chatInterval = null;

function startConversation(userId, userName) {
    currentChatUser = userId;
    if (chatInterval) clearInterval(chatInterval);
    var sidebar = document.querySelector('.messages-sidebar');
    var main = document.getElementById('messageMain');
    sidebar.style.display = 'none';
    main.style.display = 'flex';
    main.style.flexDirection = 'column';
    main.style.height = (window.innerWidth <= 768 ? 'calc(100dvh - var(--nav-height))' : '');
    main.innerHTML = '';
    var hdr = document.createElement('div');
    hdr.style.cssText = 'display:flex;align-items:center;gap:10px;padding:12px 14px;border-bottom:1px solid var(--border);flex-shrink:0;';
    var back = document.createElement('button');
    back.textContent = '←';
    back.style.cssText = 'background:none;border:none;color:var(--text);font-size:1.3rem;cursor:pointer;padding:0 4px;';
    back.onclick = backToConversations;
    var title = document.createElement('h3');
    title.textContent = userName;
    title.style.cssText = 'font-size:1rem;margin:0;';
    hdr.appendChild(back); hdr.appendChild(title);
    var msgs = document.createElement('div');
    msgs.id = 'chatMessages';
    msgs.style.cssText = 'flex:1;overflow-y:auto;padding:12px 14px;min-height:0;';
    var inp = document.createElement('div');
    inp.style.cssText = 'display:flex;gap:8px;padding:10px 14px;border-top:1px solid var(--border);flex-shrink:0;';
    var input = document.createElement('input');
    input.type = 'text';
    input.id = 'messageInput';
    input.placeholder = 'Mesaj yaz...';
    input.style.cssText = 'flex:1;padding:12px 16px;background:var(--bg);border:1px solid var(--border);border-radius:24px;color:var(--text);font-size:16px;outline:none;';
    input.onkeydown = function(e) { if (e.key === 'Enter') sendMessage(); };
    var btn = document.createElement('button');
    btn.id = 'sendBtn';
    btn.textContent = 'Gönder';
    btn.style.cssText = 'padding:12px 24px;background:var(--accent);color:#fff;border:none;border-radius:24px;cursor:pointer;font-weight:600;font-size:15px;white-space:nowrap;';
    btn.onclick = sendMessage;
    inp.appendChild(input); inp.appendChild(btn);
    main.appendChild(hdr); main.appendChild(msgs); main.appendChild(inp);
    setTimeout(function() { input.focus(); }, 300);
    loadMessages();
    chatInterval = setInterval(loadMessages, 2000);
}

function backToConversations() {
    var sidebar = document.querySelector('.messages-sidebar');
    var main = document.getElementById('messageMain');
    sidebar.style.display = '';
    main.style.display = '';
    main.style.flexDirection = '';
    main.style.height = '';
    main.innerHTML = '<div class="no-conversation" style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--text2);padding:20px;"><h2 style="font-size:1.2rem;margin-bottom:8px;">Select a conversation</h2><p style="font-size:0.9rem;">Choose someone from the list to start chatting</p></div>';
    currentChatUser = null;
    if (chatInterval) clearInterval(chatInterval);
}

function loadMessages() {
    if (!currentChatUser) return;
    fetch('/api/messages/' + currentChatUser)
    .then(function(r) { return r.json(); })
    .then(function(msgs) {
        var container = document.getElementById('chatMessages');
        if (!container) return;
        container.innerHTML = msgs.map(function(m) {
            var isOwn = m.sender_id === CURRENT_USER_ID;
            var roleBadge = (m.sender_role && m.sender_role !== 'user') ? '<span class="role-badge-xs" style="background:' + ({owner:'#ffd700',admin:'#fe2c55',moderator:'#20d5ec'}[m.sender_role]||'#888') + '">' + ({owner:'Owner',admin:'Admin',moderator:'Mod'}[m.sender_role]||'') + '</span>' : '';
            var verified = m.sender_verified ? ' <span class="verified-badge"></span>' : '';
            return '<div style="margin-bottom:10px;padding:10px 14px;background:' + (isOwn ? 'var(--accent)' : 'var(--card)') + ';border-radius:12px;max-width:80%;' + (isOwn ? 'margin-left:auto;' : '') + 'color:' + (isOwn ? '#fff' : 'var(--text)') + ';">' +
                '<strong style="font-size:0.75rem;opacity:0.7;display:block;">' + m.sender_name + '</strong>' + verified + roleBadge +
                '<p style="margin:2px 0;font-size:0.85rem;">' + escapeHtml(m.content) + '</p>' +
                '<small style="font-size:0.65rem;opacity:0.5;">' + new Date(m.created_at).toLocaleTimeString() + '</small>' +
                '</div>';
        }).join('');
        container.scrollTop = container.scrollHeight;
    });
}

function sendMessage() {
    var input = document.getElementById('messageInput');
    if (!input) return;
    var content = input.value.trim();
    if (!content || !currentChatUser) return;
    fetch('/api/messages/send', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({receiver_id: currentChatUser, content: content})
    })
    .then(function(r) { return r.json(); })
    .then(function() { input.value = ''; loadMessages(); })
    .catch(function() {});
}

function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
