"""
Tests for validation utilities.

Tests audio upload validation without external dependencies.
"""

import pytest
from app.utils.validation import validate_audio_upload, get_audio_extension


class TestAudioUploadValidation:
    """Test audio file upload validation."""

    def test_valid_webm_upload(self):
        """Valid WebM audio should pass."""
        is_valid, error = validate_audio_upload("audio/webm", 1024, "recording.webm")
        assert is_valid is True
        assert error is None

    def test_valid_wav_upload(self):
        """Valid WAV audio should pass."""
        is_valid, error = validate_audio_upload("audio/wav", 1024, "recording.wav")
        assert is_valid is True
        assert error is None

    def test_empty_file_rejected(self):
        """Empty file should be rejected."""
        is_valid, error = validate_audio_upload("audio/webm", 0, "recording.webm")
        assert is_valid is False
        assert "Empty" in error

    def test_oversized_file_rejected(self):
        """File exceeding max size should be rejected."""
        huge_size = 100 * 1024 * 1024  # 100MB
        is_valid, error = validate_audio_upload("audio/webm", huge_size, "recording.webm")
        assert is_valid is False
        assert "too large" in error

    def test_unsupported_type_rejected(self):
        """Unsupported MIME type should be rejected."""
        is_valid, error = validate_audio_upload("video/mp4", 1024, "video.mp4")
        assert is_valid is False
        assert "Unsupported" in error

    def test_no_content_type_rejected(self):
        """Missing content type should be rejected."""
        is_valid, error = validate_audio_upload(None, 1024, "recording.bin")
        assert is_valid is False

    def test_webm_codecs_opus_accepted(self):
        """audio/webm;codecs=opus should be accepted."""
        is_valid, error = validate_audio_upload("audio/webm;codecs=opus", 1024, "recording.webm")
        assert is_valid is True


class TestAudioExtension:
    """Test MIME to extension mapping."""

    def test_webm_extension(self):
        assert get_audio_extension("audio/webm") == ".webm"

    def test_wav_extension(self):
        assert get_audio_extension("audio/wav") == ".wav"

    def test_ogg_extension(self):
        assert get_audio_extension("audio/ogg") == ".ogg"

    def test_unknown_defaults_webm(self):
        assert get_audio_extension("audio/unknown") == ".webm"
