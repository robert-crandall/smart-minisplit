#!/usr/bin/env python3
"""Script to update version in manifest.json"""

import json
import sys
from pathlib import Path


def update_version(version_tag: str) -> None:
    """Update version in manifest.json"""
    # Remove 'v' prefix if present
    version = version_tag.lstrip('v')
    
    manifest_path = Path("custom_components/smart_thermostat_controller/manifest.json")
    
    if not manifest_path.exists():
        print(f"Error: {manifest_path} not found")
        sys.exit(1)
    
    # Read current manifest
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
    
    # Update version
    manifest['version'] = version
    
    # Write updated manifest
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
    
    print(f"Updated version to {version} in {manifest_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python update_version.py <version_tag>")
        sys.exit(1)
    
    update_version(sys.argv[1])