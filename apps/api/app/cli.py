"""
CLI for the RevOps Lead Scoring Platform.

Usage:
    python -m app.cli ingest --source-dir data/raw/
    python -m app.cli build-views
    python -m app.cli score-leads
    python -m app.cli export-daily-list --top-n 50 --out data/processed/daily_top_50.csv
    python -m app.cli sync-hubspot --csv data/processed/daily_top_50.csv
    python -m app.cli seed
"""

from __future__ import annotations

import csv
import uuid
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="RevOps Lead Scoring CLI", no_args_is_help=True)
console = Console()


def _get_db():
    from app.database import SessionLocal

    return SessionLocal()


_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: object) -> str:
    """A cell value that a spreadsheet will show as text: one that starts like a formula gets a leading apostrophe (names and emails come from CRMs)."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_STARTS) else text


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------


@app.command("ingest")
def ingest(
    source_dir: Path = typer.Option(..., "--source-dir", help="Directory containing raw CSV/JSON files"),
    batch_size: int = typer.Option(500, "--batch-size"),
):
    """Ingest raw files from a local directory into the raw_events table."""
    import json

    from app.models.ingestion import RawEvent

    db = _get_db()
    files = list(source_dir.glob("**/*.json")) + list(source_dir.glob("**/*.csv"))
    if not files:
        console.print(f"[yellow]No files found in {source_dir}[/yellow]")
        raise typer.Exit(1)

    total = 0
    for fpath in files:
        console.print(f"Processing [cyan]{fpath.name}[/cyan]...")
        if fpath.suffix == ".json":
            records = json.loads(fpath.read_text())
            if isinstance(records, dict):
                records = [records]
        else:
            with fpath.open() as f:
                records = list(csv.DictReader(f))

        batch = []
        for rec in records:
            ev = RawEvent(
                id=str(uuid.uuid4()),
                source_system=rec.get("source_system", "csv"),
                source_record_id=rec.get("source_record_id", rec.get("id", str(uuid.uuid4()))),
                operation=rec.get("operation", "insert"),
                schema_version=int(rec.get("schema_version", 1)),
                raw_payload=rec if isinstance(rec, dict) else dict(rec),
                ingested_at=datetime.now(UTC),
            )
            batch.append(ev)
            if len(batch) >= batch_size:
                db.add_all(batch)
                db.commit()
                total += len(batch)
                batch = []

        if batch:
            db.add_all(batch)
            db.commit()
            total += len(batch)

    db.close()
    console.print(f"[green]Ingested {total} records.[/green]")


# ---------------------------------------------------------------------------
# build-views
# ---------------------------------------------------------------------------


@app.command("build-views")
def build_views():
    """Trigger incremental feature recompute for all contacts with unprocessed events."""
    try:
        from workers.tasks.features import recompute_all_features

        result = recompute_all_features.delay()
        console.print(f"[green]Feature recompute task dispatched. Task ID: {result.id}[/green]")
    except Exception as e:
        console.print(f"[yellow]Celery unavailable — running synchronously. Error: {e}[/yellow]")
        _sync_build_views()


def _sync_build_views():
    from sqlalchemy import select

    from app.models.contact import Contact, ContactFeature

    db = _get_db()
    contacts = db.scalars(select(Contact)).all()
    console.print(f"Recomputing features for {len(contacts)} contacts...")
    # In production this would run incremental SQL aggregations.
    # Here we ensure every contact has a features row.
    for contact in contacts:
        if not contact.features:
            feat = ContactFeature(id=str(uuid.uuid4()), contact_id=contact.id)
            db.add(feat)
    db.commit()
    db.close()
    console.print("[green]Feature rows seeded.[/green]")


# ---------------------------------------------------------------------------
# score-leads
# ---------------------------------------------------------------------------


@app.command("score-leads")
def score_leads(
    model_version: str = typer.Option("", "--model-version"),
    segment: str | None = typer.Option(None, "--segment"),
    batch_size: int = typer.Option(500, "--batch-size"),
    shadow: bool = typer.Option(False, "--shadow"),
):
    """Run a full scoring pass over all contacts."""
    from sqlalchemy import select

    from app.config import get_settings
    from app.models.contact import Contact
    from app.models.scoring import ScoringRun, ScoringRunStatus
    from app.services.lead_scoring import feature_vector, latest_live_score, new_score
    from app.services.scoring_engine import score_contact
    from app.services.webhook_service import notify_score_change

    settings = get_settings()
    mv = model_version or settings.scoring_model_version
    db = _get_db()

    run = ScoringRun(
        id=str(uuid.uuid4()),
        model_version=mv,
        status=ScoringRunStatus.RUNNING,
        filter_segment=segment,
        is_shadow=shadow,
        triggered_by="cli",
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()

    q = select(Contact)
    if segment:
        from app.models.company import Company

        q = q.join(Company, Contact.company_id == Company.id).where(Company.size_tier == segment)

    contacts = db.scalars(q).all()
    run.total_contacts = len(contacts)
    db.commit()

    scored = 0
    errors = 0

    for i in range(0, len(contacts), batch_size):
        chunk = contacts[i : i + batch_size]
        scores = []
        changes = []  # what the subscribers are told about once these scores are saved
        for contact in chunk:
            try:
                fv = feature_vector(contact)
                previous = latest_live_score(db, contact.id)
                score = new_score(contact, fv, score_contact(fv), run_id=run.id, is_shadow=shadow)
                scores.append(score)
                changes.append((contact, previous, score, fv.demo_requested))
                scored += 1
            except Exception as e:
                errors += 1
                console.print(f"[red]Error scoring {contact.id}: {e}[/red]")

        db.add_all(scores)
        db.commit()
        if not shadow:
            for contact, previous, score, demo_requested in changes:
                notify_score_change(db, contact, previous, score, demo_requested)
        console.print(f"  Scored {min(i + batch_size, len(contacts))}/{len(contacts)}...")

    end = datetime.now(UTC)
    run.status = ScoringRunStatus.COMPLETED if errors == 0 else ScoringRunStatus.PARTIAL
    run.scored_count = scored
    run.error_count = errors
    run.completed_at = end
    run.duration_seconds = (end - run.started_at).total_seconds()
    db.commit()
    db.close()

    console.print(
        f"[green]Scoring complete: {scored} scored, {errors} errors. Duration: {run.duration_seconds:.1f}s[/green]"
    )


# ---------------------------------------------------------------------------
# export-daily-list
# ---------------------------------------------------------------------------


@app.command("export-daily-list")
def export_daily_list(
    top_n: int = typer.Option(50, "--top-n"),
    out: Path = typer.Option(Path("data/processed/daily_top.csv"), "--out"),
    tier: str | None = typer.Option(None, "--tier", help="Filter by priority tier"),
):
    """Export the top N ranked leads to CSV."""
    from sqlalchemy import func, select

    from app.models.company import Company
    from app.models.contact import Contact
    from app.models.scoring import LeadScore

    db = _get_db()
    latest = (
        select(LeadScore.contact_id, func.max(LeadScore.scored_at).label("max_scored_at"))
        .where(LeadScore.is_shadow == False)  # noqa: E712
        .group_by(LeadScore.contact_id)
        .subquery()
    )
    q = (
        select(LeadScore, Contact, Company)
        .join(latest, (LeadScore.contact_id == latest.c.contact_id) & (LeadScore.scored_at == latest.c.max_scored_at))
        .join(Contact, LeadScore.contact_id == Contact.id)
        .outerjoin(Company, Contact.company_id == Company.id)
        .where(LeadScore.is_shadow == False)  # noqa: E712
        .order_by(LeadScore.lead_score.desc())
        .limit(top_n)
    )
    if tier:
        q = q.where(LeadScore.priority_tier == tier.upper())

    rows = db.execute(q).all()
    db.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "contact_id",
                "email",
                "full_name",
                "company",
                "lead_score",
                "priority_tier",
                "score_reason",
                "recommended_action",
                "model_version",
                "scored_at",
            ],
        )
        writer.writeheader()
        for score, contact, company in rows:
            writer.writerow(
                {
                    "contact_id": contact.id,
                    "email": csv_safe(contact.email),
                    "full_name": csv_safe(contact.full_name),
                    "company": csv_safe(company.name if company else ""),
                    "lead_score": score.lead_score,
                    "priority_tier": score.priority_tier,
                    "score_reason": csv_safe(score.score_reason),
                    "recommended_action": csv_safe(score.recommended_action),
                    "model_version": score.model_version,
                    "scored_at": score.scored_at.isoformat(),
                }
            )

    console.print(f"[green]Exported {len(rows)} leads to {out}[/green]")

    # Display table
    table = Table(title=f"Top {top_n} Leads")
    table.add_column("Email", style="cyan")
    table.add_column("Company")
    table.add_column("Score", justify="right")
    table.add_column("Tier")
    for score, contact, company in rows[:10]:
        table.add_row(contact.email, company.name if company else "—", str(score.lead_score), score.priority_tier)
    if len(rows) > 10:
        table.add_row("...", "...", "...", "...")
    console.print(table)


# ---------------------------------------------------------------------------
# sync-hubspot
# ---------------------------------------------------------------------------


@app.command("sync-hubspot")
def sync_hubspot(
    csv_file: Path = typer.Option(..., "--csv"),
):
    """Sync leads from a CSV file to HubSpot."""
    from app.services.crm_sync import sync_batch_to_hubspot

    with csv_file.open() as f:
        contacts = list(csv.DictReader(f))

    console.print(f"Syncing {len(contacts)} contacts to HubSpot...")
    success, failure = sync_batch_to_hubspot(contacts, db_session=None)
    console.print(f"[green]Sync complete: {success} success, {failure} failed[/green]")


# ---------------------------------------------------------------------------
# seed
# ---------------------------------------------------------------------------


@app.command("seed")
def seed(count: int = typer.Option(100, "--count", help="Number of fake contacts to generate")):
    """Seed the database with synthetic data for local development."""
    try:
        from faker import Faker
    except ImportError:
        console.print("[red]faker not installed. Run: uv sync --group dev[/red]")
        raise typer.Exit(1) from None

    from app.auth.jwt import hash_password
    from app.config import get_settings
    from app.models.company import Company
    from app.models.contact import Contact, ContactFeature
    from app.models.user import User

    settings = get_settings()
    fake = Faker()
    db = _get_db()

    # Admin user
    if not db.query(User).filter_by(email=settings.admin_email).first():
        db.add(
            User(
                id=str(uuid.uuid4()),
                email=settings.admin_email,
                hashed_password=hash_password(settings.admin_password),
                full_name="Admin User",
                role="admin",
            )
        )
        db.commit()
        console.print(f"[green]Admin user created: {settings.admin_email}[/green]")

    # Companies
    companies = []
    tiers = ["smb", "mid_market", "enterprise"]
    for _ in range(count // 5):
        co = Company(
            id=str(uuid.uuid4()),
            source_system="seed",
            source_record_id=str(uuid.uuid4()),
            name=fake.company(),
            domain=fake.domain_name(),
            industry=fake.bs().split()[0],
            employee_count=fake.random_int(10, 10000),
            size_tier=fake.random_element(tiers),
            country=fake.country_code(),
        )
        companies.append(co)
    db.add_all(companies)
    db.commit()

    # Contacts + features
    for _ in range(count):
        company = fake.random_element(companies) if companies else None
        contact = Contact(
            id=str(uuid.uuid4()),
            source_system="seed",
            source_record_id=str(uuid.uuid4()),
            email=fake.unique.email(),
            first_name=fake.first_name(),
            last_name=fake.last_name(),
            job_title=fake.job(),
            company_id=company.id if company else None,
            lifecycle_stage=fake.random_element(
                ["subscriber", "lead", "marketing_qualified_lead", "sales_qualified_lead"]
            ),
        )
        db.add(contact)
        db.flush()
        feat = ContactFeature(
            id=str(uuid.uuid4()),
            contact_id=contact.id,
            api_calls_7d=fake.random_int(0, 100),
            api_calls_30d=fake.random_int(0, 400),
            page_views_7d=fake.random_int(0, 50),
            pricing_page_visited=fake.boolean(chance_of_getting_true=20),
            email_opens_7d=fake.random_int(0, 10),
            email_clicks_7d=fake.random_int(0, 5),
            demo_requested=fake.boolean(chance_of_getting_true=10),
            free_trial_active=fake.boolean(chance_of_getting_true=15),
            integration_connected=fake.boolean(chance_of_getting_true=25),
            integrations_count=fake.random_int(0, 5),
            days_since_last_activity=fake.random_int(0, 90),
        )
        db.add(feat)

    db.commit()
    db.close()
    console.print(f"[green]Seeded {count} contacts with features.[/green]")


if __name__ == "__main__":
    app()


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------


@app.command("set-password")
def set_password(
    email: str = typer.Option(..., "--email", help="The user's email address"),
    password: str = typer.Option(
        ..., prompt="New password", hide_input=True, confirmation_prompt=True, help="Asked for, twice, and not echoed"
    ),
):
    """Set a user's password. There is no password-change endpoint, so this is how an admin's password is changed (run it where the database is reachable)."""
    from sqlalchemy import func

    from app.auth.jwt import hash_password
    from app.models.user import User
    from app.schemas.auth import validate_password

    try:
        validate_password(password)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None

    db = _get_db()
    try:
        user = db.query(User).filter(func.lower(User.email) == email.strip().lower()).first()
        if user is None:
            console.print(f"[red]No user with the email {email.strip()}[/red]")
            raise typer.Exit(1)
        address = user.email
        user.hashed_password = hash_password(password)
        db.commit()
    finally:
        db.close()
    console.print(f"[green]Password set for {address}.[/green]")
    console.print("Sign-ins that already exist stay valid until they expire; change JWT_SECRET_KEY to end them all.")
