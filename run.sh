#!/bin/bash

CONFIG_FILE_NAME="config.yml"
VENV_FOLDER="venv"
PYTHON_VERSION_REQUIRED="3.10"
PYTHON_EXE="python3"

# Copy config file example if config file does not already exist
if [ ! -f $CONFIG_FILE_NAME ]; then
    cp config.yml.example $CONFIG_FILE_NAME
fi

# check if the current Python version is at least the required version
if ! $PYTHON_EXE -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else -1)' > /dev/null 2>&1; then  # false
	echo "Using '$PYTHON_EXE' executable: version $PYTHON_VERSION_REQUIRED or later is not found."
	PYTHON_EXE="python3"
	echo "Attempting to use '$PYTHON_EXE' executable instead."

	for minor_ver in {19..10..1}  # going in reverse to use the latest available version
	do
		PYTHON_EXE="python3.$minor_ver"

		if ! (! $PYTHON_EXE -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else -1)' > /dev/null 2>&1); then
			echo "Found a compatible python version. Using $PYTHON_EXE"
			break

		elif [ "$minor_ver" -eq 10 ]; then
			echo "Unable to find a compatible version of Python. Please install Python $PYTHON_VERSION_REQUIRED or later and try again."
			exit 1
		fi
	done;
fi

# Continue with script if Python version is sufficient
echo "Starting the script with $PYTHON_EXE"

# Check if venv is installed, install if needed
if $PYTHON_EXE -c "import ensurepip" &>/dev/null; then
    echo "ensurepip module found"
else
    echo "ensurepip module not found, attempting to install"
    if command -v apt-get &>/dev/null; then
        # Linux
        if [ "$(whoami)" == "root" ]; then
            apt-get update
            apt-get install -y $PYTHON_EXE-venv
        else
            echo "Sudo privileges are required to install venv. Please enter your password."
            sudo apt-get update
            sudo apt-get install -y $PYTHON_EXE-venv
        fi
    elif command -v brew &>/dev/null; then
        # macOS
        brew install $PYTHON_EXE
    else
        echo "Unable to install venv: package manager not found"
        exit 1
    fi
fi

# Create virtual environment
$PYTHON_EXE -m venv $VENV_FOLDER

$VENV_FOLDER/bin/pip3 install --upgrade pip
$VENV_FOLDER/bin/pip3 install -r requirements.txt


# Activate virtual environment and upgrade pip
source $VENV_FOLDER/bin/activate
pip3 install --upgrade pip

# Install necessary packages
pip3 install -r requirements.txt


# Check if token key exists in config.yml file
if grep -q "^token:" "$CONFIG_FILE_NAME"; then
    echo "Token key exists"
else
    if [ -z "$BOT_TOKEN" ]; then
        # Run setup script
        ./setup.sh
    fi
fi

# Run main script
python3 main.py