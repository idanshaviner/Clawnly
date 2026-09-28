"""deploy_render.py: what it sends to Render, and that no secret is ever printed."""

import json

import httpx
import pytest

import deploy_render

ENV = {"ANTHROPIC_API_KEY": "sk-secret-anthropic", "RESEND_API_KEY": "", "UNRELATED": "x"}


def test_env_vars_pass_on_only_the_secrets_that_are_set():
    keys = {v["key"]: v["value"] for v in deploy_render.env_vars("a@example.com", "https://x.onrender.com", ENV)}
    assert keys["ANTHROPIC_API_KEY"] == "sk-secret-anthropic"
    assert "RESEND_API_KEY" not in keys
    assert "UNRELATED" not in keys
    assert keys["CLAWNLY_ADMIN_EMAILS"] == "a@example.com"
    assert keys["CLAWNLY_BASE_URL"] == "https://x.onrender.com"
    assert keys["CLAWNLY_DB_PATH"] == "/var/data/clawnly.db"


def test_the_service_matches_render_yaml():
    body = deploy_render.create_body("own-1", "clawnly-lounge", "a@example.com", ENV)
    details = body["serviceDetails"]
    assert body["repo"] == "https://github.com/idanshaviner/Clawnly"
    assert body["branch"] == "clawnly-lounge"
    assert details["plan"] == "starter"
    assert details["disk"]["mountPath"] == "/var/data"
    assert details["envSpecificDetails"]["startCommand"] == deploy_render.START
    render_yaml = open("render.yaml").read()
    assert deploy_render.START in render_yaml
    assert deploy_render.BUILD in render_yaml


def fake_render(handler):
    return httpx.Client(base_url=deploy_render.API, transport=httpx.MockTransport(handler))


def test_the_sign_in_link_is_read_from_the_log():
    def handler(request):
        assert request.url.params["resource"] == "srv-1"
        return httpx.Response(200, json={"logs": [
            {"message": "INFO: 200 OK"},
            {"message": "[DEV MODE] Magic link for a@example.com: https://x.onrender.com/auth/magic-link/verify?token=abc123 "},
        ]})

    link = deploy_render.magic_link_from_logs(fake_render(handler), "own-1", "srv-1", "2026-09-26T00:00:00Z")
    assert link == "https://x.onrender.com/auth/magic-link/verify?token=abc123"


def test_env_vars_are_upserted_one_by_one_and_errors_never_echo_values(capsys):
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/ANTHROPIC_API_KEY"):
            return httpx.Response(400, json={"message": "bad key"})
        return httpx.Response(200, json={})

    variables = deploy_render.env_vars("a@example.com", None, ENV)
    with pytest.raises(SystemExit) as stop:
        deploy_render.set_env(fake_render(handler), "srv-1", variables)
    assert ("PUT", "/v1/services/srv-1/env-vars/PYTHON_VERSION") in seen
    assert "sk-secret-anthropic" not in str(stop.value)
    assert "sk-secret-anthropic" not in capsys.readouterr().out


def test_the_free_plan_has_no_disk_and_keeps_the_database_in_the_container():
    body = deploy_render.create_body("own-1", "clawnly-lounge", "a@example.com", ENV, free=True)
    assert body["serviceDetails"]["plan"] == "free"
    assert "disk" not in body["serviceDetails"]
    keys = [v["key"] for v in body["envVars"]]
    assert "CLAWNLY_DB_PATH" not in keys
