import os
import re
import shutil
import subprocess
import multiprocessing
import urllib.parse
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, jsonify, abort, send_from_directory)
import urllib.request
import json
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config
from models import db, User, Video, Like, Comment, Follow, Message, Group
from models import GroupMember, GroupMessage, Story, Report, Bookmark, Warning, Notification, CommentLike, DeletedUser
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)
app.config.from_object(Config)
app.config['WTF_CSRF_ENABLED'] = False
db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = ''

ALLOWED_VIDEO = {'mp4', 'webm', 'mov', 'avi'}
ALLOWED_IMAGE = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
ALLOWED_PROFILE = {'jpg', 'jpeg', 'png', 'gif', 'webp'}

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated

def owner_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'owner':
            abort(403)
        return f(*args, **kwargs)
    return decorated

def allowed_file(filename, allowed_set):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_set

def save_file(file, subdir, allowed_set):
    if file and allowed_file(file.filename, allowed_set):
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{datetime.utcnow().timestamp()}.{ext}"
        path = os.path.join(app.config['UPLOAD_FOLDER'], subdir, filename)
        file.save(path)
        return filename

BAD_WORDS = [
    'porn', 'porno', 'sex', 'seks', 'xxx', 'nude', 'nudity', 'nsfw',
    'sikiş', 'sikis', 'am', 'göt', 'yarrak', 'meme', 'memeler',
    'çıplak', 'ciplak', 'soyunma', 'striptiz', 'strip',
    'porno', 'pornografik', 'pornography', 'explicit', 'adult',
    'onlyfans', 'only fans', 'fuck', 'fucking', 'shit',
    'oral', 'anal', 'vagina', 'penis', 'cock', 'dick', 'ass',
    'sextape', 'sex tape', 'pornhub', 'xnxx', 'xvideos',
    '+18', '18+', 'nsfw', 'yetiskin', 'yetişkin',
    'şiddet', 'siddet', 'kill', 'killing', 'death', 'ölüm',
    'kan', 'blood', 'gore', 'şiddet', 'intihar', 'suicide',
    'terör', 'terror', 'terorist', 'terrorist',
    'uyuşturucu', 'uyusturucu', 'drug', 'weed', 'kokain',
    'silah', 'gun', 'weapon', 'bıçak', 'bicak', 'knife',
    'tecavüz', 'tecavuz', 'rape', 'istismar', 'abuse',
    'ensest', 'incest', 'reşit olmayan', 'reşit',
    'hayvan', 'animal', 'zoophile',
]

def moderate_content(title, caption):
    text = (title + ' ' + caption).lower()
    found = [w for w in BAD_WORDS if w in text]
    if found:
        return True, 'Uygunsuz içerik tespit edildi: ' + ', '.join(found)
    return False, ''

def compress_video(filename):
    upload_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
    input_path = os.path.join(upload_folder, 'videos', filename)
    temp_path = input_path + '_comp.mp4'
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        return
    try:
        cmd = ['ffmpeg', '-i', input_path,
            '-vf', 'scale=240:426:force_original_aspect_ratio=decrease,pad=240:426:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=20',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '40',
            '-c:a', 'aac', '-b:a', '32k', '-ac', '1', '-ar', '22050',
            '-movflags', '+faststart',
            '-threads', '1', '-y', temp_path]
        r = subprocess.run(cmd, capture_output=True, timeout=300)
        if r.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
            os.remove(input_path)
            os.rename(temp_path, input_path)
    except:
        try:
            if os.path.exists(temp_path): os.remove(temp_path)
        except: pass

def convert_to_9_16(input_path, output_path):
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height', '-of', 'csv=p=0',
            input_path], capture_output=True, text=True, timeout=30)
        if r.returncode != 0: return False
        parts = r.stdout.strip().split(',')
        if len(parts) < 2: return False
        w, h = int(parts[0]), int(parts[1])
        target_ratio = 9 / 16
        current_ratio = w / h
        if abs(current_ratio - target_ratio) > 0.02:
            new_w = w
            new_h = int(new_w / target_ratio)
            if new_h > h:
                new_h = h
                new_w = int(new_h * target_ratio)
            pad_top = (h - new_h) // 2
            pad_left = (w - new_w) // 2
            crop = f'crop={new_w}:{new_h}:{pad_left}:{pad_top},'
        else:
            crop = ''
        scale = 'scale=min(720,iw):min(1280,ih):force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2'
        cmd = ['ffmpeg', '-i', input_path, '-vf', crop + scale,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '30',
            '-c:a', 'aac', '-b:a', '64k', '-movflags', '+faststart',
            '-y', output_path]
        result = subprocess.run(cmd, capture_output=True, timeout=180)
        if result.returncode != 0: return False
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            try:
                os.remove(input_path)
                os.rename(output_path, input_path)
            except:
                return False
            return True
        return False
    except:
        return False

def add_notif(user_id, type, message, link='', actor_id=None, is_warning=False):
    notif = Notification(user_id=user_id, type=type, message=message,
                         link=link, actor_id=actor_id, is_warning=is_warning)
    db.session.add(notif)
    db.session.commit()

def are_friends(u1, u2):
    if u1 == u2: return True
    return Follow.query.filter_by(follower_id=u1.id, followed_id=u2.id).first() and \
           Follow.query.filter_by(follower_id=u2.id, followed_id=u1.id).first()

BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')
MAINTENANCE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'maintenance.lock')

def backup_database():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'nobi.db')
    if not os.path.exists(db_path): return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    filename = f"nobi_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    backup_path = os.path.join(BACKUP_DIR, filename)
    try:
        shutil.copy2(db_path, backup_path)
        backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith('.db')])
        while len(backups) > 20:
            os.remove(os.path.join(BACKUP_DIR, backups[0]))
            backups.pop(0)
        return filename
    except: return None

def is_maintenance():
    return os.path.exists(MAINTENANCE_FILE)

@app.before_request
def check_maintenance():
    if is_maintenance() and not current_user.is_authenticated:
        return render_template('maintenance.html'), 503
    if is_maintenance() and current_user.is_authenticated and current_user.role not in ('owner','admin'):
        logout_user()
        return render_template('maintenance.html'), 503

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.context_processor
def inject_now():
    return {'now': datetime.utcnow(), 'config': app.config}

