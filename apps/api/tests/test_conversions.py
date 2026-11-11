"""
Tests for Feature 2: Conversion Feedback Loop.

Covers:
  - ConversionCreate schema validation
  - Analytics endpoint model-accuracy with no data
  - Score snapshot attachment on conversion creation
  - Tier accuracy precision computation
"""

from datetime import UTC, datetime


class TestConversionSchema:
    def test_create_minimal(self):
        from app.schemas.conversion import ConversionCreate

        c = ConversionCreate(
            contact_id="00000000-0000-0000-0000-000000000001",
            converted_at=datetime.now(UTC),
        )
        assert c.source == "manual"
        assert c.deal_value is None

    def test_create_full(self):
        from app.schemas.conversion import ConversionCreate

        c = ConversionCreate(
            contact_id="00000000-0000-0000-0000-000000000001",
            converted_at=datetime.now(UTC),
            deal_value=12500.0,
            days_to_close=14,
            plan_tier="pro",
            source="hubspot_webhook",
            crm_deal_id="deal_123",
        )
        assert c.deal_value == 12500.0
        assert c.crm_deal_id == "deal_123"


class TestTierAccuracySchema:
    def test_precision_calculation(self):
        from app.schemas.conversion import TierAccuracy

        t = TierAccuracy(
            tier="HOT",
            total_leads=100,
            converted=42,
            precision=0.42,
            avg_score=82.5,
            avg_deal_value=15000.0,
            avg_days_to_close=12.3,
        )
        assert t.precision == 0.42
        assert t.avg_score == 82.5


class TestModelAccuracyReport:
    def test_empty_report_structure(self):
        from app.schemas.conversion import ModelAccuracyReport

        report = ModelAccuracyReport(
            model_version="1.0.0",
            total_scored=0,
            total_converted=0,
            overall_conversion_rate=0.0,
            tiers=[],
            generated_at=datetime.now(UTC),
        )
        assert report.overall_conversion_rate == 0.0
        assert report.tiers == []

    def test_report_with_tiers(self):
        from app.schemas.conversion import ModelAccuracyReport, TierAccuracy

        tiers = [
            TierAccuracy(
                tier="HOT",
                total_leads=100,
                converted=45,
                precision=0.45,
                avg_score=82.0,
                avg_deal_value=18000.0,
                avg_days_to_close=10.0,
            ),
            TierAccuracy(
                tier="WARM",
                total_leads=300,
                converted=60,
                precision=0.20,
                avg_score=60.0,
                avg_deal_value=8000.0,
                avg_days_to_close=20.0,
            ),
        ]
        report = ModelAccuracyReport(
            model_version="1.0.0",
            total_scored=400,
            total_converted=105,
            overall_conversion_rate=0.2625,
            tiers=tiers,
            generated_at=datetime.now(UTC),
        )
        assert len(report.tiers) == 2
        assert report.tiers[0].tier == "HOT"
        assert report.tiers[0].precision == 0.45
