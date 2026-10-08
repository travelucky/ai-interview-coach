                       
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    from app import create_app, db
    from sqlalchemy import text

    app = create_app()
    with app.app_context():
                                                    
        uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if not uri.startswith('sqlite'):
            print('当前仅支持 SQLite 数据库，跳过。')
            return
        try:
            r = db.session.execute(text('PRAGMA table_info(position)')).fetchall()
                                                                   
            columns = [row[1] for row in r]
            if 'sort_order' not in columns:
                print('position 表已无 sort_order 列，无需迁移。')
                return
            db.session.execute(text('ALTER TABLE position DROP COLUMN sort_order'))
            db.session.commit()
            print('已从 position 表删除 sort_order 列。')
        except Exception as e:
            db.session.rollback()
            print('迁移失败:', e)
            sys.exit(1)


if __name__ == '__main__':
    main()