@app.route('/banned')
def banned_page():
    return render_template('profile_banned.html',
        username=request.args.get('u',''),
        ban_reason=request.args.get('r',''),
        ban_date=request.args.get('d',''),
        ban_until=request.args.get('t',''),
        can_unban=request.args.get('unban','') == '1')

@app.before_request
def check_banned():
    if current_user.is_authenticated and (current_user.deleted or not current_user.password_hash):
        logout_user()
        return redirect(url_for('login'))
    if current_user.is_authenticated and current_user.is_banned:
        if current_user.banned_until and current_user.banned_until < datetime.utcnow():
            current_user.is_banned = False; current_user.ban_reason = ''; current_user.banned_until = None
            db.session.commit()
            return
        reason = current_user.ban_reason
        ban_date = current_user.created_at.strftime('%d%%20%B%%20%Y') if current_user.created_at else ''
        ban_until = current_user.banned_until.strftime('%d%%20%B%%20%Y') if current_user.banned_until else ''
        can_unban = '1' if current_user.banned_until and current_user.banned_until < datetime.utcnow() else '0'
        username = current_user.username
        logout_user()
        return redirect(url_for('banned_page', u=username, r=reason, d=ban_date, t=ban_until, unban=can_unban))

@app.before_request
def clean_expired_stories():
    expired = Story.query.filter(Story.expires_at < datetime.utcnow()).all()
    for s in expired:
        try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], 'stories', s.file_path))
        except: pass
        db.session.delete(s)
    db.session.commit()

@app.before_request
def update_last_seen():
    if current_user.is_authenticated:
        current_user.last_seen = datetime.utcnow()
        db.session.commit()

@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    q = request.args.get('q', '').strip()
    videos_query = Video.query.filter_by(approved=True)
    if q:
        videos_query = videos_query.filter(
            Video.title.ilike(f'%{q}%') | Video.caption.ilike(f'%{q}%')
        )
    videos = videos_query.order_by(Video.created_at.desc()).paginate(page=page, per_page=10, error_out=False)
    stories = []; story_users = []
    if current_user.is_authenticated:
        all_stories = Story.query.filter(Story.expires_at > datetime.utcnow())\
                             .order_by(Story.user_id, Story.created_at.desc()).all()
        seen = set()
        followed_ids = set()
        followed_ids.add(current_user.id)
        for f in Follow.query.filter_by(follower_id=current_user.id).all():
            followed_ids.add(f.followed_id)
        for s in all_stories:
            if s.user_id in seen or not s.author or s.author.is_banned: continue
            if s.user_id not in followed_ids: continue
            seen.add(s.user_id); story_users.append(s)
            stories.append(s)
    return render_template('index.html', videos=videos, stories=stories, story_users=story_users, search_query=q)

@app.route('/search')
def search():
    q = request.args.get('q', '').strip()
    if not q: return redirect(url_for('index'))
    users = User.query.filter(User.is_banned == False).filter(
        User.username.ilike(f'%{q}%') | User.nickname.ilike(f'%{q}%')
    ).limit(10).all()
    videos = Video.query.filter_by(approved=True).filter(
        Video.title.ilike(f'%{q}%') | Video.caption.ilike(f'%{q}%')
    ).order_by(Video.created_at.desc()).all()
    return render_template('search.html', query=q, users=users, videos=videos)

