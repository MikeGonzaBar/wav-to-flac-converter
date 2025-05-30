@echo off
title Enhanced WAV to FLAC Converter
echo ================================================================================
echo                     ENHANCED WAV TO FLAC CONVERTER
echo ================================================================================
echo.
echo This enhanced converter features:
echo  - Intelligent metadata lookup for international artists
echo  - Album-based track matching for generic filenames (Track 01.wav, etc.)
echo  - Multiple fallback strategies for metadata
echo  - Smart directory structure parsing
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python from https://www.python.org/
    pause
    exit /b 1
)

REM Check if virtual environment exists
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
)

REM Activate virtual environment
echo Activating virtual environment...
call .venv\Scripts\activate.bat

REM Install/upgrade requirements
echo Installing required packages...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: Failed to install required packages
    echo Trying to fix pip...
    python -m ensurepip --upgrade
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Installation failed. Please check your internet connection.
        pause
        exit /b 1
    )
)

echo.
echo ================================================================================
echo                              CONVERSION OPTIONS
echo ================================================================================
echo.

REM Get source path
set /p source_path="Enter the path to your WAV files (drag folder here or type path): "

REM Remove quotes if present
set source_path=%source_path:"=%

REM Check if source exists
if not exist "%source_path%" (
    echo ERROR: The specified path does not exist: %source_path%
    pause
    exit /b 1
)

echo.
echo Select conversion quality:
echo 1. High Quality (32-bit, compression level 12) - Best quality, larger files
echo 2. Compatibility (16-bit, compression level 8) - Better device support
echo.
set /p quality="Enter your choice (1 or 2): "

echo.
echo Select metadata strategy:
echo 1. Enhanced Metadata - Full metadata lookup with smart strategies
echo 2. Basic Metadata - Directory structure only (faster)
echo 3. No Metadata - Conversion only (fastest)
echo.
set /p metadata="Enter your choice (1, 2, or 3): "

echo.
echo Select output folder:
echo 1. Default ("FLAC CONVERTER")
echo 2. Custom folder name
echo.
set /p output_choice="Enter your choice (1 or 2): "

set output_folder=FLAC CONVERTER
if "%output_choice%"=="2" (
    set /p output_folder="Enter custom output folder name: "
)

echo.
echo ================================================================================
echo                            CONVERSION SETTINGS
echo ================================================================================
echo Source Path: %source_path%
echo Output Folder: %output_folder%

REM Build command based on selections
set command=python wav_to_flac_converter.py "%source_path%" --output "%output_folder%"

if "%quality%"=="2" (
    set command=%command% --compatibility
    echo Quality: Compatibility Mode (16-bit, level 8)
) else (
    echo Quality: High Quality Mode (32-bit, level 12)
)

if "%metadata%"=="2" (
    set command=%command% --no-metadata
    echo Metadata: Directory Structure Only
) else if "%metadata%"=="3" (
    set command=%command% --no-metadata
    echo Metadata: Disabled
) else (
    echo Metadata: Enhanced Lookup with Smart Strategies
)

echo.
echo Command to execute:
echo %command%
echo.
set /p confirm="Proceed with conversion? (Y/N): "

if /i not "%confirm%"=="Y" (
    echo Conversion cancelled.
    pause
    exit /b 0
)

echo.
echo ================================================================================
echo                              STARTING CONVERSION
echo ================================================================================
echo.
echo TIP: For generic filenames (Track 01.wav), the enhanced script will:
echo  - Search for complete album tracklist from MusicBrainz
echo  - Match tracks by position automatically
echo  - Fall back to individual track search if needed
echo.
echo For international artists with limited MusicBrainz coverage:
echo  - Multiple search strategies will be attempted
echo  - Directory structure metadata will be used as fallback
echo.
echo The conversion may take some time depending on:
echo  - Number of files
echo  - Metadata lookup strategy selected
echo  - Internet connection speed (for metadata lookup)
echo.

REM Execute the conversion
%command%

set exit_code=%errorlevel%

echo.
echo ================================================================================
echo                              CONVERSION COMPLETE
echo ================================================================================

if %exit_code%==0 (
    echo SUCCESS: All files converted successfully!
    echo Check the "%output_folder%" folder for your FLAC files.
) else (
    echo WARNING: Some files may have failed to convert.
    echo Check the conversion_enhanced.log file for details.
)

echo.
echo Log file: conversion_enhanced.log
echo.
pause 