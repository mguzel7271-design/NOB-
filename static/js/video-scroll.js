(function() {
    var feed = document.getElementById('videoFeed');
    if (!feed) return;

    var loading = false;
    var page = 1;
    var spinner = document.getElementById('loadingSpinner');
    var searchQ = new URLSearchParams(window.location.search).get('q') || '';
    var isScrolling = false;

    function preloadNext() {
        var cards = feed.querySelectorAll('.video-card');
        var nextVideo = null;
        var fRect = feed.getBoundingClientRect();
        for (var i = 0; i < cards.length; i++) {
            var r = cards[i].getBoundingClientRect();
            if (r.top > fRect.top + 50) {
                nextVideo = cards[i].querySelector('.feed-video');
                break;
            }
        }
        if (nextVideo && nextVideo.getAttribute('preloaded') !== '1') {
            nextVideo.setAttribute('preloaded', '1');
            nextVideo.preload = 'auto';
            var src = nextVideo.getAttribute('src');
            if (src) {
                var link = document.createElement('link');
                link.rel = 'preload';
                link.as = 'video';
                link.href = src;
                document.head.appendChild(link);
            }
        }
    }

    function playCurrentVideo() {
        var cards = feed.querySelectorAll('.video-card');
        var best = null, bestArea = 0;
        var fRect = feed.getBoundingClientRect();
        cards.forEach(function(c) {
            var r = c.getBoundingClientRect();
            var vt = Math.max(r.top, fRect.top);
            var vb = Math.min(r.bottom, fRect.bottom);
            var vh = Math.max(0, vb - vt);
            if (vh > bestArea) { bestArea = vh; best = c; }
        });
        if (best) {
            feed.querySelectorAll('.feed-video').forEach(function(v) { if (!best.contains(v)) { v.pause(); v.muted = true; } });
            var video = best.querySelector('.feed-video');
            if (video) { video.muted = false; var p = video.play(); if (p) p.catch(function(){}); }
            preloadNext();
        }
    }

    feed.addEventListener('scroll', function() {
        if (!isScrolling) {
            isScrolling = true;
            feed.querySelectorAll('.feed-video').forEach(function(v) { v.muted = true; });
        }
        if (this._st) clearTimeout(this._st);
        this._st = setTimeout(function() {
            isScrolling = false;
            playCurrentVideo();
        }, 100);

        if (loading) return;
        if (feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 600) {
            loading = true;
            if (spinner) spinner.style.display = 'block';
            page++;
            fetch('/api/videos?page=' + page + (searchQ ? '&q=' + encodeURIComponent(searchQ) : ''))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.length) { if (spinner) spinner.textContent = ''; loading = false; return; }
                data.forEach(function(v) {
                    var div = document.createElement('div');
                    div.className = 'video-card';
                    div.dataset.videoId = v.id;
                    var roleBadge = (v.author_role && v.author_role !== 'user') ? '<span class="role-badge" style="background:' + ({owner:'#ffd700',admin:'#fe2c55',moderator:'#20d5ec'}[v.author_role]||'#888') + '">' + ({owner:'👑 Owner',admin:'🛡️ Admin',moderator:'⚔️ Mod'}[v.author_role]||'') + '</span>' : '';
                    div.innerHTML =
                        '<video src="/uploads/videos/' + v.file_path + '" loop muted playsinline class="feed-video"></video>' +
                        '<div class="video-info-overlay">' +
                            '<div class="video-user-row">' +
                                '<a href="/profile/' + v.author_username + '"><img src="/uploads/profile_pics/' + v.author_pic + '" alt="" class="comment-avatar"></a>' +
                                '<a href="/profile/' + v.author_username + '"><strong>' + v.author + '</strong></a>' +
                                (v.author_verified ? '<span class="verified-badge"></span>' : '') + roleBadge +
                            '</div>' +
                            (v.title ? '<strong class="video-title">' + escapeXml(v.title) + '</strong>' : '') +
                            '<span class="video-caption">' + escapeXml(v.caption) + '</span>' +
                            '<div class="sound-indicator">♪ ' + v.author + '</div>' +
                        '</div>' +
                        '<div class="video-actions">' +
                            '<button class="action-btn like-btn" onclick="toggleLike(' + v.id + ', this)"><span class="action-icon">♡</span><span class="action-count">' + v.likes + '</span></button>' +
                            '<button class="action-btn" onclick="openComments(' + v.id + ')"><span class="action-icon">💬</span><span class="action-count">' + v.comments + '</span></button>' +
                            '<button class="action-btn bookmark-btn" onclick="toggleBookmark(' + v.id + ', this)"><span class="action-icon">🔖</span></button>' +
                            '<button class="action-btn" onclick="openReport(' + v.id + ', \'video\')"><span class="action-icon">⚑</span></button>' +
                        '</div>';
                    feed.appendChild(div);
                });
                loading = false;
                if (spinner) spinner.style.display = 'none';
                setTimeout(playCurrentVideo, 300);
            })
            .catch(function() { loading = false; if (spinner) spinner.style.display = 'none'; });
        }
    });

    feed.addEventListener('click', function(e) {
        var video = e.target.closest('.feed-video');
        if (video) { if (video.paused) video.play(); else video.pause(); }
    });

    function escapeXml(text) { if (!text) return ''; var d = document.createElement('div'); d.textContent = text; return d.innerHTML; }

    setTimeout(playCurrentVideo, 500);
})();
