# Enhanced WAV to FLAC Converter with Audio Fingerprinting

A sophisticated Python script that converts WAV files to high-quality FLAC format while preserving folder structure and providing comprehensive metadata enhancement through multiple intelligent lookup strategies, including audio fingerprinting for unknown tracks.

## ✨ Key Features

### 🎵 Audio Processing

- **High-Quality Conversion**: WAV to FLAC with maximum compression (level 12) and 32-bit samples
- **Compatibility Mode**: Optional 16-bit/level 8 compression for better device support
- **Smart FLAC Handling**: Processes existing FLAC files for metadata enhancement without re-conversion
- **Structure Preservation**: Maintains original folder hierarchy in output

### 🏷️ Advanced Metadata Enhancement

- **Multi-Strategy Lookup**: Uses 5 intelligent fallback strategies for metadata discovery
- **Audio Fingerprinting**: AcoustID integration for identifying unknown tracks
- **MusicBrainz Integration**: Comprehensive music database lookup with rate limiting
- **Album-Based Matching**: Smart tracklist matching for generic filenames ("Track 01.wav")
- **International Support**: Enhanced handling of non-English artists and albums
- **Metadata Completeness Check**: Only performs lookups when metadata is incomplete
- **Directory Structure Parsing**: Intelligent extraction from folder/file names

### 🌍 International & Generic File Support

- **Generic Filename Detection**: Recognizes patterns like "Track 01", "01 Track", "Pista 01"
- **Multi-Language Patterns**: Supports English, Spanish, and other language conventions
- **Similarity Scoring**: Intelligent matching with configurable thresholds
- **Fallback Strategies**: Multiple search approaches for difficult-to-match content

### ⚡ Performance & Reliability

- **Smart Caching**: Reduces API calls with intelligent result caching
- **Rate Limiting**: Respects MusicBrainz API limits (1 request/second)
- **Comprehensive Logging**: Detailed progress tracking and error reporting
- **Statistics Tracking**: Detailed summary of metadata sources and success rates

## 🚀 Quick Start

### Using the Windows Batch File (Recommended)

1. **Download** all files to a folder or clone from GitHub
2. **Double-click** `convert_wav_to_flac.bat`
3. **Follow the prompts** to:
   - Enter your music folder path
   - Choose quality mode (High Quality vs Compatibility)
   - Select metadata strategy
4. **Wait** for the conversion to complete

### Installation from GitHub

```bash
# Clone the repository
git clone https://github.com/[your-username]/wav-to-flac-converter.git
cd wav-to-flac-converter

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## 💻 Command Line Usage

### Basic Usage

```bash
# Convert with enhanced metadata lookup
python wav_to_flac_converter.py "C:\Music\WAV Files"

# Compatibility mode for older devices
python wav_to_flac_converter.py "C:\Music" --compatibility

# No metadata lookup at all
python wav_to_flac_converter.py "C:\Music" --no-metadata
```

### Command Line Options

```
positional arguments:
  source_path           Path to directory containing WAV/FLAC files

optional arguments:
  -h, --help            Show help message
  -o, --output OUTPUT   Output folder name (default: "FLAC CONVERTER")
  -c, --compatibility   Use 16-bit/level 8 for device compatibility
  -n, --no-metadata     Disable automatic metadata lookup
```

## 🔍 Metadata Lookup Strategies

The enhanced script uses a sophisticated multi-step strategy for metadata discovery:

### 1. **Existing Metadata Check**

- Reads current FLAC metadata
- Skips lookup if metadata is complete and high-quality
- Checks for MusicBrainz IDs and non-generic titles

### 2. **Album-Based Lookup** (for generic files)

- Searches complete album tracklists from MusicBrainz
- Matches tracks by position for files like "01 Track.flac"
- Perfect for properly organized but generically named files

### 3. **Individual Track Search**

- Direct MusicBrainz recording lookup
- Multiple search strategies with similarity scoring
- Handles international artists and various naming conventions

### 4. **Audio Fingerprinting** ⭐ *Enhanced Feature*

- Uses AcoustID to identify unknown tracks by audio content
- Works even with completely unknown or mislabeled files
- Requires internet connection for lookup
- High confidence threshold for accurate results

### 5. **Directory Structure Fallback**

- Parses artist/album/track from folder structure
- Extracts years, track numbers, and cleans up names
- Merges with any existing partial metadata

## 📁 Supported File Structures

The script intelligently handles various directory structures:

```
Music/
├── Artist Name/
│   ├── Album Name (2023)/
│   │   ├── 01 Track Name.wav → Gets full metadata
│   │   └── Track 02.wav → Uses album lookup + fingerprinting
│   └── 2020 - Another Album/
│       └── 05. Track.flac → Enhances existing metadata
└── Various Artists/
    └── Compilation Album/
        └── Artist - Song.wav → Individual track lookup
