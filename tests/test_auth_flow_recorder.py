"""Tests for authentication flow recorder."""

import json
import tempfile
from pathlib import Path

import pytest

from testmcpy.auth_flow_recorder import (
    AuthFlowRecorder,
    AuthFlowRecording,
    AuthFlowStep,
)


def test_auth_flow_step_creation():
    """Test creating an auth flow step."""
    step = AuthFlowStep(
        step_name="Token Request",
        step_type="request",
        data={"client_id": "test123", "grant_type": "client_credentials"},
        success=True,
        duration=0.5,
    )

    assert step.step_name == "Token Request"
    assert step.step_type == "request"
    assert step.success is True
    assert step.duration == 0.5
    assert step.data["client_id"] == "test123"


def test_auth_flow_step_serialization():
    """Test step serialization and deserialization."""
    step = AuthFlowStep(
        step_name="Token Response",
        step_type="response",
        data={"status_code": 200},
        success=True,
    )

    # Serialize
    step_dict = step.to_dict()
    assert step_dict["step_name"] == "Token Response"
    assert step_dict["step_type"] == "response"

    # Deserialize
    restored_step = AuthFlowStep.from_dict(step_dict)
    assert restored_step.step_name == step.step_name
    assert restored_step.step_type == step.step_type
    assert restored_step.data == step.data


def test_auth_flow_recording_creation():
    """Test creating an auth flow recording."""
    recording = AuthFlowRecording(
        flow_name="Test OAuth Flow",
        auth_type="oauth",
        protocol_version="OAuth 2.0",
    )

    assert recording.flow_name == "Test OAuth Flow"
    assert recording.auth_type == "oauth"
    assert recording.protocol_version == "OAuth 2.0"
    assert len(recording.steps) == 0


def test_auth_flow_recording_add_steps():
    """Test adding steps to a recording."""
    recording = AuthFlowRecording(
        flow_name="Test Flow",
        auth_type="oauth",
    )

    step1 = AuthFlowStep("Request", "request", {"url": "https://example.com"})
    step2 = AuthFlowStep("Response", "response", {"status": 200})

    recording.add_step(step1)
    recording.add_step(step2)

    assert recording.get_step_count() == 2
    assert recording.steps[0].step_name == "Request"
    assert recording.steps[1].step_name == "Response"


def test_auth_flow_recording_finalize():
    """Test finalizing a recording."""
    recording = AuthFlowRecording(
        flow_name="Test Flow",
        auth_type="oauth",
    )

    recording.finalize(success=True)

    assert recording.success is True
    assert recording.error is None
    assert recording.end_time is not None
    assert recording.get_duration() > 0


def test_auth_flow_recording_serialization():
    """Test recording serialization and deserialization."""
    recording = AuthFlowRecording(
        flow_name="Test Flow",
        auth_type="jwt",
        protocol_version="JWT",
    )

    recording.add_step(
        AuthFlowStep("Token Request", "request", {"api_url": "https://api.example.com"})
    )
    recording.finalize(success=True)

    # Serialize
    recording_dict = recording.to_dict()
    assert recording_dict["flow_name"] == "Test Flow"
    assert recording_dict["auth_type"] == "jwt"
    assert recording_dict["step_count"] == 1

    # Deserialize
    restored = AuthFlowRecording.from_dict(recording_dict)
    assert restored.flow_name == recording.flow_name
    assert restored.auth_type == recording.auth_type
    assert len(restored.steps) == len(recording.steps)


def test_auth_flow_recorder_initialization():
    """Test initializing the recorder."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = AuthFlowRecorder(storage_dir=tmpdir)
        assert recorder.storage_dir == Path(tmpdir)
        assert recorder.storage_dir.exists()


def test_auth_flow_recorder_start_recording():
    """Test starting a new recording."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = AuthFlowRecorder(storage_dir=tmpdir)

        recording = recorder.start_recording(
            flow_name="Test Flow",
            auth_type="oauth",
            protocol_version="OAuth 2.0",
        )

        assert recording.flow_name == "Test Flow"
        assert recording.auth_type == "oauth"
        assert recorder.current_recording is not None


def test_auth_flow_recorder_record_step():
    """Test recording steps."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = AuthFlowRecorder(storage_dir=tmpdir)
        recorder.start_recording("Test Flow", "oauth")

        recorder.record_step(
            step_name="Token Request",
            step_type="request",
            data={"url": "https://oauth.example.com/token"},
            success=True,
        )

        assert len(recorder.current_recording.steps) == 1
        assert recorder.current_recording.steps[0].step_name == "Token Request"


def test_auth_flow_recorder_stop_and_save():
    """Test stopping and saving a recording."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = AuthFlowRecorder(storage_dir=tmpdir)
        recorder.start_recording("Test Flow", "oauth")

        recorder.record_step(
            "Token Request", "request", {"url": "https://example.com"}, success=True
        )

        recording = recorder.stop_recording(success=True)

        # Verify recording was saved
        saved_files = list(Path(tmpdir).glob("*.json"))
        assert len(saved_files) == 1

        # Load and verify
        loaded = recorder.load_recording(saved_files[0])
        assert loaded.flow_name == "Test Flow"
        assert loaded.success is True


