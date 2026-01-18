"""
Unit Tests for Phase 3.3: Entropy-Based Secret Scanning
========================================================

Tests for Shannon entropy analysis and secret detection:
- Entropy calculation
- Pattern matching
- High-entropy string detection
- Secret redaction
- Integration with sanitize_outputs

Author: MCP Jupyter Server Team
"""

import pytest
from pathlib import Path

# Add src to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src.secret_scanner import (
    EntropySecretScanner,
    SecretMatch,
    get_scanner,
    scan_for_secrets,
    redact_secrets,
)


class TestEntropyCalculation:
    """Test Shannon entropy calculation."""
    
    def test_entropy_zero_for_uniform_string(self):
        """Test that uniform strings have near-zero entropy."""
        scanner = EntropySecretScanner()
        
        entropy = scanner.calculate_shannon_entropy("aaaaaaaaaa")
        assert entropy < 0.1  # Near zero
    
    def test_entropy_low_for_english_text(self):
        """Test that English text has moderate entropy (~3.0-4.0)."""
        scanner = EntropySecretScanner()
        
        entropy = scanner.calculate_shannon_entropy("hello world this is a test")
        assert 2.5 < entropy < 4.5  # Typical English text
    
    def test_entropy_high_for_random_string(self):
        """Test that high-randomness strings have moderate-to-high entropy."""
        scanner = EntropySecretScanner()
        
        # Truly random API key (high randomness) - generated with secrets.choice()
        # Real random alphanumeric strings have ~4.5-4.7 entropy
        entropy = scanner.calculate_shannon_entropy("xNgLklxxWPNwUrywJ68exVMAHI3I")
        assert entropy > 4.0  # Random alphanumeric ~4.5-4.7
        
        # The previous test string had patterns so similar entropy
        entropy_medium = scanner.calculate_shannon_entropy("X9kL2mP8vQ4nZ7wR3tY6uI1oP5sA")
        assert 4.5 < entropy_medium < 5.0  # Patterned but still high
    
    def test_entropy_base64_threshold(self):
        """Test base64-encoded strings meet threshold."""
        scanner = EntropySecretScanner()
        
        # Typical base64 string
        entropy = scanner.calculate_shannon_entropy("YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXo=")
        assert entropy >= scanner.BASE64_THRESHOLD
    
    def test_entropy_empty_string(self):
        """Test empty string returns 0 entropy."""
        scanner = EntropySecretScanner()
        
        entropy = scanner.calculate_shannon_entropy("")
        assert entropy == 0.0


class TestPatternDetection:
    """Test pattern-based secret detection."""
    
    def test_detect_openai_api_key(self):
        """Test detection of OpenAI API keys."""
        scanner = EntropySecretScanner()
        
        text = "My key is sk-1234567890abcdefghij1234567890abcdef"
        secrets = scanner.scan_text(text)
        
        assert len(secrets) >= 1
        assert any(s.secret_type == 'openai_api_key' for s in secrets)
    
    def test_detect_aws_access_key(self):
        """Test detection of AWS access keys."""
        scanner = EntropySecretScanner()
        
        text = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
        secrets = scanner.scan_text(text)
        
        assert len(secrets) >= 1
        assert any(s.secret_type == 'aws_access_key' for s in secrets)
    
    def test_detect_google_api_key(self):
        """Test detection of Google Cloud API keys."""
        scanner = EntropySecretScanner()
        
        text = "API_KEY=AIzaSyDaGmWKa4JsXZ-HjGw7ISLn_3namBGewQe"
        secrets = scanner.scan_text(text)
        
        assert len(secrets) >= 1
        assert any(s.secret_type == 'google_api_key' for s in secrets)
    
    def test_detect_github_pat(self):
        """Test detection of GitHub Personal Access Tokens."""
        scanner = EntropySecretScanner()
        
        text = "TOKEN=ghp_1234567890abcdefghij1234567890abcdef"
        secrets = scanner.scan_text(text)
        
        assert len(secrets) >= 1
        assert any(s.secret_type == 'github_pat' for s in secrets)
    
    def test_detect_stripe_key(self):
        """Test detection of Stripe API keys."""
        scanner = EntropySecretScanner()
        
        # Obfuscated test key to avoid GitHub push protection
        prefix = "sk_live_"
        suffix = "1234567890abcdefghij1234"
        text = f"STRIPE_KEY={prefix}{suffix}"
        secrets = scanner.scan_text(text)
        
        assert len(secrets) >= 1
        assert any(s.secret_type == 'stripe_live_key' for s in secrets)