@app.route('/rules')
def rules():
    return render_template('rules.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email','').strip()
        username = request.form.get('username','').strip()
        nickname = request.form.get('nickname','').strip()
        password = request.form.get('password','')
        confirm = request.form.get('confirm_password','')
        recaptcha_response = request.form.get('g-recaptcha-response','')

        if not email or not username or not nickname or not password:
            flash('Tüm alanlar zorunludur.', 'error'); return render_template('register.html')
        if password != confirm: flash('Şifreler eşleşmiyor.', 'error'); return render_template('register.html')
        if User.query.filter_by(email=email).first(): flash('E-posta zaten kayıtlı.', 'error'); return render_template('register.html')
        if User.query.filter_by(username=username).first(): flash('Kullanıcı adı zaten alınmış.', 'error'); return render_template('register.html')
        if len(password) < 6: flash('Şifre en az 6 karakter olmalıdır.', 'error'); return render_template('register.html')

        # reCAPTCHA doğrulama
        if not recaptcha_response:
            flash('Lütfen robot olmadığınızı doğrulayın.', 'error'); return render_template('register.html')
        try:
            payload = urllib.parse.urlencode({'secret': app.config['RECAPTCHA_SECRET_KEY'], 'response': recaptcha_response}).encode()
            req = urllib.request.Request('https://www.google.com/recaptcha/api/siteverify', data=payload)
            resp = json.loads(urllib.request.urlopen(req, timeout=5).read())
            if not resp.get('success'):
                flash('reCAPTCHA doğrulaması başarısız. Lütfen tekrar deneyin.', 'error'); return render_template('register.html')
        except:
            flash('reCAPTCHA doğrulaması sırasında hata oluştu.', 'error'); return render_template('register.html')

        user = User(email=email, username=username, nickname=nickname,
                    password_hash=generate_password_hash(password), ip_address=request.remote_addr or '')
        db.session.add(user); db.session.commit(); login_user(user)
        flash('Hesap başarıyla oluşturuldu!', 'success')
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            if user.deleted or not user.password_hash:
                return render_template('login.html', deleted_account=True, deleted_reason='Hesap silinmiş')
            if user.is_banned:
                ban_until = user.banned_until.strftime('%d %B %Y') if user.banned_until else ''
                return render_template('login.html', banned_account=True, ban_reason=user.ban_reason, ban_until=ban_until, ban_date=user.created_at.strftime('%d %B %Y') if user.created_at else '', can_unban='1' if user.banned_until and user.banned_until < datetime.utcnow() else '0', banned_username=user.username)
            user.ip_address = request.remote_addr or user.ip_address; db.session.commit(); login_user(user)
            return redirect(request.args.get('next') or url_for('index'))
        flash('Geçersiz kullanıcı adı veya şifre.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('index'))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if not current_user.is_approved:
        flash('Video yüklemek için hesabınızın admin tarafından onaylanması gerekiyor.', 'error'); return redirect(url_for('index'))
    if request.method == 'POST':
        title = request.form.get('title','').strip()
        caption = request.form.get('caption','')
        if not title:
            flash('Video başlığı zorunludur.', 'error'); return render_template('upload.html')
        video_file = request.files.get('video')
        if not video_file or video_file.filename == '':
            flash('Lütfen bir video dosyası seçin.', 'error'); return render_template('upload.html')
        if not allowed_file(video_file.filename, ALLOWED_VIDEO):
            flash('Desteklenmeyen dosya formatı. Sadece MP4, WebM, MOV, AVI kabul edilir.', 'error'); return render_template('upload.html')
        if video_file.content_length and video_file.content_length > app.config['MAX_CONTENT_LENGTH']:
            flash('Dosya çok büyük. Maksimum 1GB.', 'error'); return render_template('upload.html')
        try:
            filename = save_file(video_file, 'videos', ALLOWED_VIDEO)
            if not filename:
                flash('Dosya kaydedilemedi.', 'error'); return render_template('upload.html')
            flagged, reason = moderate_content(title, caption)
            video = Video(user_id=current_user.id, title=title, caption=caption, file_path=filename, flagged=flagged, flag_reason=reason, approved=not flagged)
            db.session.add(video); db.session.commit()
            if flagged:
                flash('Videonuz incelemeye alındı. Admin onayından sonra yayınlanacaktır.', 'warning')
            else:
                flash('Video yüklendi! Arka planda sıkıştırılıyor...', 'success')
            multiprocessing.Process(target=compress_video, args=(filename,)).start()
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            flash('Video yüklenirken hata oluştu: ' + str(e), 'error')
    return render_template('upload.html')

@app.route('/video/<int:video_id>')
def video_page(video_id):
    video = Video.query.get_or_404(video_id)
    video.views += 1; db.session.commit()
    return render_template('video.html', video=video)

@app.route('/api/video/<int:video_id>/like', methods=['POST'])
@login_required
def like_video(video_id):
    video = Video.query.get_or_404(video_id)
    existing = Like.query.filter_by(user_id=current_user.id, video_id=video_id).first()
    if existing:
        db.session.delete(existing); db.session.commit()
        return jsonify({'liked': False, 'count': video.likes_count()})
    like = Like(user_id=current_user.id, video_id=video_id)
    db.session.add(like); db.session.commit()
    if video.user_id != current_user.id:
        add_notif(video.user_id, 'like', f'{current_user.nickname} videonu beğendi',
                  f'/video/{video_id}', current_user.id)
    return jsonify({'liked': True, 'count': video.likes_count()})

@app.route('/api/video/<int:video_id>/comment', methods=['POST'])
@login_required
def add_comment(video_id):
    video = Video.query.get_or_404(video_id)
    content = request.json.get('content','').strip()
    parent_id = request.json.get('parent_id')
    if not content: return jsonify({'error': 'Yorum boş olamaz'}), 400
    if parent_id:
        parent = Comment.query.get(parent_id)
        if not parent or parent.video_id != video_id: return jsonify({'error': 'Geçersiz yanıt'}), 400
    comment = Comment(user_id=current_user.id, video_id=video_id, content=content, parent_id=parent_id)
    db.session.add(comment); db.session.commit()
    if video.user_id != current_user.id:
        add_notif(video.user_id, 'comment', f'{current_user.nickname} videona yorum yaptı',
                  f'/video/{video_id}', current_user.id)
    if parent_id and parent.user_id != current_user.id:
        add_notif(parent.user_id, 'reply', f'{current_user.nickname} yorumuna yanıt verdi',
                  f'/video/{video_id}', current_user.id)
    return jsonify({
        'id': comment.id, 'content': comment.content,
        'parent_id': parent_id,
        'author': current_user.nickname, 'author_username': current_user.username,
        'author_pic': current_user.profile_pic,
        'author_verified': current_user.verified and current_user.show_verified,
        'author_role': current_user.role if current_user.show_role else 'user',
        'created_at': comment.created_at.isoformat()
    })

@app.route('/api/video/<int:video_id>/comments')
def get_comments(video_id):
    video = Video.query.get_or_404(video_id)
    comments = Comment.query.filter_by(video_id=video_id, parent_id=None).order_by(Comment.is_pinned.desc(), Comment.created_at.desc()).all()
    user_likes = set()
    if current_user.is_authenticated:
        user_likes = {cl.comment_id for cl in CommentLike.query.filter_by(user_id=current_user.id).join(Comment).filter(Comment.video_id == video_id).all()}
    def serialize(c):
        replies = Comment.query.filter_by(parent_id=c.id).order_by(Comment.created_at.asc()).all()
        return {
            'id': c.id, 'content': c.content, 'parent_id': c.parent_id, 'is_pinned': c.is_pinned,
            'likes': c.likes_count(), 'is_liked': c.id in user_likes,
            'author': c.author.nickname, 'author_username': c.author.username,
            'author_pic': c.author.profile_pic,
            'author_verified': c.author.verified and c.author.show_verified,
            'author_role': c.author.role if c.author.show_role else 'user',
            'is_video_owner': current_user.is_authenticated and video.user_id == current_user.id,
            'is_comment_owner': current_user.is_authenticated and c.user_id == current_user.id,
            'created_at': c.created_at.isoformat(),
            'replies': [serialize(r) for r in replies]
        }
    return jsonify([serialize(c) for c in comments])

@app.route('/api/comment/<int:comment_id>/pin', methods=['POST'])
@login_required
def pin_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    video = Video.query.get_or_404(comment.video_id)
    if video.user_id != current_user.id: return jsonify({'error': 'Yetkisiz'}), 403
    if comment.parent_id: return jsonify({'error': 'Yanıtlar sabitlenemez'}), 400
    Comment.query.filter_by(video_id=video.id, is_pinned=True).update({'is_pinned': False})
    comment.is_pinned = not comment.is_pinned
    db.session.commit()
    return jsonify({'is_pinned': comment.is_pinned})

@app.route('/api/comment/<int:comment_id>/like', methods=['POST'])
@login_required
def like_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    existing = CommentLike.query.filter_by(comment_id=comment_id, user_id=current_user.id).first()
    if existing:
        db.session.delete(existing); db.session.commit()
        return jsonify({'liked': False, 'count': comment.likes_count()})
    cl = CommentLike(user_id=current_user.id, comment_id=comment_id)
    db.session.add(cl); db.session.commit()
    return jsonify({'liked': True, 'count': comment.likes_count()})

@app.route('/api/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    video = Video.query.get_or_404(comment.video_id)
    if comment.user_id != current_user.id and video.user_id != current_user.id:
        return jsonify({'error': 'Yetkisiz'}), 403
    db.session.delete(comment); db.session.commit()
    return jsonify({'success': True})

@app.route('/api/video/<int:video_id>/bookmark', methods=['POST'])
@login_required
def bookmark_video(video_id):
    Video.query.get_or_404(video_id)
    existing = Bookmark.query.filter_by(user_id=current_user.id, video_id=video_id).first()
    if existing: db.session.delete(existing); db.session.commit(); return jsonify({'bookmarked': False})
    bm = Bookmark(user_id=current_user.id, video_id=video_id); db.session.add(bm); db.session.commit()
    return jsonify({'bookmarked': True})

# === NOBI STUDIO ===
@app.route('/studio')
@login_required
def studio():
    videos = Video.query.filter_by(user_id=current_user.id).order_by(Video.created_at.desc()).all()
    return render_template('studio.html', videos=videos)

@app.route('/api/studio/update/<int:video_id>', methods=['POST'])
@login_required
def studio_update_video(video_id):
    video = Video.query.get_or_404(video_id)
    if video.user_id != current_user.id: return jsonify({'error': 'Bu video size ait değil'}), 403
    title = request.form.get('title', '').strip()
    caption = request.form.get('caption', '').strip()
    if title: video.title = title
    video.caption = caption
    thumb = request.files.get('thumbnail')
    if thumb and allowed_file(thumb.filename, ALLOWED_IMAGE):
        filename = save_file(thumb, 'videos', ALLOWED_IMAGE)
        if filename: video.thumbnail = filename
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/studio/delete', methods=['POST'])
@login_required
def studio_delete_videos():
    video_ids = request.json.get('video_ids', [])
    if not video_ids: return jsonify({'error': 'Video seçilmedi'}), 400
    for vid in video_ids:
        video = Video.query.get(int(vid))
        if video and video.user_id == current_user.id:
            try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], 'videos', video.file_path))
            except: pass
            db.session.delete(video)
    db.session.commit()
    return jsonify({'success': True, 'deleted': len(video_ids)})

