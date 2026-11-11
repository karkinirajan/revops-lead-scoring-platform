import csv
import json

import pytest
from typer.testing import CliRunner

from app import cli
from app.auth import jwt as tokens
from app.models.company import Company
from app.models.contact import Contact, ContactFeature
from app.models.ingestion import RawEvent
from app.models.scoring import LeadScore, ScoringRun
from app.models.user import User
from tests.conftest import BorrowedSession

runner = CliRunner()


@pytest.fixture()
def run(worker_db, monkeypatch):
    monkeypatch.setattr(cli, "_get_db", lambda: BorrowedSession(worker_db))

    def invoke(*args):
        return runner.invoke(cli.app, list(args))

    return invoke


class TestCsvSafe:
    @pytest.mark.parametrize("value", ['=HYPERLINK("http://evil")', "+1+1", "-2+3", "@SUM(A1)", "\tcmd", "\rcmd"])
    def test_values_that_look_like_formulas_become_text(self, value):
        assert cli.csv_safe(value) == "'" + value

    @pytest.mark.parametrize("value", ["Ada Lovelace", "ada@example.com", "a=b", "5", "", "Acme - Corp"])
    def test_ordinary_values_are_unchanged(self, value):
        assert cli.csv_safe(value) == value

    def test_none_is_empty_and_numbers_are_text(self):
        assert cli.csv_safe(None) == "" and cli.csv_safe(42) == "42"


class TestIngest:
    def test_json_and_csv_files_become_raw_events(self, run, worker_db, tmp_path):
        (tmp_path / "a.json").write_text(
            json.dumps([{"source_record_id": "j1", "email": "j1@example.com"}, {"id": "j2", "email": "j2@example.com"}])
        )
        (tmp_path / "b.json").write_text(json.dumps({"source_record_id": "single", "email": "s@example.com"}))
        (tmp_path / "c.csv").write_text("id,email\nc1,c1@example.com\nc2,c2@example.com\n")
        result = run("ingest", "--source-dir", str(tmp_path))
        assert result.exit_code == 0, result.output
        ids = {e.source_record_id for e in worker_db.query(RawEvent)}
        assert ids == {"j1", "j2", "single", "c1", "c2"}

    def test_an_empty_folder_is_an_error(self, run, tmp_path):
        result = run("ingest", "--source-dir", str(tmp_path))
        assert result.exit_code == 1 and "No files found" in result.output


class TestSeedScoreExport:
    def test_seed_creates_contacts_features_and_an_admin(self, run, worker_db):
        result = run("seed", "--count", "6")
        assert result.exit_code == 0, result.output
        assert (
            worker_db.query(Contact).count() == 6
            and worker_db.query(ContactFeature).count() == 6
            and worker_db.query(Company).count() > 0
        )
        assert worker_db.query(User).filter_by(role="admin").count() == 1

    def test_seeding_twice_does_not_duplicate_the_admin(self, run, worker_db):
        run("seed", "--count", "2")
        run("seed", "--count", "2")
        assert worker_db.query(User).filter_by(role="admin").count() == 1

    def test_scoring_scores_every_contact_and_records_a_completed_run(self, run, worker_db):
        run("seed", "--count", "8")
        result = run("score-leads")
        assert result.exit_code == 0, result.output
        scores = worker_db.query(LeadScore).all()
        assert len(scores) == 8 and all(0 <= s.lead_score <= 100 and not s.is_shadow for s in scores)
        scoring_run = worker_db.query(ScoringRun).one()
        assert (scoring_run.status, scoring_run.scored_count, scoring_run.error_count, scoring_run.total_contacts) == (
            "completed",
            8,
            0,
            8,
        )

    def test_shadow_scoring_marks_its_scores(self, run, worker_db):
        run("seed", "--count", "3")
        run("score-leads", "--shadow")
        assert {s.is_shadow for s in worker_db.query(LeadScore)} == {True}

    def test_the_export_is_a_ranked_csv(self, run, worker_db, tmp_path):
        run("seed", "--count", "12")
        run("score-leads")
        out = tmp_path / "top.csv"
        result = run("export-daily-list", "--top-n", "5", "--out", str(out))
        assert result.exit_code == 0, result.output
        rows = list(csv.DictReader(out.open()))
        assert len(rows) == 5 and [int(r["lead_score"]) for r in rows] == sorted(
            (int(r["lead_score"]) for r in rows), reverse=True
        )
        assert list(rows[0]) == [
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
        ]

    def test_the_export_can_be_limited_to_a_tier(self, run, worker_db, tmp_path, make_contact):
        make_contact(email="hot@example.com", score=90, tier="HOT")
        make_contact(email="cold@example.com", score=5, tier="COLD")
        out = tmp_path / "hot.csv"
        run("export-daily-list", "--tier", "hot", "--out", str(out))
        assert [r["email"] for r in csv.DictReader(out.open())] == ["hot@example.com"]

    def test_the_export_does_not_let_a_crm_value_run_as_a_formula(self, run, worker_db, tmp_path, make_contact):
        make_contact(
            email="=cmd|' /C calc'!A0@example.com",
            first_name='=HYPERLINK("http://evil.test","click")',
            score=90,
            tier="HOT",
            company={"name": "+SUM(1,1)"},
        )
        out = tmp_path / "out.csv"
        run("export-daily-list", "--out", str(out))
        row = next(csv.DictReader(out.open()))
        assert row["email"].startswith("'=") and row["full_name"].startswith("'=") and row["company"].startswith("'+")

    def test_the_export_ignores_newer_shadow_scores(self, run, worker_db, tmp_path, make_contact):
        from datetime import timedelta

        contact = make_contact(email="a@example.com", score=60, tier="WARM")
        live = worker_db.query(LeadScore).one()
        worker_db.add(
            LeadScore(
                contact_id=contact.id,
                lead_score=99,
                priority_tier="HOT",
                model_version="2",
                is_shadow=True,
                scored_at=live.scored_at + timedelta(hours=1),
            )
        )
        worker_db.commit()
        out = tmp_path / "out.csv"
        run("export-daily-list", "--out", str(out))
        assert [r["lead_score"] for r in csv.DictReader(out.open())] == ["60"]


