"""
Entropy-Based Secret Scanning for Phase 3.3
============================================

Shannon entropy analysis for detecting high-randomness strings that may be API keys,
tokens, or other secrets. Based on algorithms from TruffleHog and detect-secrets.

Author: MCP Jupyter Server Team
Phase: 3.3 - Entropy-Based Secret Scanning
"""

import re
import math
from typing import List, Tuple, Optional
from dataclasses import dataclass
from loguru import logger


@dataclass
class SecretMatch:
    """Detected secret with metadata."""
    text: str
    start: int
    end: int
    entropy: float
    secret_type: str
    confidence: float  # 0.0-1.0


class EntropySecretScanner:
    """
    Detects secrets using Shannon entropy analysis.
    
    This scanner identifies high-randomness strings that are likely to be
    API keys, tokens, passwords, or other credentials based on their
    information entropy and pattern matching.
    
    References:
    - TruffleHog: https://github.com/trufflesecurity/trufflehog
    - detect-secrets: https://github.com/Yelp/detect-secrets
    - Shannon Entropy: https://en.wikipedia.org/wiki/Entropy_(information_theory)
    """
    
    # Entropy thresholds (bits per character)
    # Based on empirical testing with secrets.choice() generated strings:
    # - Random alphanumeric (a-zA-Z0-9): ~4.2-4.7 entropy
    # - Random hex (0-9a-f): ~3.8-4.0 entropy
    # - Base64: ~4.5-5.0 entropy
    HEX_THRESHOLD = 3.7         # Hex-encoded data (16 chars = log2(16) = 4.0 max)
    BASE64_THRESHOLD = 4.2      # Base64-encoded data and random alphanumeric
    HIGH_ENTROPY_THRESHOLD = 4.2  # High-entropy strings (random tokens)
    API_KEY_THRESHOLD = 4.5     # Very high entropy (truly random API keys)
    
    # Minimum string length to analyze (avoid false positives on short strings)
    MIN_STRING_LENGTH = 20
    
    # Known API key patterns (regex + entropy for higher confidence)
    API_KEY_PATTERNS = [
        # OpenAI API keys
        (r'sk-[a-zA-Z0-9]{20,}', 'openai_api_key', 6.0),
        (r'sk-proj-[a-zA-Z0-9_-]{20,}', 'openai_project_key', 6.0),
        
        # AWS Access Keys
        (r'AKIA[0-9A-Z]{16}', 'aws_access_key', 5.5),
        (r'(?:aws_secret_access_key|AWS_SECRET_ACCESS_KEY)\s*[:=]\s*[A-Za-z0-9/+=]{40}', 'aws_secret_key', 6.0),
        
        # Google Cloud API Keys
        (r'AIza[0-9A-Za-z-_]{35}', 'google_api_key', 5.5),
        
        # GitHub Personal Access Tokens
        (r'ghp_[0-9a-zA-Z]{36}', 'github_pat', 6.0),
        (r'gho_[0-9a-zA-Z]{36}', 'github_oauth', 6.0),
        (r'ghs_[0-9a-zA-Z]{36}', 'github_server_token', 6.0),
        
        # Stripe API Keys
        (r'sk_live_[0-9a-zA-Z]{24,}', 'stripe_live_key', 6.0),
        (r'sk_test_[0-9a-zA-Z]{24,}', 'stripe_test_key', 6.0),
        
        # Slack Tokens
        (r'xoxb-[0-9]{11}-[0-9]{11}-[0-9a-zA-Z]{24}', 'slack_bot_token', 6.0),
        (r'xoxp-[0-9]{11}-[0-9]{11}-[0-9]{11}-[0-9a-zA-Z]{32}', 'slack_user_token', 6.0),
        
        # Twilio
        (r'SK[0-9a-fA-F]{32}', 'twilio_api_key', 5.5),
        
        # Generic high-entropy patterns (only with high entropy threshold)
        # These are disabled by default to reduce false positives
        # (r'[a-zA-Z0-9_-]{32,}', 'generic_token', 6.5),  # Long alphanumeric strings
        # (r'[A-Za-z0-9+/]{40,}={0,2}', 'base64_token', 4.5),  # Base64-encoded
    ]
    
    def __init__(self, enable_entropy: bool = True, enable_patterns: bool = True):
        """
        Initialize the entropy-based secret scanner.
        
        Args:
            enable_entropy: Enable Shannon entropy analysis
            enable_patterns: Enable regex pattern matching
        """
        self.enable_entropy = enable_entropy
        self.enable_patterns = enable_patterns
    
    def calculate_shannon_entropy(self, text: str) -> float:
        """
        Calculate Shannon entropy of a string (bits per character).
        
        Shannon entropy measures the randomness/information content of a string.
        Higher entropy indicates more randomness, which is characteristic of
        cryptographic keys and tokens.
        
        Formula: H(X) = -Σ P(x) * log2(P(x))
        
        Args:
            text: String to analyze
            
        Returns:
            Entropy in bits per character (0.0 to ~6.0 for typical text)
        
        Examples:
            - "aaaaaaa": ~0.0 (no randomness)
            - "hello world": ~3.0 (normal English text)
            - "sk-1234abcd5678EFGH": ~4.5 (base64-like)
            - "X9kL2mP8vQ4nZ7wR": ~6.0 (high entropy, likely random)
        """
        if not text:
            return 0.0
        
        # Count character frequencies
        char_counts = {}
        for char in text:
            char_counts[char] = char_counts.get(char, 0) + 1
        
        # Calculate entropy
        entropy = 0.0
        text_length = len(text)
        
        for count in char_counts.values():
            probability = count / text_length
            if probability > 0:
                entropy -= probability * math.log2(probability)
        
        return entropy
    
    def extract_candidate_strings(self, text: str) -> List[Tuple[str, int, int]]:
        """
        Extract candidate strings that might be secrets.
        
        This extracts:
        - Long alphanumeric strings (20+ chars)
        - Base64-looking strings
        - Strings following common key/token patterns
        
        Args:
            text: Text to scan
            
        Returns:
            List of (candidate_string, start_index, end_index)
        """
        candidates = []
        
        # Pattern 1: Long alphanumeric strings (no whitespace)
        # Matches: "sk-1234567890abcdef1234567890abcdef"
        for match in re.finditer(r'\b[a-zA-Z0-9_-]{20,}\b', text):
            candidates.append((match.group(0), match.start(), match.end()))
        
        # Pattern 2: Base64-looking strings
        # Matches: "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXo="
        for match in re.finditer(r'[A-Za-z0-9+/]{20,}={0,2}', text):
            candidates.append((match.group(0), match.start(), match.end()))
        
        # Pattern 3: Hex-encoded strings (32+ hex chars)
        # Matches: "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
        for match in re.finditer(r'\b[a-fA-F0-9]{32,}\b', text):
            candidates.append((match.group(0), match.start(), match.end()))
        
        # Deduplicate overlapping matches (keep longest)
        candidates.sort(key=lambda x: (x[1], -len(x[0])))  # Sort by start, then by length (desc)
        
        unique_candidates = []
        last_end = -1
        
        for candidate, start, end in candidates:
            if start >= last_end:  # No overlap
                unique_candidates.append((candidate, start, end))
                last_end = end
        
        return unique_candidates
    
    def scan_text(self, text: str) -> List[SecretMatch]:
        """
        Scan text for potential secrets using entropy analysis and pattern matching.
        
        Args:
            text: Text to scan
            
        Returns:
            List of detected secrets with metadata
        """
        secrets = []
        
        # Step 1: Pattern-based detection (high confidence)
        if self.enable_patterns:
            for pattern, secret_type, expected_entropy in self.API_KEY_PATTERNS:
                for match in re.finditer(pattern, text):
                    matched_text = match.group(0)
                    entropy = self.calculate_shannon_entropy(matched_text)
                    
                    # Confidence based on entropy match
                    # Pattern match gives base confidence of 0.7, increased if entropy matches expected
                    if entropy >= expected_entropy * 0.8:
                        confidence = min(entropy / expected_entropy, 1.0)
                    else:
                        confidence = 0.7  # Base confidence for pattern match alone
                    
                    # Pattern match is sufficient - don't filter by entropy
                    secrets.append(SecretMatch(
                        text=matched_text,
                        start=match.start(),
                        end=match.end(),
                        entropy=entropy,
                        secret_type=secret_type,
                        confidence=confidence
                    ))
        
        # Step 2: Entropy-based detection (catch unknowns)
        if self.enable_entropy:
            candidates = self.extract_candidate_strings(text)
            
            for candidate, start, end in candidates:
                # Skip if too short
                if len(candidate) < self.MIN_STRING_LENGTH:
                    continue
                
                # Calculate entropy
                entropy = self.calculate_shannon_entropy(candidate)
                
                # Check if it's a hex string (only 0-9a-fA-F)
                is_hex = bool(re.match(r'^[0-9a-fA-F]+$', candidate)) and len(candidate) >= 40
                
                # Check thresholds
                if is_hex and entropy >= self.HEX_THRESHOLD:
                    # Long hex string with decent entropy - likely a hash/token
                    secret_type = 'hex_encoded_secret'
                    confidence = min((entropy - self.HEX_THRESHOLD) / 1.0 + 0.6, 0.9)
                    
                    # Skip if already detected
                    if any(s.start == start and s.end == end for s in secrets):
                        continue
                    
                    secrets.append(SecretMatch(
                        text=candidate,
                        start=start,
                        end=end,
                        entropy=entropy,
                        secret_type=secret_type,
                        confidence=confidence
                    ))
                
                elif entropy >= self.API_KEY_THRESHOLD:
                    # Very high entropy - likely an API key
                    secret_type = 'high_entropy_string'
                    confidence = min((entropy - self.API_KEY_THRESHOLD) / 2.0 + 0.7, 1.0)
                    
                    # Skip if already detected by pattern matching
                    if any(s.start == start and s.end == end for s in secrets):
                        continue
                    
                    secrets.append(SecretMatch(
                        text=candidate,
                        start=start,
                        end=end,
                        entropy=entropy,
                        secret_type=secret_type,
                        confidence=confidence
                    ))
                
                elif entropy >= self.HIGH_ENTROPY_THRESHOLD:
                    # High entropy - possibly a secret
                    secret_type = 'possible_secret'
                    confidence = min((entropy - self.HIGH_ENTROPY_THRESHOLD) / 2.0 + 0.5, 0.8)
                    
                    # Skip if already detected
                    if any(s.start == start and s.end == end for s in secrets):
                        continue
                    
                    secrets.append(SecretMatch(
                        text=candidate,
                        start=start,
                        end=end,
                        entropy=entropy,
                        secret_type=secret_type,
                        confidence=confidence
                    ))
        
        # Sort by start position
        secrets.sort(key=lambda s: s.start)
        
        return secrets
    
    def redact_secrets(self, text: str, secrets: List[SecretMatch]) -> str:
        """
        Redact detected secrets from text.
        
        Args:
            text: Original text
            secrets: List of secrets to redact
            
        Returns:
            Text with secrets redacted
        """
        if not secrets:
            return text
        
        # Sort secrets by start position (reverse order for safe replacement)
        sorted_secrets = sorted(secrets, key=lambda s: s.start, reverse=True)
        
        result = text
        for secret in sorted_secrets:
            redaction = f"[REDACTED_{secret.secret_type.upper()}]"
            result = result[:secret.start] + redaction + result[secret.end:]
        
        return result
    
    def scan_and_redact(self, text: str, min_confidence: float = 0.5) -> Tuple[str, List[SecretMatch]]:
        """
        Scan text for secrets and redact them.
        
        Args:
            text: Text to scan and redact
            min_confidence: Minimum confidence threshold (0.0-1.0)
            
        Returns:
            (redacted_text, detected_secrets)
        """
        # Scan for secrets
        all_secrets = self.scan_text(text)
        
        # Filter by confidence threshold
        high_confidence_secrets = [s for s in all_secrets if s.confidence >= min_confidence]
        
        # Log detected secrets (without revealing the actual secret)
        if high_confidence_secrets:
            logger.warning(
                f"Detected {len(high_confidence_secrets)} potential secrets "
                f"(entropy-based scanning)"
            )
            for secret in high_confidence_secrets:
                logger.debug(
                    f"Secret detected: type={secret.secret_type}, "
                    f"entropy={secret.entropy:.2f}, "
                    f"confidence={secret.confidence:.2f}, "
                    f"length={len(secret.text)}"
                )
        
        # Redact secrets
        redacted_text = self.redact_secrets(text, high_confidence_secrets)
        
        return redacted_text, high_confidence_secrets


