#!/usr/bin/env python3
"""
Integration test runner for Smart Thermostat Controller.

This script runs all integration tests and validates that all requirements
are met according to the specification.
"""
import sys
import subprocess
import time
from pathlib import Path


def run_test_suite(test_file: str, description: str) -> bool:
    """Run a test suite and return success status."""
    print(f"\n{'='*60}")
    print(f"Running {description}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run([
            sys.executable, "-m", "pytest", 
            test_file, 
            "-v", 
            "--tb=short",
            "--disable-warnings"
        ], capture_output=True, text=True, cwd=Path(__file__).parent.parent)
        
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        
        if result.returncode == 0:
            print(f"✅ {description} - PASSED")
            return True
        else:
            print(f"❌ {description} - FAILED")
            return False
            
    except Exception as e:
        print(f"❌ {description} - ERROR: {e}")
        return False


def main():
    """Run all integration tests."""
    print("Smart Thermostat Controller - Integration Test Suite")
    print("=" * 60)
    
    start_time = time.time()
    
    # Test suites to run
    test_suites = [
        ("tests/test_integration.py", "Complete Control Scenarios & Sensor Failure Tests"),
        ("tests/test_integration_validation.py", "Requirements Validation Tests"),
        ("tests/test_performance_validation.py", "Performance & Resource Usage Tests"),
    ]
    
    results = []
    
    for test_file, description in test_suites:
        success = run_test_suite(test_file, description)
        results.append((description, success))
    
    # Summary
    print(f"\n{'='*60}")
    print("INTEGRATION TEST SUMMARY")
    print(f"{'='*60}")
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for description, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{status} - {description}")
    
    print(f"\nOverall Result: {passed}/{total} test suites passed")
    
    elapsed_time = time.time() - start_time
    print(f"Total execution time: {elapsed_time:.2f} seconds")
    
    if passed == total:
        print("\n🎉 All integration tests passed! The Smart Thermostat Controller")
        print("   meets all requirements and performance criteria.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test suite(s) failed. Please review the failures above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())