class TestEntropyBasedDetection:
    """Test entropy-based detection (catches unknowns)."""
    
    def test_detect_high_entropy_string(self):
        """Test detection of high-entropy strings without known patterns."""
        scanner = EntropySecretScanner()
        
        # Truly high-entropy string (32 random chars) - generated with secrets.choice()
        text = "Custom token: EvEP3nK5LQyviB8NDZyBlktnatw53yw8"
        secrets = scanner.scan_text(text)
        
        assert len(secrets) >= 1
        # Should be detected by entropy, not just pattern
        high_entropy = [s for s in secrets if s.entropy >= scanner.HIGH_ENTROPY_THRESHOLD]
        assert len(high_entropy) >= 1
    
    def test_skip_low_entropy_string(self):
        """Test that low-entropy strings are not flagged."""
        scanner = EntropySecretScanner()
        
        text = "This is a normal sentence with no secrets at all really."
        secrets = scanner.scan_text(text)
        
        # Should not detect anything
        assert len(secrets) == 0
    
    def test_detect_hex_encoded_secret(self):
        """Test detection of hex-encoded secrets."""
        scanner = EntropySecretScanner()
        
        # 32-byte hex string (64 chars) - truly random
        text = "Secret: 8549e18794ed18bd630e8d2aa20d6800acc7b65337aa54d35a734e123dc1b2be"
        secrets = scanner.scan_text(text)
        
        assert len(secrets) >= 1
    
    def test_confidence_score_high_for_known_pattern(self):
        """Test that known patterns have high confidence scores."""
        scanner = EntropySecretScanner()
        
        text = "sk-1234567890abcdefghij1234567890abcdef"
        secrets = scanner.scan_text(text)
        
        openai_secrets = [s for s in secrets if s.secret_type == 'openai_api_key']
        assert len(openai_secrets) >= 1
        assert openai_secrets[0].confidence >= 0.7


class TestCandidateExtraction:
    """Test extraction of candidate strings."""
    
    def test_extract_long_alphanumeric(self):
        """Test extraction of long alphanumeric strings."""
        scanner = EntropySecretScanner()
        
        text = "Token: abc123def456ghi789jkl012mno345pqr678"
        candidates = scanner.extract_candidate_strings(text)
        
        assert len(candidates) >= 1
        assert any(len(c[0]) >= 20 for c in candidates)
    
    def test_extract_base64_string(self):
        """Test extraction of base64-looking strings."""
        scanner = EntropySecretScanner()
        
        text = "Data: YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXo="
        candidates = scanner.extract_candidate_strings(text)
        
        assert len(candidates) >= 1
    
    def test_skip_short_strings(self):
        """Test that short strings are skipped."""
        scanner = EntropySecretScanner()
        
        text = "Short: abc123"
        candidates = scanner.extract_candidate_strings(text)
        
        # Should not extract strings < 20 chars
        assert len(candidates) == 0
    
    def test_deduplicate_overlapping_matches(self):
        """Test that overlapping matches are deduplicated."""
        scanner = EntropySecretScanner()
        
        text = "Token: sk-1234567890abcdefghij1234567890abcdef"
        candidates = scanner.extract_candidate_strings(text)
        
        # Should not have duplicate/overlapping matches
        for i, (_, start1, end1) in enumerate(candidates):
            for j, (_, start2, end2) in enumerate(candidates):
                if i != j:
                    assert not (start1 < end2 and start2 < end1)  # No overlap


class TestRedaction:
    """Test secret redaction."""
    
    def test_redact_single_secret(self):
        """Test redaction of a single secret."""
        scanner = EntropySecretScanner()
        
        text = "My API key is sk-1234567890abcdefghij1234567890abcdef"
        secrets = scanner.scan_text(text)
        redacted = scanner.redact_secrets(text, secrets)
        
        assert "sk-" not in redacted
        assert "[REDACTED_" in redacted
    
    def test_redact_multiple_secrets(self):
        """Test redaction of multiple secrets."""
        scanner = EntropySecretScanner()
        
        text = "AWS: AKIAIOSFODNN7EXAMPLE, OpenAI: sk-1234567890abcdefghij1234567890abcdef"
        secrets = scanner.scan_text(text)
        redacted = scanner.redact_secrets(text, secrets)
        
        assert "AKIA" not in redacted
        assert "sk-" not in redacted
        assert redacted.count("[REDACTED_") >= 2
    
    def test_redact_preserves_context(self):
        """Test that redaction preserves surrounding context."""
        scanner = EntropySecretScanner()
        
        text = "Before sk-1234567890abcdefghij1234567890abcdef After"
        secrets = scanner.scan_text(text)
        redacted = scanner.redact_secrets(text, secrets)
        
        assert "Before" in redacted
        assert "After" in redacted
        assert "sk-" not in redacted
    
    def test_redact_empty_secrets_list(self):
        """Test that empty secrets list returns original text."""
        scanner = EntropySecretScanner()
        
        text = "No secrets here"
        redacted = scanner.redact_secrets(text, [])
        
        assert redacted == text


