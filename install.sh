#!/bin/bash

# Define paths
CONFIG_PATH="$HOME/.homeassistant"
CUSTOM_COMPONENTS_PATH="$CONFIG_PATH/custom_components"
COMPONENT_NAME="smart_mini_split"

# Create custom_components directory if it doesn't exist
mkdir -p "$CUSTOM_COMPONENTS_PATH"

# Copy the component
cp -r "./custom_components/$COMPONENT_NAME" "$CUSTOM_COMPONENTS_PATH/"

echo "Smart Mini Split Controller installed to $CUSTOM_COMPONENTS_PATH/$COMPONENT_NAME"
echo "Please add the configuration to your configuration.yaml file and restart Home Assistant."