class TestSyncHubspot:
    def test_a_csv_is_pushed(self, run, tmp_path, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            "app.services.crm_sync.sync_batch_to_hubspot",
            lambda contacts, db_session=None: seen.update(n=len(contacts)) or (len(contacts), 0),
        )
        path = tmp_path / "leads.csv"
        path.write_text("email,lead_score\na@example.com,90\nb@example.com,80\n")
        result = run("sync-hubspot", "--csv", str(path))
        assert result.exit_code == 0 and seen == {"n": 2} and "2 success, 0 failed" in result.output


class TestSetPassword:
    NEW = "a-brand-new-password"

    def invoke(self, run, *args, answers=None):
        """`run` makes the command use the test's session; the passwords are typed at the prompt, as they would be."""
        typed = f"{self.NEW}\n{self.NEW}\n" if answers is None else answers
        return runner.invoke(cli.app, ["set-password", *args], input=typed)

    def test_it_sets_the_password_and_the_user_can_sign_in_with_it(self, run, worker_db, make_user, client):
        user = make_user(email="ada@example.com", password="the-old-password")
        result = self.invoke(run, "--email", "ada@example.com")
        assert result.exit_code == 0, result.output
        worker_db.rollback()  # what was not committed would be lost here
        worker_db.refresh(user)
        assert tokens.verify_password(self.NEW, user.hashed_password)
        assert not tokens.verify_password("the-old-password", user.hashed_password)
        assert (
            client.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": self.NEW}).status_code
            == 200
        )
        assert (
            client.post(
                "/api/v1/auth/login", json={"email": "ada@example.com", "password": "the-old-password"}
            ).status_code
            == 401
        )

    def test_the_email_is_matched_without_regard_to_case_or_spaces(self, run, worker_db, make_user):
        user = make_user(email="Ada@Example.com")
        assert self.invoke(run, "--email", "  ada@EXAMPLE.com ").exit_code == 0
        worker_db.refresh(user)
        assert tokens.verify_password(self.NEW, user.hashed_password)

    def test_it_says_which_user_and_does_not_echo_the_password(self, run, make_user):
        make_user(email="ada@example.com")
        result = self.invoke(run, "--email", "ada@example.com")
        assert "Password set for ada@example.com" in result.output
        assert self.NEW not in result.output  # what was typed is not shown back
        assert "JWT_SECRET_KEY" in result.output  # and the existing sign-ins are said to stay valid

    def test_an_unknown_user_is_an_error_and_creates_nobody(self, run, worker_db):
        result = self.invoke(run, "--email", "nobody@example.com")
        assert result.exit_code == 1 and "No user with the email nobody@example.com" in result.output
        assert worker_db.query(User).count() == 0

    @pytest.mark.parametrize("password", ["short", "x" * 11, "é" * 37, "x" * 73])
    def test_a_password_that_user_creation_would_refuse_is_refused(self, run, worker_db, make_user, password):
        user = make_user(email="ada@example.com", password="the-old-password")
        before = user.hashed_password
        result = self.invoke(run, "--email", "ada@example.com", answers=f"{password}\n{password}\n")
        assert result.exit_code == 1 and "password must be" in result.output
        worker_db.refresh(user)
        assert user.hashed_password == before

    def test_two_different_entries_change_nothing(self, run, worker_db, make_user):
        user = make_user(email="ada@example.com", password="the-old-password")
        before = user.hashed_password
        result = self.invoke(run, "--email", "ada@example.com", answers="first-password-here\nsecond-password-here\n")
        assert result.exit_code != 0
        worker_db.refresh(user)
        assert user.hashed_password == before

    def test_the_exact_maximum_length_is_accepted(self, run, worker_db, make_user):
        user = make_user(email="ada@example.com")
        assert self.invoke(run, "--email", "ada@example.com", answers="x" * 72 + "\n" + "x" * 72 + "\n").exit_code == 0
        worker_db.refresh(user)
        assert tokens.verify_password("x" * 72, user.hashed_password)

    def test_the_exact_minimum_length_is_accepted(self, run, worker_db, make_user):
        user = make_user(email="ada@example.com")
        assert self.invoke(run, "--email", "ada@example.com", answers="x" * 12 + "\n" + "x" * 12 + "\n").exit_code == 0
        worker_db.refresh(user)
        assert tokens.verify_password("x" * 12, user.hashed_password)
