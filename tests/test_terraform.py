"""
Terraform validation test for all three cloud providers.

Runs `terraform init -backend=false` and `terraform validate` on each infra directory.
No cloud credentials needed — purely syntactic/semantic validation.

Run with:
    python test_terraform.py
"""

import os
import subprocess
import sys

INFRA_DIR = os.path.join(os.path.dirname(__file__), "infra")


def test_passed(name):
    print(f"  PASS  {name}")


def test_failed(name, detail=""):
    print(f"  FAIL  {name}")
    if detail:
        print(f"        {detail}")
    sys.exit(1)


def run_terraform(provider_dir, command, args=None):
    """Run a terraform command in the given directory."""
    cmd = ["terraform", command] + (args or [])
    result = subprocess.run(
        cmd,
        cwd=provider_dir,
        capture_output=True,
        text=True,
    )
    return result


def validate_provider(name, provider_dir):
    """Init and validate terraform for a cloud provider."""
    # Check directory exists
    if not os.path.isdir(provider_dir):
        test_failed(f"{name}: directory exists", f"Missing: {provider_dir}")
        return

    # Check main.tf exists
    main_tf = os.path.join(provider_dir, "main.tf")
    if not os.path.isfile(main_tf):
        test_failed(f"{name}: main.tf exists", f"Missing: {main_tf}")
        return

    # Init (no backend to avoid needing credentials)
    result = run_terraform(provider_dir, "init", ["-backend=false", "-no-color"])
    if result.returncode != 0:
        test_failed(f"{name}: terraform init", result.stderr[:500])
        return
    test_passed(f"{name}: terraform init")

    # Validate
    result = run_terraform(provider_dir, "validate", ["-no-color"])
    if result.returncode != 0:
        test_failed(f"{name}: terraform validate", result.stderr[:500] + result.stdout[:500])
        return
    test_passed(f"{name}: terraform validate")


def check_required_files(name, provider_dir, required_files):
    """Check that all expected Terraform files exist."""
    missing = []
    for f in required_files:
        if not os.path.isfile(os.path.join(provider_dir, f)):
            missing.append(f)
    if missing:
        test_failed(f"{name}: required files", f"Missing: {', '.join(missing)}")
    else:
        test_passed(f"{name}: all {len(required_files)} required files present")


def check_terraform_available():
    """Check if terraform is installed."""
    result = subprocess.run(
        ["terraform", "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("ERROR: terraform not found in PATH. Install from https://developer.hashicorp.com/terraform/install")
        sys.exit(1)
    version_line = result.stdout.strip().split("\n")[0]
    print(f"Using: {version_line}")
    return True


def main():
    print("=" * 60)
    print("TERRAFORM VALIDATION TESTS (no cloud credentials needed)")
    print("=" * 60)
    print()

    check_terraform_available()
    print()

    # ------- AWS -------
    print("[1] AWS Infrastructure")
    aws_dir = os.path.join(INFRA_DIR, "aws")
    check_required_files("AWS", aws_dir, [
        "main.tf", "variables.tf", "s3.tf", "ecr.tf", "lambda.tf",
        "ecs.tf", "iam.tf", "network.tf", "secrets.tf", "outputs.tf",
        "lambda/router.py",
    ])
    validate_provider("AWS", aws_dir)

    # ------- GCP -------
    print(f"\n[2] GCP Infrastructure")
    gcp_dir = os.path.join(INFRA_DIR, "gcp")
    check_required_files("GCP", gcp_dir, [
        "main.tf", "variables.tf", "gcs.tf", "artifact_registry.tf",
        "iam.tf", "apis.tf", "secrets.tf", "cloud_function.tf",
        "cloud_run_job.tf", "outputs.tf",
        "function/main.py", "function/requirements.txt",
    ])
    validate_provider("GCP", gcp_dir)

    # ------- Azure -------
    print(f"\n[3] Azure Infrastructure")
    azure_dir = os.path.join(INFRA_DIR, "azure")
    check_required_files("Azure", azure_dir, [
        "main.tf", "variables.tf", "storage.tf", "acr.tf",
        "identity.tf", "keyvault.tf", "eventgrid.tf", "function.tf",
        "logs.tf", "outputs.tf",
        "function/function_app.py", "function/host.json", "function/requirements.txt",
    ])
    validate_provider("Azure", azure_dir)

    # ------- Cross-provider checks -------
    print(f"\n[4] Cross-provider consistency")

    # Check all providers support the same runtime env vars
    for name, provider_dir in [("AWS", aws_dir), ("GCP", gcp_dir), ("Azure", azure_dir)]:
        variables_tf = os.path.join(provider_dir, "variables.tf")
        with open(variables_tf, "r") as f:
            content = f.read()
        if "agent_runtime" in content:
            test_passed(f"{name}: agent_runtime variable defined")
        else:
            test_failed(f"{name}: agent_runtime variable", "Missing agent_runtime variable")

    # Check GCP has the new multi-runtime secrets
    gcp_secrets = os.path.join(gcp_dir, "secrets.tf")
    with open(gcp_secrets, "r") as f:
        content = f.read()
    if "anthropic_api_key" in content and "openai_api_key" in content:
        test_passed("GCP: both API key secrets configured")
    else:
        test_failed("GCP: API key secrets", "Missing anthropic or openai key secret")

    print()
    print("=" * 60)
    print("ALL TERRAFORM TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
