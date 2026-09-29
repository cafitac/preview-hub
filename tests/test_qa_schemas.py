import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from preview_hub.cli import descriptor
from preview_hub.contracts import CompositionSpec, EnvName
from preview_hub.lifecycle import CreateEnvironment

ROOT = Path(__file__).resolve().parents[1]


def validate_schema(name, document):
    schema = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)


def test_sample_qa_report_schema():
    report = json.loads((ROOT / "e2e/fixtures/sample-qa-report.json").read_text())
    validate_schema("qa-report", report)


def test_ready_descriptor_schema(ctx):
    env = CreateEnvironment(ctx).execute(CompositionSpec(EnvName("schema-test"), {}))
    document = descriptor(env, ctx.catalog.public_url_template)
    validate_schema("environment-descriptor", document)
    assert document["state"] == "READY"
    assert document["readiness"]["allHealthy"] is True
    assert document["services"][0]["commit"] == ctx.git.sha
    assert document["testAccounts"] == []
