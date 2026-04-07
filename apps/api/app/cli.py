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
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="RevOps Lead Scoring CLI", no_args_is_help=True)
console = Console()


def _get_db():
    from app.database import SessionLocal
    return SessionLocal()


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

@app.command("ingest")
def ingest(
    source_dir: Path = typer.Option(..., "--source-dir", help="Directory containing raw CSV/JSON files"),
    batch_size: int = typer.Option(500, "--batch-size"),
):
    """Ingest raw files from a local directory into the raw_events table."""
    from app.models.ingestion import RawEvent
    import json

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
                ingested_at=datetime.now(timezone.utc),
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
    from app.models.ingestion import RawEvent

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
    from app.models.contact import Contact, ContactFeature
    from app.models.scoring import LeadScore, ScoringRun, ScoringRunStatus
    from app.services.scoring_engine import FeatureVector, score_contact, SCORE_CONFIG
    from app.config import get_settings

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
        started_at=datetime.now(timezone.utc),
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
        for contact in chunk:
            try:
                f = contact.features
                fv = FeatureVector(
                    api_calls_7d=f.api_calls_7d if f else 0,
                    api_calls_30d=f.api_calls_30d if f else 0,
                    page_views_7d=f.page_views_7d if f else 0,
                    pricing_page_visited=f.pricing_page_visited if f else False,
                    email_opens_7d=f.email_opens_7d if f else 0,
                    email_clicks_7d=f.email_clicks_7d if f else 0,
                    docs_page_visits_7d=f.docs_page_visits_7d if f else 0,
                    demo_requested=f.demo_requested if f else False,
                    free_trial_active=f.free_trial_active if f else False,
                    integration_connected=f.integration_connected if f else False,
                    integrations_count=f.integrations_count if f else 0,
                    sessions_7d=f.sessions_7d if f else 0,
                    days_since_last_activity=f.days_since_last_activity if f else 999,
                )
                result = score_contact(fv)
                score = LeadScore(
                    id=str(uuid.uuid4()),
                    contact_id=contact.id,
                    company_id=contact.company_id,
                    scoring_run_id=run.id,
                    lead_score=result.lead_score,
                    priority_tier=result.priority_tier,
                    model_version=result.model_version,
                    score_reason=result.score_reason,
                    feature_contributions=result.feature_contributions,
                    recommended_action=result.recommended_action,
                    is_shadow=shadow,
                    scored_at=datetime.now(timezone.utc),
                    feature_freshness_at=f.computed_at if f else None,
                )
                scores.append(score)
                scored += 1
            except Exception as e:
                errors += 1
                console.print(f"[red]Error scoring {contact.id}: {e}[/red]")

        db.add_all(scores)
        db.commit()
        console.print(f"  Scored {min(i + batch_size, len(contacts))}/{len(contacts)}...")

    end = datetime.now(timezone.utc)
    run.status = ScoringRunStatus.COMPLETED if errors == 0 else ScoringRunStatus.PARTIAL
    run.scored_count = scored
    run.error_count = errors
    run.completed_at = end
    run.duration_seconds = (end - run.started_at).total_seconds()
    db.commit()
    db.close()

    console.print(f"[green]Scoring complete: {scored} scored, {errors} errors. Duration: {run.duration_seconds:.1f}s[/green]")


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
    from app.models.contact import Contact
    from app.models.company import Company
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
            fieldnames=["contact_id", "email", "full_name", "company", "lead_score", "priority_tier",
                        "score_reason", "recommended_action", "model_version", "scored_at"],
        )
        writer.writeheader()
        for score, contact, company in rows:
            writer.writerow({
                "contact_id": contact.id,
                "email": contact.email,
                "full_name": contact.full_name,
                "company": company.name if company else "",
                "lead_score": score.lead_score,
                "priority_tier": score.priority_tier,
                "score_reason": score.score_reason or "",
                "recommended_action": score.recommended_action or "",
                "model_version": score.model_version,
                "scored_at": score.scored_at.isoformat(),
            })

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
        console.print("[red]faker not installed. Run: pip install faker[/red]")
        raise typer.Exit(1)

    from app.models.company import Company
    from app.models.contact import Contact, ContactFeature
    from app.auth.jwt import hash_password
    from app.models.user import User
    from app.config import get_settings

    settings = get_settings()
    fake = Faker()
    db = _get_db()

    # Admin user
    if not db.query(User).filter_by(email=settings.admin_email).first():
        db.add(User(
            id=str(uuid.uuid4()),
            email=settings.admin_email,
            hashed_password=hash_password(settings.admin_password),
            full_name="Admin User",
            role="admin",
        ))
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
    for i in range(count):
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
            lifecycle_stage=fake.random_element(["subscriber", "lead", "marketing_qualified_lead", "sales_qualified_lead"]),
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
