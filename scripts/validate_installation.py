#!/usr/bin/env python3
"""Installation validation script for Smart Thermostat Controller"""

import json
import sys
from pathlib import Path
from typing import List, Dict, Any


class InstallationValidator:
    """Validates Smart Thermostat Controller installation"""
    
    def __init__(self, ha_config_path: str = "/config"):
        self.ha_config_path = Path(ha_config_path)
        self.custom_components_path = self.ha_config_path / "custom_components"
        self.integration_path = self.custom_components_path / "smart_thermostat_controller"
        self.errors: List[str] = []
        self.warnings: List[str] = []
    
    def validate_directory_structure(self) -> bool:
        """Validate that all required files are present"""
        required_files = [
            "__init__.py",
            "climate.py", 
            "config_flow.py",
            "const.py",
            "control_manager.py",
            "cooldown_manager.py",
            "coordinator.py",
            "error_handling.py",
            "learning_manager.py",
            "logging_utils.py",
            "manifest.json",
            "models.py",
            "sensor.py",
            "strings.json"
        ]
        
        if not self.integration_path.exists():
            self.errors.append(f"Integration directory not found: {self.integration_path}")
            return False
        
        missing_files = []
        for file_name in required_files:
            file_path = self.integration_path / file_name
            if not file_path.exists():
                missing_files.append(file_name)
        
        if missing_files:
            self.errors.append(f"Missing required files: {', '.join(missing_files)}")
            return False
        
        return True
    
    def validate_manifest(self) -> bool:
        """Validate manifest.json structure and content"""
        manifest_path = self.integration_path / "manifest.json"
        
        try:
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.errors.append(f"Invalid manifest.json: {e}")
            return False
        
        required_keys = ["domain", "name", "version", "config_flow", "integration_type"]
        missing_keys = [key for key in required_keys if key not in manifest]
        
        if missing_keys:
            self.errors.append(f"Missing manifest keys: {', '.join(missing_keys)}")
            return False
        
        # Validate specific values
        if manifest.get("domain") != "smart_thermostat_controller":
            self.errors.append("Invalid domain in manifest.json")
            return False
        
        if not manifest.get("config_flow"):
            self.errors.append("config_flow must be true in manifest.json")
            return False
        
        return True
    
    def validate_strings(self) -> bool:
        """Validate strings.json for config flow"""
        strings_path = self.integration_path / "strings.json"
        
        try:
            with open(strings_path, 'r') as f:
                strings = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.errors.append(f"Invalid strings.json: {e}")
            return False
        
        required_sections = ["config", "options"]
        for section in required_sections:
            if section not in strings:
                self.warnings.append(f"Missing strings section: {section}")
        
        return True
    
    def validate_python_syntax(self) -> bool:
        """Validate Python syntax in all Python files"""
        python_files = list(self.integration_path.glob("*.py"))
        
        for py_file in python_files:
            try:
                with open(py_file, 'r') as f:
                    compile(f.read(), py_file, 'exec')
            except SyntaxError as e:
                self.errors.append(f"Syntax error in {py_file.name}: {e}")
                return False
            except Exception as e:
                self.warnings.append(f"Could not validate {py_file.name}: {e}")
        
        return True
    
    def validate_home_assistant_version(self) -> bool:
        """Check Home Assistant version compatibility"""
        try:
            # Try to import Home Assistant core to check version
            import homeassistant
            from homeassistant.const import __version__ as ha_version
            
            # Parse version numbers
            ha_major, ha_minor = map(int, ha_version.split('.')[:2])
            required_major, required_minor = 2023, 1
            
            if (ha_major, ha_minor) < (required_major, required_minor):
                self.errors.append(
                    f"Home Assistant {required_major}.{required_minor}.0 or newer required, "
                    f"found {ha_version}"
                )
                return False
                
        except ImportError:
            self.warnings.append("Could not verify Home Assistant version")
        
        return True
    
    def validate_dependencies(self) -> bool:
        """Validate that all dependencies are available"""
        try:
            # Test imports that the integration requires
            import asyncio
            import logging
            import json
            from datetime import datetime, timedelta
            from typing import Any, Dict, List, Optional
            from dataclasses import dataclass
            
            # Home Assistant specific imports
            from homeassistant.core import HomeAssistant
            from homeassistant.config_entries import ConfigEntry
            from homeassistant.helpers.entity_platform import AddEntitiesCallback
            
        except ImportError as e:
            self.errors.append(f"Missing required dependency: {e}")
            return False
        
        return True
    
    def run_validation(self) -> Dict[str, Any]:
        """Run all validation checks"""
        results = {
            "success": True,
            "errors": [],
            "warnings": [],
            "checks": {}
        }
        
        checks = [
            ("Directory Structure", self.validate_directory_structure),
            ("Manifest", self.validate_manifest),
            ("Strings", self.validate_strings),
            ("Python Syntax", self.validate_python_syntax),
            ("Home Assistant Version", self.validate_home_assistant_version),
            ("Dependencies", self.validate_dependencies)
        ]
        
        for check_name, check_func in checks:
            try:
                check_result = check_func()
                results["checks"][check_name] = check_result
                if not check_result:
                    results["success"] = False
            except Exception as e:
                results["checks"][check_name] = False
                self.errors.append(f"Error during {check_name} check: {e}")
                results["success"] = False
        
        results["errors"] = self.errors
        results["warnings"] = self.warnings
        
        return results


def main():
    """Main validation function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate Smart Thermostat Controller installation")
    parser.add_argument(
        "--config-path", 
        default="/config",
        help="Path to Home Assistant configuration directory"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format"
    )
    
    args = parser.parse_args()
    
    validator = InstallationValidator(args.config_path)
    results = validator.run_validation()
    
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print("Smart Thermostat Controller Installation Validation")
        print("=" * 50)
        
        for check_name, check_result in results["checks"].items():
            status = "✓ PASS" if check_result else "✗ FAIL"
            print(f"{check_name}: {status}")
        
        if results["errors"]:
            print("\nErrors:")
            for error in results["errors"]:
                print(f"  - {error}")
        
        if results["warnings"]:
            print("\nWarnings:")
            for warning in results["warnings"]:
                print(f"  - {warning}")
        
        print(f"\nOverall Result: {'SUCCESS' if results['success'] else 'FAILED'}")
    
    sys.exit(0 if results["success"] else 1)


if __name__ == "__main__":
    main()