@app.route('/api/search')
def api_search():
    q = request.args.get('q', '').strip()
    if not q: return jsonify({'users': [], 'videos': []})
    users = User.query.filter(User.is_banned == False, User.is_approved == True).filter(
        User.username.ilike(f'%{q}%') | User.nickname.ilike(f'%{q}%')
    ).limit(5).all()
    videos = Video.query.filter_by(approved=True).filter(
        Video.title.ilike(f'%{q}%') | Video.caption.ilike(f'%{q}%')
    ).limit(5).all()
    return jsonify({
        'users': [{'id': u.id, 'username': u.username, 'name': u.nickname, 'pic': u.profile_pic} for u in users],
        'videos': [{'id': v.id, 'title': v.title or 'Başlıksız', 'author': v.author.nickname} for v in videos]
    })

@app.route('/api/videos')
def api_videos():
    page = request.args.get('page', 1, type=int)
    q = request.args.get('q', '').strip()
    videos_q = Video.query.filter_by(approved=True)
    if q:
        videos_q = videos_q.filter(Video.title.ilike(f'%{q}%') | Video.caption.ilike(f'%{q}%'))
    videos = videos_q.order_by(Video.created_at.desc()).paginate(page=page, per_page=5, error_out=False)
    return jsonify([{
        'id': v.id, 'title': v.title, 'caption': v.caption,
        'file_path': v.file_path, 'author_id': v.author.id,
        'author': v.author.nickname, 'author_username': v.author.username,
        'author_pic': v.author.profile_pic,
        'author_verified': v.author.verified and v.author.show_verified,
        'author_role': v.author.role if v.author.show_role else 'user',
        'likes': v.likes_count(), 'comments': v.comments_count(),
        'views': v.views, 'created_at': v.created_at.isoformat()
    } for v in videos.items])

@app.route('/profile/<username>')
def profile(username):
    user = User.query.filter_by(username=username).first()
    if not user:
        del_user = DeletedUser.query.filter_by(username=username).first()
        if del_user:
            return render_template('profile_deleted.html', username=username, reason=del_user.reason, date=del_user.deleted_at.strftime('%d %B %Y'))
        return render_template('profile_deleted.html', username=username)
    if user.is_banned:
        return render_template('profile_banned.html',
            username=username, ban_reason=user.ban_reason,
            ban_date=user.created_at.strftime('%d %B %Y %H:%M') if user.created_at else '',
            ban_until=user.banned_until.strftime('%d %B %Y %H:%M') if user.banned_until else '',
            can_unban=user.banned_until and user.banned_until < datetime.utcnow() and current_user.is_authenticated and current_user.id == user.id)
    videos = Video.query.filter_by(user_id=user.id).order_by(Video.created_at.desc()).all() if user.id == (current_user.id if current_user.is_authenticated else None) else Video.query.filter_by(user_id=user.id, approved=True).order_by(Video.created_at.desc()).all()
    is_following = False
    if current_user.is_authenticated and current_user != user: is_following = current_user.is_following(user)
    return render_template('profile.html', profile_user=user, videos=videos, is_following=is_following)

