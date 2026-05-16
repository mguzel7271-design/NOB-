document.addEventListener('DOMContentLoaded', function() {
    setTimeout(function() {
        document.querySelectorAll('.flash-message').forEach(function(el) {
            el.style.transition = 'opacity 0.4s';
            el.style.opacity = '0';
            setTimeout(function() { el.remove(); }, 400);
        });
    }, 4000);

    if (document.querySelector('.nav-toggle')) {
        document.addEventListener('click', function(e) {
            var nav = document.querySelector('.nav-links');
            if (nav && nav.classList.contains('active') && !e.target.closest('.navbar')) {
                nav.classList.remove('active');
            }
        });
    }

    if (document.querySelector('.notif-bell')) {
        pollNotifications();
        setInterval(pollNotifications, 10000);
    }
});

function pollNotifications() {
    fetch('/api/notifications/count')
    .then(function(r) { return r.json(); })
    .then(function(data) {
        var badge = document.getElementById('notifCount');
        if (!badge) return;
        var c = data.count;
        if (c > 0) {
            badge.style.display = 'flex';
            badge.textContent = c > 99 ? '99+' : c;
        } else {
            badge.style.display = 'none';
        }
    });
}

function toggleNotifications() {
    var panel = document.getElementById('notifPanel');
    if (panel.style.display === 'block') {
        panel.style.display = 'none';
        return;
    }
    panel.style.display = 'block';
    var list = document.getElementById('notifList');
    list.innerHTML = '<div class="loading" style="padding:20px;text-align:center;color:var(--text2);">Yükleniyor...</div>';
    fetch('/api/notifications')
    .then(function(r) { return r.json(); })
    .then(function(notifs) {
        if (!notifs.length) {
            list.innerHTML = '<div class="loading" style="padding:30px;text-align:center;color:var(--text2);">Bildirim yok.</div>';
            return;
        }
        list.innerHTML = '';
        notifs.forEach(function(n) {
            var div = document.createElement('div');
            var cls = 'notif-item';
            if (!n.is_read) cls += ' unread';
            if (n.is_warning) cls += ' warning';
            if (n.is_announcement) cls += ' announcement';
            div.className = cls;
            if (n.link) {
                div.style.cursor = 'pointer';
                div.addEventListener('click', function() { location.href = n.link; });
            }
            var msg = document.createElement('div');
            msg.className = 'notif-msg';
            msg.textContent = n.message;
            var small = document.createElement('small');
            small.textContent = timeAgo(n.created_at);
            div.appendChild(msg);
            div.appendChild(small);
            list.appendChild(div);
        });
    });
}

function readAllNotifs() {
    fetch('/api/notifications/read', { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function() {
        document.querySelectorAll('.notif-item').forEach(function(el) { el.classList.remove('unread'); });
        document.getElementById('notifCount').style.display = 'none';
    });
}

function timeAgo(iso) {
    var diff = Date.now() - new Date(iso).getTime();
    var sec = Math.floor(diff / 1000);
    if (sec < 60) return 'şimdi';
    var min = Math.floor(sec / 60);
    if (min < 60) return min + 'd';
    var hr = Math.floor(min / 60);
    if (hr < 24) return hr + 's';
    var d = Math.floor(hr / 24);
    return d + 'g';
}

document.addEventListener('click', function(e) {
    var panel = document.getElementById('notifPanel');
    if (panel && panel.style.display === 'block' && !e.target.closest('.notif-bell') && !e.target.closest('.notif-panel')) {
        panel.style.display = 'none';
    }
});