```

## 🎵 Audio Fingerprinting

The enhanced version includes **AcoustID** integration for identifying unknown tracks:

### How It Works

1. **Generates Audio Fingerprint**: Creates unique acoustic signature
2. **Queries AcoustID Database**: Searches millions of known recordings
3. **Retrieves Metadata**: Gets complete track information from matches
4. **High Confidence**: Only uses matches with sufficient similarity

### Perfect For

- **Compilation Discs**: Unofficial mixes and DJ sets
- **Unknown Files**: Files with missing or incorrect metadata
- **International Content**: Tracks not well-covered by text search
- **Live Recordings**: Concert recordings that match studio versions

## 📊 Enhanced Statistics

The script provides detailed statistics about metadata sources:

```
CONVERSION SUMMARY
================================================================================
Total files found:      500
WAV files converted:    450
FLAC files processed:   50
Failed conversions:     0

METADATA SOURCES:
Already complete:       120    # Files with complete metadata
MusicBrainz lookup:     200    # Found via database search
Audio fingerprinting:   80     # Identified by audio content
Directory structure:    100    # Used folder/filename info

TIMING:
Total time elapsed:     45.2 minutes
Average time per file:  5.4 seconds
Success rate:           100.0%
```

## 🛠️ Requirements

### System Requirements

- **Python 3.7+**
- **FFmpeg** (installed automatically via batch file on Windows)
- **Internet connection** (for metadata lookup and fingerprinting)

### Python Dependencies

```
pydub>=0.25.1
mutagen>=1.47.0
musicbrainzngs>=0.7.1
pyacoustid>=1.3.0
pylast>=5.0.0
```

## 🔧 Advanced Configuration

### Metadata Quality Levels

- **Complete**: Has MusicBrainz IDs and proper titles
- **Partial**: Has basic info but could be enhanced
- **Generic**: Uses patterns like "Track 01" (triggers enhanced lookup)
- **Missing**: No metadata (uses all strategies)

### Fingerprinting Accuracy

- **High Confidence**: Used for automatic metadata assignment
- **Medium Confidence**: Considered but may require verification
- **Low Confidence**: Ignored to prevent incorrect assignments

### Cache Management

- **MusicBrainz Cache**: Stores API results to reduce repeated calls
- **Album Cache**: Caches complete album tracklists
- **Fingerprint Cache**: Stores fingerprint results for efficiency
- **Automatic Cleanup**: Caches persist between runs for performance

## 🚨 Troubleshooting

### Common Issues

#### "ffmpeg not found"

- **Windows**: Run the batch file - it installs FFmpeg automatically
- **Manual**: Download FFmpeg and add to PATH

#### "No matches found via fingerprinting"

- **Normal**: Not all tracks are in the AcoustID database
- **Solution**: Script automatically falls back to other methods

#### Internet connection issues

- **Fingerprinting**: Requires internet; script will skip if offline
- **MusicBrainz**: Also requires internet; use `--no-metadata` for offline conversion only

#### Generic filenames not being enhanced

- **Check**: Ensure files match patterns (Track 01, 01 Track, etc.)
- **Solution**: Use fingerprinting for unknown files
- **Alternative**: Rename files to include actual song titles

### Performance Tips

1. **Use metadata lookup selectively**: Disable for simple conversions
2. **Organize files first**: Good folder structure improves results
3. **Check logs**: Review `conversion_enhanced.log` for detailed info
4. **Batch processing**: Process large collections in smaller chunks

## 📈 Version History

### v2.1 (Current) - Enhanced with Audio Fingerprinting

- ✅ **Audio fingerprinting** via AcoustID for unknown tracks
- ✅ **FLAC file processing** without re-conversion
- ✅ **Metadata completeness checking** to avoid unnecessary lookups
- ✅ **Enhanced statistics** showing metadata sources
- ✅ **Improved error handling** and user feedback

### v2.0 - Advanced Metadata Enhancement

- ✅ Album-based track matching for generic filenames
- ✅ International artist support with similarity scoring
- ✅ Multiple fallback strategies for metadata lookup
- ✅ Enhanced generic filename detection
- ✅ Comprehensive caching and rate limiting

### v1.0 - Basic Converter

- ✅ WAV to FLAC conversion with quality options
- ✅ Basic metadata lookup via MusicBrainz
- ✅ Directory structure preservation
- ✅ Windows batch file interface

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues, feature requests, or pull requests.

### Future Enhancements

- **Cover Art Download**: Automatic album artwork embedding
- **Additional Fingerprinting**: Multiple fingerprinting providers
- **Batch Metadata Editor**: GUI for manual metadata correction
- **Cloud Storage Support**: Direct integration with cloud services
- **Cross-platform GUI**: Native desktop application

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **MusicBrainz**: Comprehensive music metadata database
- **AcoustID**: Audio fingerprinting service
- **FFmpeg**: Audio processing engine
- **Python Audio Libraries**: pydub, mutagen for audio handling

---

*Happy converting! 🎵*
