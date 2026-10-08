                       
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def main():
    from app import create_app
    from sqlalchemy import text
    app = create_app()
    with app.app_context():
        from app import db
        bind = db.session.get_bind()
        if bind.dialect.name != 'sqlite':
            print('仅支持 SQLite，跳过。')
            return
        try:
            result = db.session.execute(text('PRAGMA table_info(interview_session)'))
            cols = [row[1] for row in result.fetchall()]
            if 'interview_state' in cols:
                print('interview_state 列已存在，跳过。')
                return
            db.session.execute(text('ALTER TABLE interview_session ADD COLUMN interview_state TEXT'))
            db.session.commit()
            print('已添加 interview_session.interview_state 列。')
        except Exception as e:
            print('执行失败:', e)
            db.session.rollback()

if __name__ == '__main__':
    main()