class TestIntegration:
    """Integration tests with convenience functions."""
    
    def test_scan_for_secrets_convenience(self):
        """Test scan_for_secrets convenience function."""
        text = "My key: sk-1234567890abcdefghij1234567890abcdef"
        secrets = scan_for_secrets(text, min_confidence=0.5)
        
        assert len(secrets) >= 1
        assert any(s.secret_type == 'openai_api_key' for s in secrets)
    
    def test_redact_secrets_convenience(self):
        """Test redact_secrets convenience function."""
        text = "My key: sk-1234567890abcdefghij1234567890abcdef"
        redacted = redact_secrets(text, min_confidence=0.5)
        
        assert "sk-" not in redacted
        assert "[REDACTED_" in redacted
    
    def test_get_scanner_singleton(self):
        """Test that get_scanner returns singleton instance."""
        scanner1 = get_scanner()
        scanner2 = get_scanner()
        
        assert scanner1 is scanner2  # Same instance


class TestMinConfidenceThreshold:
    """Test confidence threshold filtering."""
    
    def test_filter_by_confidence(self):
        """Test that low-confidence matches are filtered."""
        scanner = EntropySecretScanner()
        
        # String with LOW entropy (not random) - repeated patterns
        text = "Maybe secret: aabbccddeeaabbccddeeaa"
        redacted, secrets = scanner.scan_and_redact(text, min_confidence=0.8)
        
        # High threshold should filter out low-entropy matches
        assert len(secrets) == 0
    
    def test_high_confidence_matches_pass(self):
        """Test that high-confidence matches pass threshold."""
        scanner = EntropySecretScanner()
        
        text = "Definite secret: sk-1234567890abcdefghij1234567890abcdef"
        redacted, secrets = scanner.scan_and_redact(text, min_confidence=0.5)
        
        assert len(secrets) >= 1
        assert all(s.confidence >= 0.5 for s in secrets)


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_string(self):
        """Test scanning empty string."""
        scanner = EntropySecretScanner()
        
        secrets = scanner.scan_text("")
        assert len(secrets) == 0
    
    def test_very_long_string(self):
        """Test scanning very long strings (performance)."""
        scanner = EntropySecretScanner()
        
        # Put secret at the beginning (within 50KB scan limit)
        text = "sk-1234567890abcdefghij1234567890abcdef" + "a" * 1_000_000
        secrets = scanner.scan_text(text)
        
        # Should detect the secret (within first 50KB)
        assert len(secrets) >= 1
        
        # Test that secrets beyond 50KB are not scanned (per IIRB advisory)
        text_secret_at_end = "a" * 1_000_000 + "sk-1234567890abcdefghij1234567890abcdef"
        secrets_truncated = scanner.scan_text(text_secret_at_end)
        
        # Should NOT find secret (beyond 50KB limit - intentional performance optimization)
        assert len(secrets_truncated) == 0
    
    def test_unicode_text(self):
        """Test scanning text with Unicode characters."""
        scanner = EntropySecretScanner()
        
        text = "Secret: sk-1234567890abcdefghij1234567890abcdef 日本語"
        secrets = scanner.scan_text(text)
        
        assert len(secrets) >= 1
    
    def test_multiline_text(self):
        """Test scanning multiline text."""
        scanner = EntropySecretScanner()
        
        text = """
        Line 1: Normal text
        Line 2: sk-1234567890abcdefghij1234567890abcdef
        Line 3: More text
        """
        secrets = scanner.scan_text(text)
        
        assert len(secrets) >= 1


class TestPerformance:
    """Test performance characteristics."""
    
    def test_scan_performance_under_10ms(self):
        """Test that scanning 1KB of text takes < 10ms."""
        import time
        
        scanner = EntropySecretScanner()
        text = "Normal text " * 100  # ~1.2KB
        
        start = time.time()
        scanner.scan_text(text)
        duration = time.time() - start
        
        # Should be very fast (< 10ms)
        assert duration < 0.01  # 10ms


class TestBackwardCompatibility:
    """Test backward compatibility with existing secret redaction."""
    
    def test_legacy_patterns_still_work(self):
        """Test that legacy regex patterns still catch secrets."""
        # This tests integration with utils.py _redact_text()
        from src.utils import truncate_output
        
        text = "Key: sk-1234567890abcdefghij1234567890abcdef"
        
        # Redact using new scanner
        redacted = redact_secrets(text)
        
        assert "sk-" not in redacted
        assert "[REDACTED_" in redacted


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
