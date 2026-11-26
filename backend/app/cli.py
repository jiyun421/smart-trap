import sqlite3
from contextlib import contextmanager

import click
from flask import current_app
from flask.cli import with_appcontext

from .db import apply_migrations, get_db, require_id, transaction
from .validation import ApiError, identifier, invalid, nonempty_text, number, timestamp


@click.command("migrate")
@with_appcontext
def migrate_command():
    """Apply all SQLite migrations."""
    try:
        apply_migrations(current_app.config["DB_PATH"])
    except (OSError, RuntimeError, sqlite3.Error) as error:
        raise click.ClickException(str(error)) from error
    click.echo("Database migrations are up to date.")


@click.group("registry")
@with_appcontext
def registry():
    """Register traps, locations, and deployments."""


@registry.command("trap")
@click.argument("trap_id")
@click.argument("name")
@click.option("--empty-g", type=float, required=True)
@click.option("--low-g", type=float, required=True)
@click.option("--interval", type=click.IntRange(1, 86400), required=True)
def register_trap(trap_id, name, empty_g, low_g, interval):
    with registry_transaction() as connection:
        trap_id = identifier(trap_id, "trap_id")
        name = nonempty_text(name, "name", 200)
        empty_g = number(empty_g, "empty_g", 0)
        low_g = number(low_g, "low_g", 0)
        if empty_g >= low_g:
            raise invalid("empty_g must be smaller than low_g")
        connection.execute("INSERT INTO traps VALUES (?, ?, ?, ?, ?)", (trap_id, name, empty_g, low_g, interval))
    click.echo(f"Registered trap {trap_id}")


@registry.command("location")
@click.argument("location_id")
@click.argument("name")
@click.option("--latitude", type=float)
@click.option("--longitude", type=float)
@click.option("--notes")
def register_location(location_id, name, latitude, longitude, notes):
    with registry_transaction() as connection:
        location_id = identifier(location_id, "location_id")
        name = nonempty_text(name, "name", 200)
        latitude = number(latitude, "latitude", -90, 90) if latitude is not None else None
        longitude = number(longitude, "longitude", -180, 180) if longitude is not None else None
        notes = nonempty_text(notes, "notes", 2000) if notes is not None else None
        connection.execute("INSERT INTO locations VALUES (?, ?, ?, ?, ?)", (location_id, name, latitude, longitude, notes))
    click.echo(f"Registered location {location_id}")


@registry.command("deploy")
@click.argument("deployment_id")
@click.argument("trap_id")
@click.argument("location_id")
@click.argument("target_species")
@click.argument("started_at")
def register_deployment(deployment_id, trap_id, location_id, target_species, started_at):
    with registry_transaction() as connection:
        deployment_id = identifier(deployment_id, "deployment_id")
        trap_id = identifier(trap_id, "trap_id")
        location_id = identifier(location_id, "location_id")
        target_species = identifier(target_species, "target_species")
        if target_species == "unknown":
            raise invalid("target_species must be a known species code")
        started_at = timestamp(started_at, "started_at")
        require_id(connection, "traps", "trap_id", trap_id)
        require_id(connection, "locations", "location_id", location_id)
        previous = connection.execute(
            "SELECT * FROM deployments WHERE trap_id = ? ORDER BY started_at DESC LIMIT 1", (trap_id,)
        ).fetchone()
        if previous is not None:
            if started_at <= previous["started_at"] or (previous["ended_at"] and started_at < previous["ended_at"]):
                raise invalid("The new deployment overlaps a previous deployment")
            if previous["ended_at"] is None:
                latest = connection.execute(
                    "SELECT MAX(observed_at) FROM trap_events WHERE deployment_id = ?", (previous["deployment_id"],)
                ).fetchone()[0]
                if latest and latest >= started_at:
                    raise invalid("The new deployment must start after the previous deployment's latest recorded event")
                connection.execute(
                    "UPDATE deployments SET ended_at = ? WHERE deployment_id = ?",
                    (started_at, previous["deployment_id"]),
                )
        connection.execute(
            "INSERT INTO deployments (deployment_id, trap_id, location_id, target_species, started_at) VALUES (?, ?, ?, ?, ?)",
            (deployment_id, trap_id, location_id, target_species, started_at),
        )
    click.echo(f"Registered deployment {deployment_id}")


@contextmanager
def registry_transaction():
    try:
        connection = get_db()
        with transaction(connection, write=True):
            yield connection
    except (ApiError, sqlite3.Error) as error:
        raise click.ClickException(str(error)) from error


def setup_cli(app):
    app.cli.add_command(migrate_command)
    app.cli.add_command(registry)
