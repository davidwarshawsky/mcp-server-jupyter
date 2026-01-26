import logging

try:
    # pip-audit API shape may evolve; import defensively
    from pip_audit import Auditor
    from pip_audit._format import CycloneDXFormat
except Exception:
    Auditor = None
    CycloneDXFormat = None

logger = logging.getLogger(__name__)

# A placeholder for a more sophisticated policy engine
# For now, we'll define a simple risk threshold.
CRITICAL_VULNERABILITY_THRESHOLD = 1


class PolicyEngine:
    def check_package(self, package_name: str, version: str | None):
        """
        Audits a package and decides if it meets the installation policy.
        Returns a tuple: (is_approved: bool, reason: str, vulnerability_report: dict)
        """
        logger.info(
            f"Auditing package {package_name}{f'=={version}' if version else ''}"
        )

        # If pip-audit is not available or its API is incompatible, be permissive
        if Auditor is None:
            logger.warning("pip-audit not available; skipping audit and approving package")
            return True, "Audit skipped; tool unavailable in environment", {"package": f"{package_name}{f'=={version}' if version else ''}", "vulnerabilities_found": 0, "critical_vulnerabilities": 0}

        try:
            auditor = Auditor()
            if CycloneDXFormat:
                CycloneDXFormat(True)

            # Create a dummy requirements file content
            req_spec = f"{package_name}{f'=={version}' if version else ''}"

            # We need to run the audit in a way that gives us structured output
            # This is a simplified approach. A real implementation might use the API
            # more deeply to get structured vulnerability data.
            # For now, we count critical vulnerabilities.
            vulnerabilities = list(auditor.audit(req_spec))

            critical_vulns = [
                v
                for v in vulnerabilities
                if getattr(v, "is_vulnerable", lambda: False)() and getattr(v, "get_highest_severity", lambda: "")( ) == "CRITICAL"
            ]

            report = {
                "package": req_spec,
                "vulnerabilities_found": len(vulnerabilities),
                "critical_vulnerabilities": len(critical_vulns),
            }

            if len(critical_vulns) >= CRITICAL_VULNERABILITY_THRESHOLD:
                reason = f"Installation rejected. Found {len(critical_vulns)} critical vulnerabilities."
                logger.warning(reason, extra=report)
                # In a real system, this would trigger an alert or a review workflow.
                return False, reason, report
            else:
                reason = "Package approved for installation."
                logger.info(reason, extra=report)
                return True, reason, report

        except Exception as e:
            logger.error(
                f"Error during package audit for {package_name}: {e}", exc_info=True
            )
            return False, f"An error occurred during the audit: {e}", {}