@app.route('/follow/<int:user_id>', methods=['POST'])
@login_required
def follow_user(user_id):
    target = User.query.get_or_404(user_id)
    if target == current_user: return jsonify({'error': 'Kendinizi takip edemezsiniz'}), 400
    existing = Follow.query.filter_by(follower_id=current_user.id, followed_id=user_id).first()
    if existing:
        db.session.delete(existing); db.session.commit()
        return jsonify({'following': False, 'count': target.followers_count()})
    follow = Follow(follower_id=current_user.id, followed_id=user_id)
    db.session.add(follow); db.session.commit()
    add_notif(user_id, 'follow', f'{current_user.nickname} seni takip etmeye başladı',
              f'/profile/{current_user.username}', current_user.id)
    return jsonify({'following': True, 'count': target.followers_count()})

@app.route('/report', methods=['POST'])
@login_required
def report_content():
    content_type = request.json.get('content_type')
    content_id = request.json.get('content_id')
    reason = request.json.get('reason','').strip()
    if not content_type or not content_id or not reason: return jsonify({'error': 'Eksik alanlar'}), 400
    report = Report(reporter_id=current_user.id, content_type=content_type, content_id=content_id, reason=reason)
    db.session.add(report); db.session.commit()
    return jsonify({'success': True})

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        action = request.form.get('action','')
        if action == 'profile':
            nickname = request.form.get('nickname','').strip()
            bio = request.form.get('bio','').strip()
            if nickname: current_user.nickname = nickname
            current_user.bio = bio; flash('Profil güncellendi!', 'success')
        elif action == 'email':
            email = request.form.get('email','').strip()
            if email and User.query.filter_by(email=email).first() and email != current_user.email:
                flash('E-posta zaten kullanımda.', 'error')
            elif email: current_user.email = email; flash('E-posta güncellendi!', 'success')
        elif action == 'password':
            old = request.form.get('old_password','')
            new = request.form.get('new_password','')
            confirm = request.form.get('confirm_password','')
            if not check_password_hash(current_user.password_hash, old): flash('Mevcut şifre yanlış.', 'error')
            elif new != confirm: flash('Şifreler eşleşmiyor.', 'error')
            elif len(new) < 6: flash('Şifre en az 6 karakter olmalıdır.', 'error')
            else: current_user.password_hash = generate_password_hash(new); flash('Şifre güncellendi!', 'success')
        elif action == 'username':
            username = request.form.get('username','').strip()
            if username and username != current_user.username:
                if User.query.filter_by(username=username).first(): flash('Kullanıcı adı zaten alınmış.', 'error')
                elif len(username) < 3: flash('Kullanıcı adı en az 3 karakter olmalıdır.', 'error')
                else: current_user.username = username; flash('Kullanıcı adı güncellendi!', 'success')
        elif action == 'birth_date':
            bd = request.form.get('birth_date','')
            if bd:
                try: current_user.birth_date = datetime.strptime(bd, '%Y-%m-%d').date(); flash('Doğum tarihi güncellendi!', 'success')
                except: flash('Geçersiz tarih formatı.', 'error')
        elif action == 'theme':
            current_user.theme = request.form.get('theme','dark'); flash('Tema güncellendi!', 'success')
        elif action == 'privacy':
            current_user.private = request.form.get('private') == 'on'
            current_user.show_verified = request.form.get('show_verified') == 'on'
            current_user.show_role = request.form.get('show_role') == 'on'
            flash('Gizlilik ayarları güncellendi!', 'success')
        elif action == 'delete_account':
            password = request.form.get('password','')
            if not check_password_hash(current_user.password_hash, password):
                flash('Şifre yanlış. Hesap silinemedi.', 'error')
            else:
                uid = current_user.id
                logout_user()
                user = User.query.get(uid)
                if user:
                    if user.role == 'owner':
                        flash('Owner hesabı silinemez.', 'error'); return redirect(url_for('settings'))
                    db.session.delete(user); db.session.commit()
                flash('Hesabınız kalıcı olarak silindi.', 'success')
                return redirect(url_for('register'))
        elif action == 'profile_pic':
            pic = request.files.get('profile_pic')
            if pic and allowed_file(pic.filename, ALLOWED_PROFILE):
                old_pic = current_user.profile_pic
                filename = save_file(pic, 'profile_pics', ALLOWED_PROFILE)
                if filename:
                    current_user.profile_pic = filename
                    if old_pic and old_pic != 'default.jpg':
                        try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], 'profile_pics', old_pic))
                        except: pass
                    flash('Profil fotoğrafı güncellendi!', 'success')
            else: flash('Geçersiz resim dosyası.', 'error')
        db.session.commit(); return redirect(url_for('settings'))
    return render_template('settings.html')

@app.route('/messages')
@login_required
def messages():
    conversations = {}
    sent = Message.query.filter_by(sender_id=current_user.id).order_by(Message.created_at.desc()).all()
    received = Message.query.filter_by(receiver_id=current_user.id).order_by(Message.created_at.desc()).all()
    for m in sent + received:
        other = m.receiver if m.sender_id == current_user.id else m.sender
        if other.id not in conversations or conversations[other.id].created_at < m.created_at:
            conversations[other.id] = m
    sorted_conv = sorted(conversations.values(), key=lambda x: x.created_at, reverse=True)
    users_list = User.query.filter(User.id != current_user.id, User.is_banned == False).order_by(User.nickname).all()
    return render_template('messages.html', conversations=sorted_conv, users=users_list)

