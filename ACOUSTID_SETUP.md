# AcoustID API Setup Guide

Audio fingerprinting lets the converter identify files even when names like `Track 01.wav` do not contain a real title.

## Get An API Key

1. Create or sign in to an AcoustID account at https://acoustid.org.
2. Open https://acoustid.org/api-key.
3. Create an application key for this converter.

## Configure The Converter

Copy `.env.example` to `.env` and fill in your key:

```env
ACOUSTID_API_KEY=your_acoustid_key_here
```

The script loads `.env` automatically. `.env` is ignored by Git so local keys do not get committed.

## Verify Fingerprinting

Run:

```bash
python wav_to_flac_converter.py "C:\Music" --dry-run --fingerprinting
```

For real conversion, omit `--dry-run`.

## Requirements

AcoustID lookup uses the `pyacoustid` Python package and the Chromaprint `fpcalc` binary. Install Chromaprint from https://acoustid.org/chromaprint if fingerprinting logs say `fpcalc` is missing.
