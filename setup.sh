#!/bin/bash

CONFIG_FILE_NAME="config.yml"

# Check if config.yml file exists
if [ ! -f $CONFIG_FILE_NAME ]; then
  echo "$CONFIG_FILE_NAME not found"
  exit 1
fi

# Get bot token from user input
read -p "Enter bot token: " BOT_TOKEN

# Check if token key exists in config.yml file
if grep -q "token" $CONFIG_FILE_NAME; then
  # Replace token value if new value is not None/Empty
  if [ -n "$BOT_TOKEN" ]; then
    sed -i "s/^token:.*/token: $BOT_TOKEN/" $CONFIG_FILE_NAME
  fi
else
  # Add new token key-value pair to config.yml file
  if [ -n "$BOT_TOKEN" ]; then
    echo "token: $BOT_TOKEN" > $CONFIG_FILE_NAME
  fi
fi