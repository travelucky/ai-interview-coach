import os

from app import create_app


app = create_app()


if __name__ == '__main__':
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '5001'))
    debug = app.config.get('DEBUG', False)
    print(f'AI 模拟面试系统: http://{host}:{port}')
    app.run(host=host, port=port, debug=debug)
