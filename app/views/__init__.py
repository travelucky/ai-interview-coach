                       
from flask import Blueprint, render_template, redirect, url_for

bp = Blueprint('views', __name__, template_folder='../templates')


@bp.route('/')
def index():
    return redirect(url_for('views.login'))


@bp.route('/login')
def login():
    return render_template('login.html')


@bp.route('/admin')
def admin():
    return render_template('admin.html')


@bp.route('/user')
def user():
    return render_template('user.html')
