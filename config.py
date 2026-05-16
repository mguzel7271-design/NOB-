import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'nobi-secret-key-2024'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///nobi.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
    MAX_CONTENT_LENGTH = 1024 * 1024 * 1024
    STORY_EXPIRE_DAYS = 2
    RECAPTCHA_SITE_KEY = '6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI'
    RECAPTCHA_SECRET_KEY = '6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe'
