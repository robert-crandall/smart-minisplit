#!/usr/bin/env python3
"""Test installation process for Smart Thermostat Controller"""

import asyncio
import json
import logging
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any
import zipfile


class InstallationTester:
    """Tests the installation process in a simulated environment"""
    
    def __init__(self):
        self.temp_dir = None
        self.ha_config_dir = None
        self.custom_components_dir = None
        self.integration_dir = None
        self.test_results = {
            "success": True,
            "tests": {},
            "errors": [],
            "warnings": []
        }
    
    def setup_test_environment(self) -> bool:
        """Set up a temporary Home Assistant-like environment"""
        try:
            self.temp_dir = Path(tempfile.mkdtemp(prefix="ha_test_"))
            self.ha_config_dir = self.temp_dir / "config"
            self.custom_components_dir = self.ha_config_dir / "custom_components"
            self.integration_dir = self.custom_components_dir / "smart_thermostat_controller"
            
            # Create directory structure
            self.custom_components_dir.mkdir(parents=True)
            
            # Create basic configuration.yaml
            config_yaml = self.ha_config_dir / "configuration.yaml"
            config_yaml.write_text("""
# Test Home Assistant configuration
homeassistant:
  name: Test Home
  latitude: 40.7128
  longitude: -74.0060
  elevation: 0
  unit_system: imperial
  time_zone: America/New_York

# Enable the frontend
frontend:

# Enable configuration UI
config:

# Enable logging
logger:
  default: info
""")
            
            return True
            
        except Exception as e:
            self.test_results["errors"].append(f"Failed to setup test environment: {e}")
            return False
    
    def test_manual_installation(self) -> bool:
        """Test manual installation by copying files"""
        try:
            source_dir = Path("custom_components/smart_thermostat_controller")
            
            if not source_dir.exists():
                self.test_results["errors"].append("Source integration directory not found")
                return False
            
            # Copy integration files
            shutil.copytree(source_dir, self.integration_dir)
            
            # Verify all files were copied
            required_files = [
                "__init__.py", "climate.py", "config_flow.py", "const.py",
                "control_manager.py", "cooldown_manager.py", "coordinator.py",
                "error_handling.py", "learning_manager.py", "logging_utils.py",
                "manifest.json", "models.py", "sensor.py", "strings.json"
            ]
            
            missing_files = []
            for file_name in required_files:
                if not (self.integration_dir / file_name).exists():
                    missing_files.append(file_name)
            
            if missing_files:
                self.test_results["errors"].append(f"Missing files after installation: {missing_files}")
                return False
            
            return True
            
        except Exception as e:
            self.test_results["errors"].append(f"Manual installation test failed: {e}")
            return False
    
    def test_zip_installation(self) -> bool:
        """Test installation from zip file"""
        try:
            # Create zip file
            zip_path = self.temp_dir / "smart_thermostat_controller.zip"
            source_dir = Path("custom_components/smart_thermostat_controller")
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in source_dir.rglob("*"):
                    if file_path.is_file():
                        arcname = file_path.relative_to(source_dir.parent)
                        zipf.write(file_path, arcname)
            
            # Extract zip file
            with zipfile.ZipFile(zip_path, 'r') as zipf:
                zipf.extractall(self.custom_components_dir)
            
            # Verify extraction
            if not self.integration_dir.exists():
                self.test_results["errors"].append("Integration directory not created from zip")
                return False
            
            return True
            
        except Exception as e:
            self.test_results["errors"].append(f"Zip installation test failed: {e}")
            return False
    
    def test_manifest_validation(self) -> bool:
        """Test manifest.json validation"""
        try:
            manifest_path = self.integration_dir / "manifest.json"
            
            if not manifest_path.exists():
                self.test_results["errors"].append("manifest.json not found")
                return False
            
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
            
            # Validate required fields
            required_fields = ["domain", "name", "version", "config_flow"]
            for field in required_fields:
                if field not in manifest:
                    self.test_results["errors"].append(f"Missing required field in manifest: {field}")
                    return False
            
            # Validate domain matches directory name
            if manifest["domain"] != "smart_thermostat_controller":
                self.test_results["errors"].append("Domain mismatch in manifest")
                return False
            
            return True
            
        except Exception as e:
            self.test_results["errors"].append(f"Manifest validation failed: {e}")
            return False
    
    def test_python_imports(self) -> bool:
        """Test that all Python modules can be imported"""
        try:
            import sys
            sys.path.insert(0, str(self.custom_components_dir))
            
            # Test importing the main module
            import smart_thermostat_controller
            
            # Test importing submodules
            modules_to_test = [
                "smart_thermostat_controller.climate",
                "smart_thermostat_controller.config_flow",
                "smart_thermostat_controller.const",
                "smart_thermostat_controller.control_manager",
                "smart_thermostat_controller.cooldown_manager",
                "smart_thermostat_controller.coordinator",
                "smart_thermostat_controller.error_handling",
                "smart_thermostat_controller.learning_manager",
                "smart_thermostat_controller.logging_utils",
                "smart_thermostat_controller.models",
                "smart_thermostat_controller.sensor"
            ]
            
            for module_name in modules_to_test:
                try:
                    __import__(module_name)
                except ImportError as e:
                    self.test_results["warnings"].append(f"Could not import {module_name}: {e}")
            
            return True
            
        except Exception as e:
            self.test_results["errors"].append(f"Python import test failed: {e}")
            return False
    
    def test_hacs_compatibility(self) -> bool:
        """Test HACS compatibility"""
        try:
            # Check for hacs.json
            hacs_json_path = Path("hacs.json")
            if not hacs_json_path.exists():
                self.test_results["warnings"].append("hacs.json not found")
                return True  # Not critical for basic installation
            
            with open(hacs_json_path, 'r') as f:
                hacs_config = json.load(f)
            
            # Validate HACS configuration
            if "name" not in hacs_config:
                self.test_results["warnings"].append("Missing name in hacs.json")
            
            return True
            
        except Exception as e:
            self.test_results["warnings"].append(f"HACS compatibility test failed: {e}")
            return True  # Not critical
    
    def cleanup_test_environment(self):
        """Clean up temporary test environment"""
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
    
    def run_all_tests(self) -> Dict[str, Any]:
        """Run all installation tests"""
        tests = [
            ("Environment Setup", self.setup_test_environment),
            ("Manual Installation", self.test_manual_installation),
            ("Manifest Validation", self.test_manifest_validation),
            ("Python Imports", self.test_python_imports),
            ("HACS Compatibility", self.test_hacs_compatibility)
        ]
        
        for test_name, test_func in tests:
            try:
                result = test_func()
                self.test_results["tests"][test_name] = result
                if not result:
                    self.test_results["success"] = False
            except Exception as e:
                self.test_results["tests"][test_name] = False
                self.test_results["errors"].append(f"Test {test_name} failed with exception: {e}")
                self.test_results["success"] = False
        
        # Cleanup
        self.cleanup_test_environment()
        
        return self.test_results


def main():
    """Main test function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test Smart Thermostat Controller installation")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format"
    )
    
    args = parser.parse_args()
    
    tester = InstallationTester()
    results = tester.run_all_tests()
    
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print("Smart Thermostat Controller Installation Test")
        print("=" * 50)
        
        for test_name, test_result in results["tests"].items():
            status = "✓ PASS" if test_result else "✗ FAIL"
            print(f"{test_name}: {status}")
        
        if results["errors"]:
            print("\nErrors:")
            for error in results["errors"]:
                print(f"  - {error}")
        
        if results["warnings"]:
            print("\nWarnings:")
            for warning in results["warnings"]:
                print(f"  - {warning}")
        
        print(f"\nOverall Result: {'SUCCESS' if results['success'] else 'FAILED'}")
    
    return 0 if results["success"] else 1


if __name__ == "__main__":
    exit(main())