@app.route('/api/messages/<int:user_id>')
@login_required
def get_messages(user_id):
    msgs = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == user_id)) |
        ((Message.sender_id == user_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.created_at.asc()).all()
    Message.query.filter_by(sender_id=user_id, receiver_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify([{
        'id': m.id, 'sender_id': m.sender_id, 'sender_name': m.sender.nickname,
        'sender_role': m.sender.role if m.sender.show_role else 'user',
        'sender_verified': m.sender.verified and m.sender.show_verified,
        'content': m.content, 'created_at': m.created_at.isoformat()
    } for m in msgs])

@app.route('/api/messages/send', methods=['POST'])
@login_required
def send_message():
    receiver_id = request.json.get('receiver_id')
    content = request.json.get('content','').strip()
    if not receiver_id or not content: return jsonify({'error': 'Eksik alanlar'}), 400
    msg = Message(sender_id=current_user.id, receiver_id=receiver_id, content=content)
    db.session.add(msg); db.session.commit()
    return jsonify({'id': msg.id, 'created_at': msg.created_at.isoformat()})

@app.route('/api/unread-count')
@login_required
def unread_count():
    count = Message.query.filter_by(receiver_id=current_user.id, is_read=False).count()
    return jsonify({'count': count})

@app.route('/groups')
@login_required
def groups():
    my_groups = Group.query.join(GroupMember).filter(GroupMember.user_id == current_user.id).all()
    users = User.query.filter(User.id != current_user.id, User.is_banned == False).order_by(User.nickname).all()
    return render_template('groups.html', groups=my_groups, users=users)

@app.route('/groups/create', methods=['POST'])
@login_required
def create_group():
    name = request.form.get('name','').strip()
    if not name: flash('Grup adı gerekli.', 'error'); return redirect(url_for('groups'))
    group = Group(name=name, created_by=current_user.id)
    db.session.add(group); db.session.flush()
    db.session.add(GroupMember(group_id=group.id, user_id=current_user.id))
    for mid in request.form.getlist('members'):
        if int(mid) != current_user.id and User.query.get(int(mid)):
            db.session.add(GroupMember(group_id=group.id, user_id=int(mid)))
    db.session.commit(); flash('Grup oluşturuldu!', 'success')
    return redirect(url_for('group_chat', group_id=group.id))

@app.route('/groups/<int:group_id>')
@login_required
def group_chat(group_id):
    group = Group.query.get_or_404(group_id)
    if not GroupMember.query.filter_by(group_id=group_id, user_id=current_user.id).first():
        flash('Bu grubun üyesi değilsiniz.', 'error'); return redirect(url_for('groups'))
    return render_template('group_chat.html', group=group)

@app.route('/api/groups/<int:group_id>/messages')
@login_required
def get_group_messages(group_id):
    msgs = GroupMessage.query.filter_by(group_id=group_id).order_by(GroupMessage.created_at.asc()).all()
    return jsonify([{
        'id': m.id, 'sender_id': m.sender_id, 'sender_name': m.sender.nickname,
        'sender_role': m.sender.role if m.sender.show_role else 'user',
        'sender_verified': m.sender.verified and m.sender.show_verified,
        'content': m.content, 'created_at': m.created_at.isoformat()
    } for m in msgs])

@app.route('/api/groups/send', methods=['POST'])
@login_required
def send_group_message():
    group_id = request.json.get('group_id')
    content = request.json.get('content','').strip()
    if not group_id or not content: return jsonify({'error': 'Eksik alanlar'}), 400
    if not GroupMember.query.filter_by(group_id=group_id, user_id=current_user.id).first():
        return jsonify({'error': 'Üye değil'}), 403
    msg = GroupMessage(group_id=group_id, sender_id=current_user.id, content=content)
    db.session.add(msg); db.session.commit()
    return jsonify({'id': msg.id, 'created_at': msg.created_at.isoformat()})

@app.route('/api/groups/<int:group_id>/add_member', methods=['POST'])
@login_required
def add_group_member(group_id):
    group = Group.query.get_or_404(group_id)
    if group.created_by != current_user.id: return jsonify({'error': 'Sadece grup sahibi üye ekleyebilir'}), 403
    user_id = request.json.get('user_id')
    if GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first(): return jsonify({'error': 'Zaten üye'}), 400
    db.session.add(GroupMember(group_id=group_id, user_id=user_id)); db.session.commit()
    return jsonify({'success': True})

@app.route('/story/upload', methods=['POST'])
@login_required
def upload_story():
    file = request.files.get('file')
    content = request.form.get('content','')
    if not file: flash('Dosya gerekli.', 'error'); return redirect(url_for('index'))
    if allowed_file(file.filename, ALLOWED_IMAGE):
        filename = save_file(file, 'stories', ALLOWED_IMAGE)
        if filename:
            story = Story(user_id=current_user.id, file_path=filename, content=content)
            db.session.add(story); db.session.commit(); flash('Hikaye yüklendi!', 'success')
    else: flash('Geçersiz dosya türü. Sadece resim.', 'error')
    return redirect(url_for('index'))

@app.route('/api/stories')
def api_stories():
    stories_query = Story.query.filter(Story.expires_at > datetime.utcnow()).order_by(Story.created_at.desc()).all()
    data = {}
    for s in stories_query:
        uid = s.user_id
        if uid not in data:
            user = User.query.get(uid)
            if not user or user.is_banned: continue
            data[uid] = {
                'user_id': uid, 'username': user.username, 'nickname': user.nickname,
                'profile_pic': user.profile_pic,
                'verified': user.verified and user.show_verified,
                'role': user.role if user.show_role else 'user',
                'stories': []
            }
        data[uid]['stories'].append({'id': s.id, 'file_path': s.file_path, 'content': s.content, 'created_at': s.created_at.isoformat()})
    return jsonify(list(data.values()))

# === NOTIFICATION ROUTES ===
@app.route('/api/notifications')
@login_required
def get_notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(50).all()
    return jsonify([{
        'id': n.id, 'type': n.type, 'message': n.message, 'link': n.link,
        'is_read': n.is_read, 'is_warning': n.is_warning,
        'created_at': n.created_at.isoformat()
    } for n in notifs])

@app.route('/api/notifications/count')
@login_required
def notification_count():
    count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return jsonify({'count': count})

@app.route('/api/notifications/read', methods=['POST'])
@login_required
def read_notifications():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'success': True})

# === ADMIN ROUTES ===
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'nobi.db')
    db_size = 0
    try: db_size = os.path.getsize(db_path)
    except: pass
    pending_videos = Video.query.filter_by(approved=False).count()
    return render_template('admin/dashboard.html',
        user_count=User.query.count(), video_count=Video.query.count(),
        pending_videos=pending_videos,
        report_count=Report.query.filter_by(resolved=False).count(),
        pending_users=User.query.filter_by(is_approved=False).count(),
        banned_count=User.query.filter_by(is_banned=True).count(),
        warn_count=Warning.query.count(),
        maintenance=is_maintenance(), db_size=db_size,
        story_count=Story.query.count(), comment_count=Comment.query.count(),
        message_count=Message.query.count(), notif_count=Notification.query.count())

