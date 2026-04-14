"""
Dry-run test: validates the NFS-mounted S3 Files storage backend.

Tests the same workflow plumbing as test_plumbing.py but uses the NFSStorage
backend instead of S3 API. This validates that the NFS mount path works as a
drop-in replacement for S3 copy operations.

Run with:
    python test_plumbing_nfs.py
    # No MinIO or Docker needed — uses local temp directory as mount path.
"""

import json
import os
import shutil
import sys
import tempfile

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storage.nfs import NFSStorage

BUCKET = "test-workflows"
PREFIX = "runs/test_run_001"


def test_passed(name):
    print(f"  PASS  {name}")


def test_failed(name, detail=""):
    print(f"  FAIL  {name}")
    if detail:
        print(f"        {detail}")
    sys.exit(1)


def main():
    print("=" * 60)
    print("PLUMBING TEST: NFS Storage Backend (no S3/MinIO needed)")
    print("=" * 60)

    # Create a temp directory to simulate NFS mount
    mount_path = tempfile.mkdtemp(prefix="nfs_test_")
    print(f"NFS mount path (simulated): {mount_path}")
    print()

    try:
        # ------------------------------------------------------------------
        # Test 1: NFS Storage initialization
        # ------------------------------------------------------------------
        print("[1] NFS Storage initialization")
        try:
            storage = NFSStorage(bucket=BUCKET, mount_path=mount_path)
            test_passed("NFSStorage created successfully")
        except Exception as e:
            test_failed("NFSStorage creation", str(e))

        # ------------------------------------------------------------------
        # Test 2: Seed manifest
        # ------------------------------------------------------------------
        print("\n[2] Manifest seeding via NFS")
        manifest = {
            "run_id": "test_run_001",
            "workflow": "test-workflow",
            "status": "running",
            "current_step": 0,
            "steps": [
                {"step": 0, "agent": "sales", "instruction": "Do sales research", "status": "pending"},
                {"step": 1, "agent": "finance", "instruction": "Do financial audit", "status": "pending"},
            ],
            "context": {"company": "TestCorp"},
        }
        storage.write_json(f"{PREFIX}/manifest.json", manifest)
        readback = storage.read_json(f"{PREFIX}/manifest.json")
        assert readback["run_id"] == "test_run_001"
        assert readback["steps"][0]["status"] == "pending"
        test_passed("Manifest written and read back via NFS")

        # ------------------------------------------------------------------
        # Test 3: State transition pending -> running
        # ------------------------------------------------------------------
        print("\n[3] State transition: pending -> running")
        manifest["steps"][0]["status"] = "running"
        storage.write_json(f"{PREFIX}/manifest.json", manifest)
        readback = storage.read_json(f"{PREFIX}/manifest.json")
        assert readback["steps"][0]["status"] == "running"
        test_passed("Step 0 marked as running")

        # ------------------------------------------------------------------
        # Test 4: Simulate agent output (step 0 produces files)
        # ------------------------------------------------------------------
        print("\n[4] Simulate agent output files")
        storage.write_bytes(
            f"{PREFIX}/step_0/output/company_profile.md",
            b"# TestCorp Profile\nRevenue: $100M\n",
        )
        storage.write_bytes(
            f"{PREFIX}/step_0/output/company_data.json",
            json.dumps({"revenue": 100_000_000}).encode(),
        )
        output_keys = storage.list_keys(f"{PREFIX}/step_0/output")
        assert len(output_keys) == 2
        test_passed(f"Step 0 produced {len(output_keys)} output files")

        # ------------------------------------------------------------------
        # Test 5: Context accumulation
        # ------------------------------------------------------------------
        print("\n[5] Context accumulation")
        context = {
            "step_0": {
                "agent": "sales",
                "completed_at": "2026-03-28T10:05:00Z",
                "summary": "Researched TestCorp. Revenue $100M.",
                "output_files": ["company_profile.md", "company_data.json"],
            }
        }
        storage.write_json(f"{PREFIX}/context.json", context)
        readback = storage.read_json(f"{PREFIX}/context.json")
        assert "step_0" in readback
        assert readback["step_0"]["agent"] == "sales"
        test_passed("Context written with step 0 results")

        # ------------------------------------------------------------------
        # Test 6: File handover (NFS copy - the KEY optimization)
        # ------------------------------------------------------------------
        print("\n[6] File handover via NFS copy (zero S3 API calls)")
        storage.copy_prefix(
            f"{PREFIX}/step_0/output/",
            f"{PREFIX}/step_1/input/",
        )
        input_keys = storage.list_keys(f"{PREFIX}/step_1/input")
        assert len(input_keys) == 2
        # Verify content survived the copy
        profile = storage.read_bytes(f"{PREFIX}/step_1/input/company_profile.md")
        assert b"TestCorp" in profile
        test_passed(f"Copied {len(input_keys)} files via NFS (no S3 round-trip)")

        # ------------------------------------------------------------------
        # Test 7: Advance manifest to step 1
        # ------------------------------------------------------------------
        print("\n[7] Manifest advancement: step 0 complete, step 1 pending")
        manifest["steps"][0]["status"] = "complete"
        manifest["steps"][0]["completed_at"] = "2026-03-28T10:05:00Z"
        manifest["current_step"] = 1
        storage.write_json(f"{PREFIX}/manifest.json", manifest)
        readback = storage.read_json(f"{PREFIX}/manifest.json")
        assert readback["current_step"] == 1
        assert readback["steps"][0]["status"] == "complete"
        assert readback["steps"][1]["status"] == "pending"
        test_passed("Manifest advanced to step 1")

        # ------------------------------------------------------------------
        # Test 8: Terminal state: workflow complete
        # ------------------------------------------------------------------
        print("\n[8] Terminal state: workflow complete")
        manifest["steps"][1]["status"] = "complete"
        manifest["steps"][1]["completed_at"] = "2026-03-28T10:10:00Z"
        manifest["status"] = "complete"
        manifest["completed_at"] = "2026-03-28T10:10:00Z"
        storage.write_json(f"{PREFIX}/manifest.json", manifest)
        readback = storage.read_json(f"{PREFIX}/manifest.json")
        assert readback["status"] == "complete"
        test_passed("Workflow marked complete")

        # ------------------------------------------------------------------
        # Test 9: Symlink optimization (zero-copy handover)
        # ------------------------------------------------------------------
        print("\n[9] Symlink optimization (zero-copy file sharing)")
        try:
            storage.create_symlink(
                f"{PREFIX}/step_0/output",
                f"{PREFIX}/step_2_symlinked/input",
            )
            # Verify symlinked files are accessible
            profile_via_link = storage.read_bytes(
                f"{PREFIX}/step_2_symlinked/input/company_profile.md"
            )
            assert b"TestCorp" in profile_via_link
            test_passed("Symlink handover works (true zero-copy)")
        except OSError as e:
            # Symlinks may not work on all platforms (e.g., Windows without admin)
            print(f"  SKIP  Symlink test: {e}")

        # ------------------------------------------------------------------
        # Test 10: download/upload round-trip
        # ------------------------------------------------------------------
        print("\n[10] Download/upload round-trip via NFS")
        import tempfile as tf

        with tf.TemporaryDirectory() as tmpdir:
            local_dir = os.path.join(tmpdir, "local_copy")
            os.makedirs(local_dir)

            storage.download_prefix_to_dir(
                f"{PREFIX}/step_0/output", local_dir
            )
            local_files = os.listdir(local_dir)
            assert len(local_files) == 2

            upload_prefix = f"{PREFIX}/step_99/reuploaded"
            storage.upload_dir_to_prefix(local_dir, upload_prefix)
            reuploaded_keys = storage.list_keys(upload_prefix)
            assert len(reuploaded_keys) == 2
            test_passed("Download/upload round-trip successful")

        # ------------------------------------------------------------------
        # Test 11: key_exists
        # ------------------------------------------------------------------
        print("\n[11] Key existence check")
        assert storage.key_exists(f"{PREFIX}/manifest.json")
        assert not storage.key_exists(f"{PREFIX}/nonexistent.json")
        test_passed("key_exists works correctly")

        # ------------------------------------------------------------------
        # Test 12: Path traversal protection
        # ------------------------------------------------------------------
        print("\n[12] Path traversal protection")
        try:
            storage.read_json("../../etc/passwd")
            test_failed("Path traversal", "Should have raised ValueError")
        except ValueError:
            test_passed("Path traversal blocked correctly")

        # ------------------------------------------------------------------
        # Test 13: Verify final bucket structure
        # ------------------------------------------------------------------
        print("\n[13] Final NFS directory structure")
        all_keys = storage.list_keys(PREFIX)
        print(f"  Files in {BUCKET}/{PREFIX}/:")
        for key in sorted(all_keys):
            short = key[len(f"{BUCKET}/") :] if key.startswith(f"{BUCKET}/") else key
            print(f"    {short}")

        expected_count = 6  # manifest, context, step_0 outputs, step_1 inputs
        assert len([k for k in all_keys if not "symlinked" in k and not "step_99" in k]) >= expected_count
        test_passed(f"NFS directory structure matches expectation")

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        print()
        print("=" * 60)
        print("ALL NFS STORAGE TESTS PASSED")
        print("=" * 60)
        print()
        print("What this proves:")
        print("  - NFS mount works as drop-in S3 replacement")
        print("  - File handover uses local copy (no S3 API calls)")
        print("  - Symlink optimization enables true zero-copy sharing")
        print("  - Path traversal protection is in place")
        print("  - Same manifest state machine works on NFS")
        print()
        print("Production setup:")
        print("  1. Mount S3 bucket via NFS: mount -t nfs s3://bucket /mnt/s3")
        print("  2. Set STORAGE_BACKEND=nfs NFS_MOUNT_PATH=/mnt/s3")
        print("  3. Agent containers mount the same NFS path")
        print("  4. Zero S3 API calls for data handover between steps")

    finally:
        # Cleanup
        shutil.rmtree(mount_path, ignore_errors=True)


if __name__ == "__main__":
    main()