# Global scanner instance
_global_scanner: Optional[EntropySecretScanner] = None


def get_scanner() -> EntropySecretScanner:
    """Get or create the global entropy scanner instance."""
    global _global_scanner
    if _global_scanner is None:
        _global_scanner = EntropySecretScanner(
            enable_entropy=True,
            enable_patterns=True
        )
    return _global_scanner


def scan_for_secrets(text: str, min_confidence: float = 0.5) -> List[SecretMatch]:
    """
    Scan text for potential secrets (convenience function).
    
    Args:
        text: Text to scan
        min_confidence: Minimum confidence threshold (0.0-1.0)
        
    Returns:
        List of detected secrets
    """
    scanner = get_scanner()
    secrets = scanner.scan_text(text)
    return [s for s in secrets if s.confidence >= min_confidence]


def redact_secrets(text: str, min_confidence: float = 0.5) -> str:
    """
    Scan and redact secrets from text (convenience function).
    
    Args:
        text: Text to redact
        min_confidence: Minimum confidence threshold (0.0-1.0)
        
    Returns:
        Text with secrets redacted
    """
    scanner = get_scanner()
    redacted_text, _ = scanner.scan_and_redact(text, min_confidence)
    return redacted_text


# Export key classes and functions
__all__ = [
    'EntropySecretScanner',
    'SecretMatch',
    'get_scanner',
    'scan_for_secrets',
    'redact_secrets',
]