@app.route('/admin/announce', methods=['POST'])
@login_required
@owner_required
def admin_announce():
    message = request.form.get('message', '').strip()
    if not message: flash('Mesaj gerekli.', 'error'); return redirect(url_for('admin_dashboard'))
    users = User.query.filter(User.deleted == False).all()
    for u in users:
        if u.id == current_user.id: continue
        n = Notification(user_id=u.id, type='announcement', message='📢 Duyuru: ' + message, is_announcement=True)
        db.session.add(n)
    db.session.commit(); flash('Duyuru tüm kullanıcılara gönderildi!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/api/report_user', methods=['POST'])
@login_required
def report_user():
    user_id = request.json.get('user_id')
    reason = request.json.get('reason', '').strip()
    if not user_id or not reason: return jsonify({'error': 'Eksik alanlar'}), 400
    target = User.query.get(user_id)
    if not target or target.deleted: return jsonify({'error': 'Kullanıcı bulunamadı'}), 404
    report = Report(reporter_id=current_user.id, content_type='user', content_id=user_id, reason=reason)
    db.session.add(report); db.session.commit()
    return jsonify({'success': True})

@app.route('/api/unban_me', methods=['POST'])
@login_required
def unban_me():
    if current_user.is_banned and current_user.banned_until and current_user.banned_until < datetime.utcnow():
        current_user.is_banned = False; current_user.ban_reason = ''; current_user.banned_until = None
        db.session.commit()
        return jsonify({'success': True, 'message': 'Banınız kalktı!'})
    return jsonify({'error': 'Ban süreniz dolmamış.'}), 400