def test_auth_flow_recorder_list_recordings():
    """Test listing saved recordings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = AuthFlowRecorder(storage_dir=tmpdir)

        # Create multiple recordings
        for i, auth_type in enumerate(["oauth", "jwt", "bearer"]):
            recorder.start_recording(f"Flow {i}", auth_type)
            recorder.record_step(f"Step {i}", "request", {"index": i})
            recorder.stop_recording(success=True)

        # List all
        all_recordings = recorder.list_recordings()
        assert len(all_recordings) == 3

        # Filter by type
        oauth_recordings = recorder.list_recordings(auth_type="oauth")
        assert len(oauth_recordings) == 1
        assert oauth_recordings[0]["auth_type"] == "oauth"

        # Limit results
        limited = recorder.list_recordings(limit=2)
        assert len(limited) == 2


def test_auth_flow_recorder_compare():
    """Test comparing two recordings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = AuthFlowRecorder(storage_dir=tmpdir)

        # Create first recording
        recorder.start_recording("Flow 1", "oauth")
        recorder.record_step("Step 1", "request", {"data": "test1"})
        recorder.record_step("Step 2", "response", {"status": 200}, success=True)
        rec1 = recorder.stop_recording(success=True, auto_save=False)

        # Create second recording
        recorder.start_recording("Flow 2", "oauth")
        recorder.record_step("Step 1", "request", {"data": "test2"})
        recorder.record_step("Step 2", "response", {"status": 401}, success=False)
        rec2 = recorder.stop_recording(success=False, auto_save=False)

        # Compare
        comparison = recorder.compare_recordings(rec1, rec2)

        assert comparison["differences"]["success_changed"] is True
        assert len(comparison["differences"]["step_differences"]) > 0


def test_auth_flow_recorder_sanitize():
    """Test sanitizing sensitive data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = AuthFlowRecorder(storage_dir=tmpdir)
        recorder.start_recording("Test Flow", "oauth")

        # Add step with sensitive data
        recorder.record_step(
            "Token Request",
            "request",
            data={
                "client_id": "public123",
                "client_secret": "secret_should_be_hidden",
                "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            },
        )

        recording = recorder.stop_recording(success=True, auto_save=False)

        # Sanitize
        sanitized = recorder.sanitize_recording(recording, keep_token_preview=True)

        # Verify secrets are hidden
        step_data = sanitized.steps[0].data
        assert "secret_should_be_hidden" not in step_data["client_secret"]
        assert step_data["client_secret"].endswith("...")
        assert step_data["token"].endswith("...")
        assert len(step_data["token"]) < len("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9")


def test_auth_flow_recorder_delete():
    """Test deleting a recording."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = AuthFlowRecorder(storage_dir=tmpdir)
        recorder.start_recording("Test Flow", "oauth")
        recording = recorder.stop_recording(success=True)

        # Find saved file
        saved_files = list(Path(tmpdir).glob("*.json"))
        assert len(saved_files) == 1
        filepath = saved_files[0]

        # Delete
        recorder.delete_recording(filepath)

        # Verify deleted
        assert not filepath.exists()


def test_auth_flow_recorder_export():
    """Test exporting a recording to JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = AuthFlowRecorder(storage_dir=tmpdir)
        recorder.start_recording("Test Flow", "oauth")
        recorder.record_step("Step 1", "request", {"url": "https://example.com"})
        recording = recorder.stop_recording(success=True, auto_save=False)

        # Export
        export_path = Path(tmpdir) / "exported.json"
        recorder.export_to_json(recording, export_path)

        # Verify export
        assert export_path.exists()
        data = json.loads(export_path.read_text())
        assert data["flow_name"] == "Test Flow"
        assert len(data["steps"]) == 1


def test_auth_flow_step_counts():
    """Test step count methods."""
    recording = AuthFlowRecording("Test Flow", "oauth")

    recording.add_step(AuthFlowStep("Step 1", "request", {}, success=True))
    recording.add_step(AuthFlowStep("Step 2", "response", {}, success=True))
    recording.add_step(AuthFlowStep("Step 3", "error", {}, success=False))

    assert recording.get_step_count() == 3
    assert recording.get_success_count() == 2
    assert recording.get_failure_count() == 1
