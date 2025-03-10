from werkzeug.security import generate_password_hash
from terminaltables import AsciiTable


from director.context import pass_ctx
from director.exceptions import UserNotFound
from director.models.users import User
from director.extensions import db_engine
from sqlalchemy.orm import Session

import click


def _get_users():
    return User.query.all()


@click.group()
def user():
    """Manage the users"""


@user.command(name="list")
@pass_ctx
def list_users(ctx):
    """Display users"""
    data = [["Username"]]
    users = _get_users()

    for user in users:
        data.append([user.username])

    table = AsciiTable(data)
    table.inner_row_border = True
    click.echo(table.table)


@user.command(name="create")
@click.argument("username")
@click.password_option()
@pass_ctx
def create_user(ctx, username, password):
    """Create user"""
    user = User(username=username, password=generate_password_hash(password))
    db_session = db_engine.get_db_session()
    with db_session() as session:
        user.save(session)
        session.commit()


@user.command(name="update")
@click.argument("username")
@click.password_option()
@pass_ctx
def update_user(ctx, username, password):
    """Update user"""
    user = User(username=username, password=generate_password_hash(password))
    try:
        db_session = db_engine.get_db_session()
        with db_session() as session:
            user.update(session)
    except UserNotFound as e:
        click.echo(str(e))


@user.command(name="delete")
@click.argument("username")
@pass_ctx
def delete_user(ctx, username):
    """delete user"""
    db_session = db_engine.get_db_session()
    with db_session() as session:
        user = session.query(User).filter_by(username=username).first()
        if not user:
            click.echo(f"User {username} not found")
            return
        user.delete(session)