@app.route('/admin/maintenance', methods=['POST'])
@login_required
@admin_required
def toggle_maintenance():
    if is_maintenance():
        try: os.remove(MAINTENANCE_FILE)
        except: pass
        flash('Bakım modu kapatıldı.', 'success')
    else:
        with open(MAINTENANCE_FILE, 'w') as f: f.write('1')
        flash('Bakım modu açıldı.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    status = request.args.get('status','all')
    query = User.query.order_by(User.created_at.desc())
    if status == 'pending': query = query.filter_by(is_approved=False)
    elif status == 'banned': query = query.filter_by(is_banned=True)
    elif status == 'verified': query = query.filter_by(verified=True)
    return render_template('admin/users.html', users=query.all(), status=status)

@app.route('/admin/user/<int:user_id>')
@login_required
@admin_required
def admin_user_detail(user_id):
    user = User.query.get_or_404(user_id)
    return render_template('admin/user_detail.html', user=user,
        videos=Video.query.filter_by(user_id=user.id).order_by(Video.created_at.desc()).all(),
        warnings=Warning.query.filter_by(user_id=user.id).order_by(Warning.created_at.desc()).all())

@app.route('/admin/videos')
@login_required
@admin_required
def admin_videos():
    return render_template('admin/videos.html', videos=Video.query.order_by(Video.created_at.desc()).all())

@app.route('/admin/groups')
@login_required
@admin_required
def admin_groups():
    groups = Group.query.order_by(Group.created_at.desc()).all()
    return render_template('admin/groups.html', groups=groups)

@app.route('/admin/reports')
@login_required
@admin_required
def admin_reports():
    return render_template('admin/reports.html', reports=Report.query.order_by(Report.created_at.desc()).all())

@app.route('/admin/resolve_report/<int:report_id>', methods=['POST'])
@login_required
@admin_required
def resolve_report(report_id):
    r = Report.query.get_or_404(report_id); r.resolved = True; db.session.commit(); return jsonify({'success': True})

@app.route('/admin/approve/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def approve_user(user_id):
    u = User.query.get_or_404(user_id); u.is_approved = not u.is_approved; db.session.commit(); return jsonify({'approved': u.is_approved})

@app.route('/admin/verify/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def verify_user(user_id):
    u = User.query.get_or_404(user_id); u.verified = not u.verified; db.session.commit(); return jsonify({'verified': u.verified})

@app.route('/admin/ban/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def ban_user(user_id):
    u = User.query.get_or_404(user_id)
    if u.role == 'owner': return jsonify({'error': 'Owner banlanamaz'}), 400
    reason = request.json.get('reason', 'Kurallara uymama')
    duration = request.json.get('duration', '0')
    if u.is_banned:
        u.is_banned = False; u.ban_reason = ''; u.banned_until = None
    else:
        u.is_banned = True; u.ban_reason = reason
        if duration and duration != '0':
            days = int(duration)
            u.banned_until = datetime.utcnow() + timedelta(days=days)
        else:
            u.banned_until = None
    db.session.commit(); return jsonify({'banned': u.is_banned})

@app.route('/admin/kick/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def kick_user(user_id):
    u = User.query.get_or_404(user_id)
    if u.role == 'owner': return jsonify({'error': 'Owner atılamaz'}), 400
    u.is_banned = True; u.ban_reason = 'Hesaptan atıldı'; db.session.commit(); return jsonify({'success': True})

@app.route('/admin/warn/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def warn_user(user_id):
    u = User.query.get_or_404(user_id)
    reason = request.json.get('reason','')
    if not reason: return jsonify({'error': 'Uyarı sebebi gerekli'}), 400
    warn = Warning(user_id=user_id, admin_id=current_user.id, reason=reason)
    db.session.add(warn); db.session.commit()
    add_notif(user_id, 'warning', f'⚠️ Uyarı: {reason}', '', is_warning=True)
    return jsonify({'success': True})

@app.route('/admin/backups')
@login_required
@admin_required
def admin_backups():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith('.db')], reverse=True)
    backup_info = []
    for b in backups:
        path = os.path.join(BACKUP_DIR, b)
        size = os.path.getsize(path) if os.path.exists(path) else 0
        backup_info.append({'name': b, 'size': size})
    return render_template('admin/backups.html', backups=backup_info)

@app.route('/admin/backup/create', methods=['POST'])
@login_required
@admin_required
def create_backup():
    filename = backup_database()
    if filename: flash(f'Yedek alındı: {filename}', 'success')
    else: flash('Yedek alınamadı.', 'error')
    return redirect(url_for('admin_backups'))

@app.route('/admin/backup/restore/<filename>', methods=['POST'])
@login_required
@admin_required
def restore_backup(filename):
    backup_path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(backup_path): flash('Dosya bulunamadı.', 'error'); return redirect(url_for('admin_backups'))
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'nobi.db')
    try:
        shutil.copy2(backup_path, db_path)
        flash('Yedek geri yüklendi. Sunucu yeniden başlatılıyor...', 'success')
    except: flash('Geri yükleme başarısız.', 'error')
    return redirect(url_for('admin_backups'))

@app.route('/admin/backup/delete/<filename>', methods=['POST'])
@login_required
@admin_required
def delete_backup(filename):
    backup_path = os.path.join(BACKUP_DIR, filename)
    if os.path.exists(backup_path): os.remove(backup_path)
    return redirect(url_for('admin_backups'))

@app.route('/admin/set_role/<int:user_id>', methods=['POST'])
@login_required
@owner_required
def set_role(user_id):
    u = User.query.get_or_404(user_id)
    role = request.json.get('role','user')
    if role not in ('admin','moderator','user'): return jsonify({'error': 'Geçersiz rol'}), 400
    if u.role == 'owner': return jsonify({'error': 'Owner rolü değiştirilemez'}), 400
    u.role = role
    if role in ('admin','moderator'): u.verified = True; u.is_approved = True
    db.session.commit(); return jsonify({'success': True, 'role': role})

@app.route('/admin/approve_video/<int:video_id>', methods=['POST'])
@login_required
@admin_required
def admin_approve_video(video_id):
    v = Video.query.get_or_404(video_id)
    v.approved = True; v.flagged = False; v.flag_reason = ''
    db.session.commit(); return jsonify({'success': True})

@app.route('/admin/delete_video/<int:video_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_video(video_id):
    v = Video.query.get_or_404(video_id)
    try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], 'videos', v.file_path))
    except: pass
    Bookmark.query.filter_by(video_id=video_id).delete()
    Like.query.filter_by(video_id=video_id).delete()
    Comment.query.filter_by(video_id=video_id).delete()
    db.session.delete(v); db.session.commit(); return jsonify({'success': True})

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(user_id):
    u = User.query.get_or_404(user_id)
    if u.role == 'owner': return jsonify({'error': 'Owner silinemez'}), 400
    reason = request.json.get('reason', 'Topluluk kurallarını ihlal')
    deleted = DeletedUser(username=u.username, reason=reason)
    Like.query.filter_by(user_id=u.id).delete()
    Comment.query.filter_by(user_id=u.id).delete()
    Follow.query.filter_by(follower_id=u.id).delete()
    Follow.query.filter_by(followed_id=u.id).delete()
    Message.query.filter_by(sender_id=u.id).delete()
    Message.query.filter_by(receiver_id=u.id).delete()
    Warning.query.filter_by(user_id=u.id).delete()
    Warning.query.filter_by(admin_id=u.id).delete()
    GroupMember.query.filter_by(user_id=u.id).delete()
    GroupMessage.query.filter_by(sender_id=u.id).delete()
    Report.query.filter_by(reporter_id=u.id).delete()
    Notification.query.filter_by(user_id=u.id).delete()
    Video.query.filter_by(user_id=u.id).delete()
    Story.query.filter_by(user_id=u.id).delete()
    Bookmark.query.filter_by(user_id=u.id).delete()
    db.session.delete(u)
    db.session.add(deleted)
    db.session.commit(); return jsonify({'success': True})

@app.route('/admin/delete_group/<int:group_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_group(group_id):
    g = Group.query.get_or_404(group_id)
    db.session.delete(g); db.session.commit(); return jsonify({'success': True})

def stream_video(file_path):
    if not os.path.exists(file_path):
        abort(404)
    size = os.path.getsize(file_path)
    range_header = request.headers.get('Range')
    if not range_header:
        resp = app.response_class(open(file_path, 'rb'), 200, mimetype='video/mp4', direct_passthrough=True)
        resp.headers['Content-Length'] = size
        resp.headers['Accept-Ranges'] = 'bytes'
        return resp
    match = re.search(r'bytes=(\d+)-(\d*)', range_header)
    start = int(match.group(1)) if match and match.group(1) else 0
    end = int(match.group(2)) if match and match.group(2) else size - 1
    length = end - start + 1
    def gen():
        with open(file_path, 'rb') as f:
            f.seek(start)
            left = length
            first = True
            while left > 0:
                chunk_size = 524288 if first else 262144
                if chunk_size > left: chunk_size = left
                chunk = f.read(chunk_size)
                if not chunk: break
                left -= len(chunk)
                first = False
                yield chunk
    resp = app.response_class(gen(), 206, mimetype='video/mp4', direct_passthrough=True)
    resp.headers['Content-Range'] = f'bytes {start}-{end}/{size}'
    resp.headers['Accept-Ranges'] = 'bytes'
    resp.headers['Content-Length'] = length
    return resp

MIMES = {
    'mp4': 'video/mp4', 'webm': 'video/webm', 'mov': 'video/quicktime', 'avi': 'video/x-msvideo',
    'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif', 'webp': 'image/webp'
}

@app.route('/uploads/<subdir>/<filename>')
def uploaded_file(subdir, filename):
    fp = os.path.join(app.config['UPLOAD_FOLDER'], subdir, filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext in ('jpg','jpeg','png','gif','webp'):
        return send_from_directory(os.path.join(app.config['UPLOAD_FOLDER'], subdir), filename)
    resp = stream_video(fp)
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp

@app.route('/uploads/<filename>')
def upload_root(filename):
    fp = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    for d in ['videos', 'images', 'profile_pics', 'stories']:
        p = os.path.join(app.config['UPLOAD_FOLDER'], d)
        os.makedirs(p, exist_ok=True)
    backup_database()
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(role='owner').first():
            owner = User(email='admin@nobi.com', username='admin', nickname='Admin',
                        password_hash=generate_password_hash('admin123'),
                        role='owner', verified=True, is_approved=True)
            db.session.add(owner); db.session.commit()
    app.run(debug=True, host='0.0.0.0', port=3000)
